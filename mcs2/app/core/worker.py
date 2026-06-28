

import queue
import threading
import time

from app.core.mailer import Mailer, SMTPDeliveryError
from app.core.queue_manager import (
    get_queue,
    increment_failed,
    increment_processed,
    mark_worker_status,
    unregister_worker,
    worker_heartbeat,
)
from app.core.rate_limiter import get_rate_limiter
from app.core.template_engine import render_template
from app.database.db import (
    is_campaign_completed,
    record_email_log,
    update_campaign_counts,
    update_campaign_heartbeat,
    update_campaign_status,
    update_recipient_status,
)
from app.utils.logger import logger
from config import CONFIG


BATCH_SIZE = CONFIG.BATCH_SIZE


class EmailWorker(threading.Thread):
    def __init__(self, campaign_id, subject, mailer=None, rate_limiter=None,
                 enforce_schedule=True, template_name="campaign.html"):
        super().__init__(name=f"campaign-{campaign_id}-worker", daemon=True)
        self.campaign_id = campaign_id
        self.subject = subject
        self.mailer = mailer or Mailer()
        self.rate_limiter = rate_limiter or get_rate_limiter()
        self.enforce_schedule = enforce_schedule
        self.template_name = template_name or "campaign.html"
        self.stop_event = threading.Event()
        self.last_error = None

    def stop(self):
        self.stop_event.set()

    def _heartbeat(self, status="running"):
        worker_heartbeat(self.campaign_id)
        mark_worker_status(self.campaign_id, status)
        try:
            update_campaign_heartbeat(self.campaign_id)
        except Exception:
            logger.exception("Unable to persist heartbeat for campaign %s", self.campaign_id)

    def _wait_for_send_window(self):
        while self.enforce_schedule and not self.rate_limiter.can_send():
            self._heartbeat("paused")
            wait_seconds = self.rate_limiter.seconds_until_resume()
            logger.info("Campaign %s paused for business hours/quota; resume in %ss",
                        self.campaign_id, wait_seconds)
            if self.stop_event.wait(min(wait_seconds, 60)):
                return False
        return not self.stop_event.is_set()

    def _send_one(self, recipient):
        email = recipient["work_email"]
        recipient_id = recipient.get("id")
        started = time.monotonic()
        update_recipient_status(
            email, "processing", campaign_id=self.campaign_id, recipient_id=recipient_id
        )
        try:
            html_content = render_template(self.template_name, recipient)
            result = self.mailer.send_email(email, self.subject, html_content)
            retried = result.get("attempts", 1) > 1 if isinstance(result, dict) else False
            update_recipient_status(
                email, "sent", campaign_id=self.campaign_id, recipient_id=recipient_id,
                increment_retry=retried,
            )
            record_email_log(
                recipient_id, self.campaign_id, "sent", "accepted", "success",
                int((time.monotonic() - started) * 1000),
            )
            increment_processed(self.campaign_id)
            self.rate_limiter.email_sent()
            logger.info("Campaign %s delivered email to %s", self.campaign_id, email)
        except SMTPDeliveryError as exc:
            self.last_error = str(exc)
            update_recipient_status(
                email, "failed", str(exc), self.campaign_id, exc.category,
                increment_retry=exc.retryable, recipient_id=recipient_id,
            )
            record_email_log(
                recipient_id, self.campaign_id, "failed", str(exc), exc.category,
                int((time.monotonic() - started) * 1000),
            )
            increment_failed(self.campaign_id)
            logger.error("Campaign %s failed delivery to %s: %s", self.campaign_id, email, exc)
        except Exception as exc:
            self.last_error = str(exc)
            update_recipient_status(
                email, "failed", str(exc), self.campaign_id,
                increment_retry=False, recipient_id=recipient_id,
            )
            record_email_log(
                recipient_id, self.campaign_id, "failed", str(exc), "unknown",
                int((time.monotonic() - started) * 1000),
            )
            increment_failed(self.campaign_id)
            logger.exception("Campaign %s isolated recipient failure for %s", self.campaign_id, email)
        finally:
            update_campaign_counts(self.campaign_id)
            self._heartbeat()

    def run(self):
        campaign_queue = get_queue(self.campaign_id)
        logger.info("Worker started for campaign %s with queue depth %s",
                    self.campaign_id, campaign_queue.qsize())
        try:
            update_campaign_status(self.campaign_id, "sending")
            self._heartbeat("connecting")
            try:
                self.mailer.connect()
            except Exception as exc:
                self.last_error = str(exc)
                update_campaign_status(self.campaign_id, "recovering", str(exc))
                mark_worker_status(self.campaign_id, "connection_failed")
                logger.exception("SMTP connection failed for campaign %s", self.campaign_id)
                return

            while not self.stop_event.is_set():
                if not self._wait_for_send_window():
                    break
                batch = []
                for _ in range(BATCH_SIZE):
                    try:
                        batch.append(campaign_queue.get_nowait())
                    except queue.Empty:
                        break
                if not batch:
                    break

                logger.info("Processing %s recipients for campaign %s", len(batch), self.campaign_id)
                for index, recipient in enumerate(batch):
                    if self.stop_event.is_set():
                        # Preserve work that was claimed but not started.
                        for pending in batch[index:]:
                            campaign_queue.task_done()
                            campaign_queue.put(pending)
                        break
                    if not self._wait_for_send_window():
                        for pending in batch[index:]:
                            campaign_queue.task_done()
                            campaign_queue.put(pending)
                        break
                    self._send_one(recipient)
                    campaign_queue.task_done()
                    if index < len(batch) - 1 and not self.stop_event.is_set():
                        self.rate_limiter.email_delay(self.stop_event)

                if self.stop_event.is_set():
                    break
                if not campaign_queue.empty():
                    self._heartbeat("batch_pause")
                    self.rate_limiter.batch_pause(self.stop_event)
                    self.rate_limiter.long_break(self.stop_event)

            update_campaign_counts(self.campaign_id)
            if self.stop_event.is_set():
                update_campaign_status(self.campaign_id, "paused")
                logger.info("Worker stopped gracefully for campaign %s", self.campaign_id)
            elif is_campaign_completed(self.campaign_id):
                update_campaign_status(self.campaign_id, "completed")
                logger.info("Campaign %s completed", self.campaign_id)
            else:
                # The manual batching UI can leave durable, unbatched leads.
                update_campaign_status(self.campaign_id, "sending")
        except Exception as exc:
            self.last_error = str(exc)
            update_campaign_status(self.campaign_id, "recovering", str(exc))
            logger.exception("Worker-level failure isolated for campaign %s", self.campaign_id)
        finally:
            try:
                self.mailer.disconnect()
            finally:
                unregister_worker(self.campaign_id, self)
                logger.info("Worker exited for campaign %s", self.campaign_id)
