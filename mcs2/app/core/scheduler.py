"""
==========================================================
Campaign Scheduler
Marketing Campaign System v2.5 Enterprise
==========================================================

Responsible for

✓ Daily quota

✓ Business hours

✓ Batch scheduling

✓ Campaign pause

✓ Resume tomorrow

✓ ETA

✓ Campaign health

"""

from datetime import datetime, timedelta

from config import CONFIG


class CampaignScheduler:

    def __init__(self):

        self.today = datetime.now().date()

        self.sent_today = 0

        self.started = datetime.now()

    # ----------------------------------------------------
    # DAILY RESET
    # ----------------------------------------------------

    def check_new_day(self):

        if datetime.now().date() != self.today:

            self.today = datetime.now().date()

            self.sent_today = 0

    # ----------------------------------------------------
    # BUSINESS HOURS
    # ----------------------------------------------------

    def business_hours_open(self):

        self.check_new_day()

        hour = datetime.now().hour

        return (

            CONFIG.SEND_START_HOUR

            <= hour

            <

            CONFIG.SEND_END_HOUR

        )

    # ----------------------------------------------------
    # DAILY LIMIT
    # ----------------------------------------------------

    def daily_limit_reached(self):

        self.check_new_day()

        return (

            self.sent_today

            >=

            CONFIG.DAILY_SEND_LIMIT

        )

    # ----------------------------------------------------
    # EMAIL SENT
    # ----------------------------------------------------

    def email_sent(self):

        self.sent_today += 1

    # ----------------------------------------------------
    # SHOULD SEND?
    # ----------------------------------------------------

    def can_send(self):

        if not self.business_hours_open():

            return False

        if self.daily_limit_reached():

            return False

        return True

    # ----------------------------------------------------
    # NEXT RESUME
    # ----------------------------------------------------

    def next_resume_time(self):

        now = datetime.now()
        if not self.daily_limit_reached() and now.hour < CONFIG.SEND_START_HOUR:
            target_day = now
        else:
            target_day = now + timedelta(days=1)
        return datetime(
            target_day.year, target_day.month, target_day.day,
            CONFIG.SEND_START_HOUR, 0, 0
        )

    # ----------------------------------------------------
    # WAIT UNTIL RESUME
    # ----------------------------------------------------

    def seconds_until_resume(self):

        resume = self.next_resume_time()

        return max(

            0,

            int(

                (resume - datetime.now())

                .total_seconds()

            )

        )

    # ----------------------------------------------------
    # CAMPAIGN STATUS
    # ----------------------------------------------------

    def status(self):

        return {

            "business_hours":

                self.business_hours_open(),

            "daily_limit":

                self.daily_limit_reached(),

            "sent_today":

                self.sent_today,

            "remaining_today":

                max(

                    0,

                    CONFIG.DAILY_SEND_LIMIT

                    - self.sent_today

                ),

            "next_resume":

                self.next_resume_time()

        }

    # ----------------------------------------------------
    # ETA
    # ----------------------------------------------------

    def estimate_finish(

        self,

        remaining,

        avg_seconds_per_email

    ):

        seconds = (

            remaining

            *

            avg_seconds_per_email

        )

        return datetime.now() + timedelta(

            seconds=seconds

        )
