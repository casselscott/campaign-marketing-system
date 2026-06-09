"""
worker.py

EmailWorker thread – replaces the Celery send_email_task.

Preserves:
  - BATCH_SIZE = 25  (Titan SMTP safety limit)
  - EMAIL_DELAY_MIN / MAX between individual emails
  - BATCH_DELAY (120 s) between batches
  - Titan bounce-limit detection
  - SMTP failure classification
  - Per-recipient connect/disconnect kept inside the batch loop
    so a single bad recipient can't kill the whole run
"""
import random
import time

from threading import Thread

from app.core.queue_manager import get_queue, increment_processed, increment_failed
from app.core.mailer import Mailer
from app.core.template_engine import render_template

from app.database.db import (
    update_recipient_status,
    update_campaign_counts,
    update_campaign_status,
    is_campaign_completed
)

from app.utils.logger import logger


# -----------------------------------
# TITAN SAFE LIMITS
# -----------------------------------

BATCH_SIZE = 25

EMAIL_DELAY_MIN = 8
EMAIL_DELAY_MAX = 15

BATCH_DELAY = 120          # seconds between batches


class EmailWorker(Thread):

    def __init__(
        self,
        campaign_id,
        subject
    ):

        super().__init__()

        self.campaign_id = campaign_id
        self.subject = subject
        self.daemon = True

    def run(self):

        q = get_queue()

        mailer = Mailer()

        # -----------------------------------
        # CONNECT SMTP
        # -----------------------------------

        try:

            mailer.connect()

            logger.info(
                "SMTP Connected Successfully"
            )

        except Exception as e:

            logger.error(
                f"SMTP Connection Failed: "
                f"{str(e)}"
            )

            return

        # -----------------------------------
        # PROCESS QUEUE IN BATCHES
        # -----------------------------------

        while not q.empty():

            batch = []

            # Build batch (up to BATCH_SIZE)
            for _ in range(BATCH_SIZE):

                if q.empty():
                    break

                batch.append(q.get())

            logger.info(
                f"Processing Batch of "
                f"{len(batch)} Emails "
                f"For Campaign {self.campaign_id}"
            )

            # -----------------------------------
            # SEND EACH EMAIL IN BATCH
            # -----------------------------------

            for recipient in batch:

                try:

                    logger.info(
                        f"Starting Task For: "
                        f"{recipient['work_email']}"
                    )

                    # Render Dynamic HTML Template
                    html_content = render_template(
                        "campaign.html",
                        recipient
                    )

                    logger.info(
                        f"Template Rendered For "
                        f"{recipient['work_email']}"
                    )

                    # Send Email
                    mailer.send_email(
                        recipient["work_email"],
                        self.subject,
                        html_content
                    )

                    logger.info(
                        f"Email Sent To: "
                        f"{recipient['work_email']}"
                    )

                    # Update Recipient Status
                    update_recipient_status(
                        recipient["work_email"],
                        "sent"
                    )

                    logger.info(
                        f"Recipient Status Updated: "
                        f"{recipient['work_email']} -> sent"
                    )

                    # Update Campaign Counts
                    update_campaign_counts(self.campaign_id)

                    logger.info(
                        f"Campaign Counts Updated "
                        f"For Campaign {self.campaign_id}"
                    )

                    increment_processed()

                    # -----------------------------------
                    # TITAN SAFE HUMAN DELAY
                    # -----------------------------------

                    delay = random.randint(
                        EMAIL_DELAY_MIN,
                        EMAIL_DELAY_MAX
                    )

                    logger.info(
                        f"Sleeping For {delay} Seconds "
                        f"Before Next Email"
                    )

                    time.sleep(delay)

                except Exception as e:

                    error_message = str(e)

                    # -----------------------------------
                    # TITAN SMTP PROTECTION DETECTION
                    # -----------------------------------

                    if (
                        "bounce limit exceeded"
                        in error_message.lower()
                    ):

                        logger.warning(
                            "Titan Bounce Protection Triggered – "
                            "pausing 60 seconds"
                        )

                        time.sleep(60)

                    # Update Failed Recipient
                    update_recipient_status(
                        recipient["work_email"],
                        "failed",
                        error_message
                    )

                    # Update Campaign Counts
                    update_campaign_counts(self.campaign_id)

                    increment_failed()

                    logger.error(
                        f"Failed Sending To "
                        f"{recipient['work_email']} : "
                        f"{error_message}"
                    )

                finally:

                    # Mark task done in queue
                    try:
                        q.task_done()
                    except Exception:
                        pass

            logger.info("Batch Completed")

            # -----------------------------------
            # CHECK CAMPAIGN COMPLETION
            # -----------------------------------

            if is_campaign_completed(self.campaign_id):

                update_campaign_status(
                    self.campaign_id,
                    "completed"
                )

                logger.info(
                    f"Campaign {self.campaign_id} "
                    f"Completed Successfully"
                )

                break

            else:

                logger.info(
                    f"Campaign {self.campaign_id} "
                    f"Still Processing – "
                    f"Waiting {BATCH_DELAY}s Before Next Batch"
                )

                # Delay Between Batches (Titan protection)
                time.sleep(BATCH_DELAY)

        # -----------------------------------
        # DISCONNECT SMTP
        # -----------------------------------

        try:

            mailer.disconnect()

            logger.info(
                "SMTP Connection Closed"
            )

        except Exception as disconnect_error:

            logger.error(
                f"SMTP Disconnect Error: "
                f"{str(disconnect_error)}"
            )
