"""Process-wide Titan SMTP pacing and daily quota enforcement."""

import random
import threading
from datetime import datetime, timedelta

from config import CONFIG


class RateLimiter:
    def __init__(self):
        self.sent_today = 0
        self.batch_counter = 0
        self.connection_counter = 0
        self._day = datetime.now().date()
        self._lock = threading.Lock()

    def _reset_if_new_day(self):
        today = datetime.now().date()
        if today != self._day:
            self._day = today
            self.sent_today = 0
            self.batch_counter = 0

    def business_hours_open(self):
        now = datetime.now()
        return CONFIG.SEND_START_HOUR <= now.hour < CONFIG.SEND_END_HOUR

    def daily_limit_reached(self):
        with self._lock:
            self._reset_if_new_day()
            return self.sent_today >= CONFIG.DAILY_SEND_LIMIT

    def can_send(self):
        return self.business_hours_open() and not self.daily_limit_reached()

    def seconds_until_resume(self):
        now = datetime.now()
        with self._lock:
            self._reset_if_new_day()
            quota_reached = self.sent_today >= CONFIG.DAILY_SEND_LIMIT
        if not quota_reached and now.hour < CONFIG.SEND_START_HOUR:
            target = now.replace(hour=CONFIG.SEND_START_HOUR, minute=0, second=0, microsecond=0)
        else:
            target = (now + timedelta(days=1)).replace(
                hour=CONFIG.SEND_START_HOUR, minute=0, second=0, microsecond=0
            )
        return max(1, int((target - now).total_seconds()))

    def email_delay(self, stop_event=None):
        delay = random.randint(CONFIG.EMAIL_DELAY_MIN, CONFIG.EMAIL_DELAY_MAX)
        if stop_event:
            stop_event.wait(delay)
        else:
            threading.Event().wait(delay)
        return delay

    def batch_pause(self, stop_event=None):
        if stop_event:
            stop_event.wait(CONFIG.BATCH_PAUSE_SECONDS)
        else:
            threading.Event().wait(CONFIG.BATCH_PAUSE_SECONDS)

    def long_break(self, stop_event=None):
        with self._lock:
            due = self.batch_counter > 0 and self.batch_counter % CONFIG.LONG_BREAK_AFTER == 0
        if due:
            if stop_event:
                stop_event.wait(CONFIG.LONG_BREAK_SECONDS)
            else:
                threading.Event().wait(CONFIG.LONG_BREAK_SECONDS)

    def email_sent(self):
        with self._lock:
            self._reset_if_new_day()
            self.sent_today += 1
            self.batch_counter += 1
            self.connection_counter += 1

    def reconnect_required(self):
        with self._lock:
            return self.connection_counter >= CONFIG.RECONNECT_AFTER

    def reset_connection_counter(self):
        with self._lock:
            self.connection_counter = 0

    def reset_day(self):
        with self._lock:
            self.sent_today = 0
            self._day = datetime.now().date()

    def status(self):
        with self._lock:
            self._reset_if_new_day()
            sent = self.sent_today
        return {
            "business_hours": self.business_hours_open(),
            "daily_limit": sent >= CONFIG.DAILY_SEND_LIMIT,
            "sent_today": sent,
            "remaining_today": max(0, CONFIG.DAILY_SEND_LIMIT - sent),
        }


_shared_limiter = RateLimiter()


def get_rate_limiter():
    return _shared_limiter
