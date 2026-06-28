import os
import smtplib
import tempfile
import unittest
from unittest.mock import patch

from app.core import queue_manager
from app.core.mailer import Mailer, SMTPDeliveryError
from app.core.worker import EmailWorker
from app.database import db


class ImmediateLimiter:
    def can_send(self):
        return True

    def seconds_until_resume(self):
        return 0

    def email_sent(self):
        pass

    def email_delay(self, stop_event=None):
        pass

    def batch_pause(self, stop_event=None):
        pass

    def long_break(self, stop_event=None):
        pass


class SuccessfulMailer:
    def connect(self):
        pass

    def disconnect(self):
        pass

    def send_email(self, recipient, subject, html):
        return {"status": "sent", "attempts": 1}


class MixedMailer(SuccessfulMailer):
    def send_email(self, recipient, subject, html):
        if recipient.startswith("fail"):
            raise SMTPDeliveryError("mailbox not found", category="invalid_email")
        return super().send_email(recipient, subject, html)


class EnterpriseEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_db = db.DB_NAME
        db.DB_NAME = os.path.join(self.temp.name, "campaigns.db")
        db.initialize_database()
        with queue_manager._manager_lock:
            queue_manager._campaign_queues.clear()
            queue_manager._active_workers.clear()
            queue_manager._campaign_stats.clear()

    def tearDown(self):
        db.DB_NAME = self.original_db
        self.temp.cleanup()

    def _campaign(self, emails):
        campaign_id = db.create_campaign("Test", "Subject", 0)
        rows = [{"contact_name": email, "work_email": email} for email in emails]
        db.import_lead_list(campaign_id, rows)
        recipients = db.get_next_batch(campaign_id, 25)
        for recipient in recipients:
            queue_manager.enqueue(campaign_id, recipient)
        return campaign_id, recipients

    def test_sqlite_pragmas_indexes_and_atomic_batch_claim(self):
        campaign_id = db.create_campaign("Import", "Subject", 0)
        inserted = db.import_lead_list(campaign_id, [
            {"contact_name": "A", "work_email": "A@example.com"},
            {"contact_name": "Duplicate", "work_email": "a@example.com"},
            {"contact_name": "B", "work_email": "b@example.com"},
        ])
        self.assertEqual(inserted, 2)
        claimed = db.get_next_batch(campaign_id, 1)
        self.assertEqual(len(claimed), 1)
        self.assertEqual(len(db.get_recipients_for_campaign(campaign_id)), 1)
        self.assertFalse(db.is_campaign_completed(campaign_id))

        conn = db.get_connection()
        try:
            self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
            index_names = {row[1] for row in conn.execute("PRAGMA index_list(recipients)")}
            self.assertIn("idx_recipients_campaign_status", index_names)
        finally:
            conn.close()

    def test_queue_isolation_and_statistics(self):
        queue_manager.enqueue(1, {"id": 1})
        queue_manager.enqueue(2, {"id": 2})
        self.assertEqual(queue_manager.queue_size(1), 1)
        self.assertEqual(queue_manager.queue_size(2), 1)
        self.assertEqual(queue_manager.dequeue(1)["id"], 1)
        self.assertEqual(queue_manager.queue_size(2), 1)

    @patch("app.core.worker.render_template", return_value="<p>Hello</p>")
    def test_worker_completes_campaign_and_updates_heartbeat(self, _render):
        campaign_id, _ = self._campaign(["ok@example.com"])
        worker = EmailWorker(
            campaign_id, "Subject", mailer=SuccessfulMailer(),
            rate_limiter=ImmediateLimiter(), enforce_schedule=False,
        )
        worker.run()
        campaign = db.get_campaign(campaign_id)
        self.assertEqual(campaign["status"], "completed")
        self.assertEqual(campaign["sent_count"], 1)
        self.assertIsNotNone(campaign["worker_heartbeat"])

    @patch("app.core.worker.render_template", return_value="<p>Hello</p>")
    def test_worker_isolates_recipient_failure(self, _render):
        campaign_id, _ = self._campaign(["fail@example.com", "ok@example.com"])
        worker = EmailWorker(
            campaign_id, "Subject", mailer=MixedMailer(),
            rate_limiter=ImmediateLimiter(), enforce_schedule=False,
        )
        worker.run()
        campaign = db.get_campaign(campaign_id)
        self.assertEqual(campaign["status"], "completed")
        self.assertEqual(campaign["sent_count"], 1)
        self.assertEqual(campaign["failed_count"], 1)

    def test_recovery_rebuilds_queue_from_sqlite(self):
        campaign_id, recipients = self._campaign(["recover@example.com"])
        queue_manager.clear_campaign_queue(campaign_id)
        with patch("app.core.campaign_monitor.launch_campaign_worker", return_value=True):
            from app.core.campaign_monitor import recover_campaign
            self.assertTrue(recover_campaign(campaign_id))
        self.assertEqual(queue_manager.queue_size(campaign_id), len(recipients))
        self.assertEqual(db.get_campaign(campaign_id)["recovery_count"], 1)


class MailerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_db = db.DB_NAME
        db.DB_NAME = os.path.join(self.temp.name, "campaigns.db")
        db.initialize_database()

    def tearDown(self):
        db.DB_NAME = self.original_db
        self.temp.cleanup()

    def test_temporary_failure_reconnects_and_retries(self):
        state = {"attempts": 0, "connections": 0}

        class FakeSMTP:
            def login(self, username, password):
                pass

            def noop(self):
                return 250, b"OK"

            def sendmail(self, sender, recipient, message):
                state["attempts"] += 1
                if state["attempts"] == 1:
                    raise smtplib.SMTPServerDisconnected("temporary connection closed")

            def quit(self):
                pass

            def close(self):
                pass

        def factory(_cfg, _context):
            state["connections"] += 1
            return FakeSMTP()

        environment = {
            "SMTP_SERVER": "smtp.test",
            "SMTP_PORT": "465",
            "SMTP_USERNAME": "sender@test",
            "SMTP_PASSWORD": "secret",
            "SENDER_NAME": "Sender",
            "USE_SSL": "true",
        }
        with patch.dict(os.environ, environment, clear=False):
            mailer = Mailer(smtp_factory=factory, sleep_func=lambda _seconds: None)
            result = mailer.send_email("person@example.com", "Subject", "<p>Hi</p>")
            self.assertEqual(result["attempts"], 2)
            self.assertEqual(mailer.stats["retries"], 1)
            self.assertEqual(state["connections"], 2)
            self.assertTrue(mailer.validate_connection(force=True))


if __name__ == "__main__":
    unittest.main()
