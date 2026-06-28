"""
==========================================================
Marketing Campaign System v4.0 Enterprise Configuration
==========================================================

Central configuration for the entire Marketing Campaign
System.

All application behaviour is controlled from this file,
including campaign pacing, SMTP reliability, recovery,
health monitoring, logging, dashboard refresh, and
automatic self-healing.

Author: Soft Tech Group
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CampaignConfig:

    # =====================================================
    # CAMPAIGN LIMITS
    # =====================================================

    # Titan Professional SMTP
    DAILY_SEND_LIMIT = 450

    # Emails processed per batch
    BATCH_SIZE = 10

    # =====================================================
    # EMAIL PACING
    # =====================================================

    # Random delay between every email (seconds)
    EMAIL_DELAY_MIN = 20
    EMAIL_DELAY_MAX = 40

    # Pause after each batch
    BATCH_PAUSE_SECONDS = 180

    # Long cooling-off break
    LONG_BREAK_AFTER = 100
    LONG_BREAK_SECONDS = 900

    # =====================================================
    # SENDING SCHEDULE
    # =====================================================

    # False = Campaigns run 24 hours/day
    ENABLE_BUSINESS_HOURS = False

    # Only used if ENABLE_BUSINESS_HOURS=True
    SEND_START_HOUR = 0
    SEND_END_HOUR = 24

    # =====================================================
    # RETRIES
    # =====================================================

    MAX_RETRIES = 3

    RETRY_WAIT_MINUTES = [
        10,
        30,
        120,
    ]

    # Random retry jitter (seconds)
    RETRY_JITTER_MIN = 15
    RETRY_JITTER_MAX = 90

    # =====================================================
    # SMTP
    # =====================================================

    SMTP_TIMEOUT = 30

    KEEP_CONNECTION_OPEN = True

    # Refresh SMTP session after X emails
    RECONNECT_AFTER = 100

    # Verify SMTP connection every X emails
    SMTP_HEALTH_CHECK_INTERVAL = 25

    # NOOP timeout
    SMTP_NOOP_TIMEOUT = 10

    # Enable automatic reconnect
    AUTO_RECONNECT = True

    # Maximum reconnect attempts
    MAX_RECONNECT_ATTEMPTS = 5

    # Seconds between reconnect attempts
    RECONNECT_DELAY = 15

    # =====================================================
    # CIRCUIT BREAKER
    # =====================================================

    ENABLE_CIRCUIT_BREAKER = True

    # Pause SMTP after consecutive failures
    CIRCUIT_BREAKER_THRESHOLD = 5

    # Wait before reconnecting
    CIRCUIT_BREAKER_RESET_SECONDS = 600

    # =====================================================
    # WORKER
    # =====================================================

    # Background worker heartbeat
    HEARTBEAT_INTERVAL = 30

    # Worker health check
    WATCHDOG_INTERVAL = 60

    # Detect stalled worker
    STALLED_WORKER_TIMEOUT = 300

    # =====================================================
    # CAMPAIGN RECOVERY
    # =====================================================

    AUTO_RESUME = True

    AUTO_COMPLETE = True

    # Recover recipients left in "sending"
    RECOVER_STUCK_RECIPIENTS = True

    STUCK_RECIPIENT_TIMEOUT = 600

    # =====================================================
    # SQLITE
    # =====================================================

    SQLITE_TIMEOUT = 30

    SQLITE_BUSY_TIMEOUT = 30000

    ENABLE_WAL = True

    AUTO_VACUUM = True

    # =====================================================
    # DASHBOARD
    # =====================================================

    DASHBOARD_REFRESH_MS = 5000

    SHOW_SMTP_HEALTH = True

    SHOW_CAMPAIGN_HEALTH = True

    SHOW_PROGRESS_BAR = True

    SHOW_ETA = True

    SHOW_THROUGHPUT = True

    # =====================================================
    # CAMPAIGN ANALYTICS
    # =====================================================

    ENABLE_CAMPAIGN_TIMELINE = True

    ENABLE_SUMMARY_REPORT = True

    ENABLE_DELIVERY_STATISTICS = True

    ENABLE_FAILURE_ANALYTICS = True

    # =====================================================
    # PERFORMANCE
    # =====================================================

    ENABLE_MEMORY_MONITOR = True

    MEMORY_WARNING_MB = 1024

    ENABLE_CPU_MONITOR = True

    CPU_WARNING_PERCENT = 85

    # =====================================================
    # QUEUE
    # =====================================================

    ENABLE_PERSISTENT_QUEUE = True

    SAVE_QUEUE_AFTER_EACH_EMAIL = True

    SAVE_PROGRESS_AFTER_BATCH = True

    # =====================================================
    # SHUTDOWN
    # =====================================================

    GRACEFUL_SHUTDOWN = True

    COMPLETE_CURRENT_EMAIL = True

    CLOSE_SMTP_ON_EXIT = True

    SAVE_QUEUE_ON_EXIT = True

    # =====================================================
    # LOGGING
    # =====================================================

    LOG_SMTP = True

    LOG_DATABASE = False

    LOG_QUEUE = True

    LOG_WORKER = True

    LOG_HEARTBEAT = True

    LOG_WATCHDOG = True

    LOG_RECONNECT = True

    LOG_RETRY = True

    LOG_PERFORMANCE = False

    # =====================================================
    # DEBUG
    # =====================================================

    DEBUG_MODE = False

    VERBOSE_LOGGING = False


# ==========================================================
# Global Configuration
# ==========================================================

CONFIG = CampaignConfig()

# =====================================================
# DATABASE COMMITS
# =====================================================

# Commit recipient status immediately after every email.
COMMIT_AFTER_EACH_EMAIL = True

# =====================================================
# HEALTH
# =====================================================

# Automatically reconnect after this many minutes,
# even if the SMTP session appears healthy.
MAX_CONNECTION_AGE_MINUTES = 30

# =====================================================
# LOG RETENTION
# =====================================================

LOG_RETENTION_DAYS = 30

# =====================================================
# STATISTICS
# =====================================================

ENABLE_SMTP_STATISTICS = True

ENABLE_DELIVERY_TIMINGS = True

# =====================================================
# PERFORMANCE
# =====================================================

TRACK_LATENCY = True

# =====================================================
# APPLICATION
# =====================================================

APP_NAME = "Marketing Campaign System"

APP_VERSION = "4.0.0"

ENGINE = "Enterprise Campaign Engine"

SMTP_PROVIDER = "Titan"

ENVIRONMENT = "production"