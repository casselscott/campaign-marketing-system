"""SQLite persistence for the campaign engine.

All connections receive the same concurrency and safety pragmas.  The module
keeps the original public functions so existing Streamlit pages continue to
work while adding the metadata required for monitoring and recovery.
"""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from config import CONFIG


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_NAME = os.getenv("MCS_DATABASE_PATH", str(PROJECT_ROOT / "data" / "campaigns.db"))


class ManagedConnection(sqlite3.Connection):
    """Close read-only convenience connections when their context exits."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def get_connection():
    db_path = Path(DB_NAME)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(db_path),
        timeout=CONFIG.SQLITE_TIMEOUT,
        check_same_thread=False,
        factory=ManagedConnection,
    )
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout={int(CONFIG.SQLITE_BUSY_TIMEOUT)}")
    if CONFIG.ENABLE_WAL:
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-20000")  # 20 MiB, expressed in KiB
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def transaction(immediate=False):
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _add_column_if_missing(conn, table, definition):
    column = definition.split()[0]
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def initialize_database():
    with transaction() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS campaigns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                subject TEXT,
                status TEXT DEFAULT 'queued',
                total_emails INTEGER DEFAULT 0,
                sent_count INTEGER DEFAULT 0,
                failed_count INTEGER DEFAULT 0,
                pending_count INTEGER DEFAULT 0,
                queued_count INTEGER DEFAULT 0,
                completed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS recipients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id INTEGER,
                contact_name TEXT,
                job_title TEXT,
                company_name TEXT,
                work_email TEXT,
                mobile TEXT,
                industry TEXT,
                sub_industry TEXT,
                status TEXT DEFAULT 'queued',
                retry_count INTEGER DEFAULT 0,
                error_message TEXT,
                smtp_category TEXT,
                sent_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS email_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recipient_id INTEGER,
                campaign_id INTEGER,
                smtp_response TEXT,
                status TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(recipient_id) REFERENCES recipients(id) ON DELETE SET NULL,
                FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS campaign_analytics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id INTEGER,
                sent_count INTEGER DEFAULT 0,
                failed_count INTEGER DEFAULT 0,
                pending_count INTEGER DEFAULT 0,
                queued_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS lead_list (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id INTEGER,
                contact_name TEXT,
                job_title TEXT,
                company_name TEXT,
                work_email TEXT,
                mobile TEXT,
                industry TEXT,
                sub_industry TEXT,
                batched INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE TABLE IF NOT EXISTS smtp_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")

        for definition in (
            "started_at TIMESTAMP",
            "updated_at TIMESTAMP",
            "last_activity_at TIMESTAMP",
            "worker_heartbeat TIMESTAMP",
            "last_error TEXT",
            "recovery_count INTEGER DEFAULT 0",
            "template_name TEXT DEFAULT 'campaign.html'",
        ):
            _add_column_if_missing(conn, "campaigns", definition)
        for definition in ("updated_at TIMESTAMP", "last_attempt_at TIMESTAMP"):
            _add_column_if_missing(conn, "recipients", definition)
        for definition in ("smtp_category TEXT", "duration_ms INTEGER"):
            _add_column_if_missing(conn, "email_logs", definition)

        indexes = (
            "CREATE INDEX IF NOT EXISTS idx_campaigns_status ON campaigns(status)",
            "CREATE INDEX IF NOT EXISTS idx_recipients_campaign ON recipients(campaign_id)",
            "CREATE INDEX IF NOT EXISTS idx_recipients_campaign_status ON recipients(campaign_id, status)",
            "CREATE INDEX IF NOT EXISTS idx_recipients_email ON recipients(work_email)",
            "CREATE INDEX IF NOT EXISTS idx_leads_campaign_batched ON lead_list(campaign_id, batched)",
            "CREATE INDEX IF NOT EXISTS idx_leads_campaign_email ON lead_list(campaign_id, work_email)",
            "CREATE INDEX IF NOT EXISTS idx_logs_campaign_created ON email_logs(campaign_id, created_at)",
        )
        for statement in indexes:
            conn.execute(statement)


def create_campaign(name, subject, total_emails):
    with transaction() as conn:
        cursor = conn.execute(
            "INSERT INTO campaigns (name, subject, status, total_emails, queued_count, updated_at) "
            "VALUES (?, ?, 'queued', ?, ?, CURRENT_TIMESTAMP)",
            (name, subject, total_emails, total_emails),
        )
        return cursor.lastrowid


def update_campaign_status(campaign_id, status, error_message=None):
    terminal = status in {"completed", "failed", "cancelled"}
    with transaction() as conn:
        conn.execute(
            """UPDATE campaigns
               SET status=?, last_error=?, updated_at=CURRENT_TIMESTAMP,
                   last_activity_at=CURRENT_TIMESTAMP,
                   started_at=CASE WHEN ? IN ('sending','recovering')
                                   THEN COALESCE(started_at, CURRENT_TIMESTAMP) ELSE started_at END,
                   completed_at=CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END
               WHERE id=?""",
            (status, error_message, status, terminal, campaign_id),
        )


def update_campaign_heartbeat(campaign_id):
    with transaction() as conn:
        conn.execute(
            "UPDATE campaigns SET worker_heartbeat=CURRENT_TIMESTAMP, "
            "last_activity_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (campaign_id,),
        )


def update_campaign_template(campaign_id, template_name):
    with transaction() as conn:
        conn.execute(
            "UPDATE campaigns SET template_name=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (template_name, campaign_id),
        )


def increment_recovery_count(campaign_id):
    with transaction() as conn:
        conn.execute(
            "UPDATE campaigns SET recovery_count=COALESCE(recovery_count,0)+1, "
            "status='recovering', updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (campaign_id,),
        )


def update_campaign_counts(campaign_id):
    with transaction() as conn:
        counts = conn.execute(
            """SELECT
                   SUM(CASE WHEN status='sent' THEN 1 ELSE 0 END) AS sent,
                   SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed,
                   SUM(CASE WHEN status IN ('pending','retrying') THEN 1 ELSE 0 END) AS pending,
                   SUM(CASE WHEN status='queued' THEN 1 ELSE 0 END) AS queued
               FROM recipients WHERE campaign_id=?""",
            (campaign_id,),
        ).fetchone()
        conn.execute(
            """UPDATE campaigns SET sent_count=?, failed_count=?, pending_count=?, queued_count=?,
                   last_activity_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            tuple((counts[key] or 0) for key in ("sent", "failed", "pending", "queued")) + (campaign_id,),
        )


def recipient_exists(work_email):
    with get_connection() as conn:
        return conn.execute(
            "SELECT status FROM recipients WHERE work_email=? ORDER BY id DESC LIMIT 1",
            (work_email,),
        ).fetchone()


def insert_recipient(campaign_id, data):
    work_email = str(data.get("work_email", "")).strip().lower()
    if not work_email:
        return False
    with transaction(immediate=True) as conn:
        existing = conn.execute(
            "SELECT id FROM recipients WHERE campaign_id=? AND work_email=? LIMIT 1",
            (campaign_id, work_email),
        ).fetchone()
        if existing:
            return False
        conn.execute(
            """INSERT INTO recipients
               (campaign_id, contact_name, job_title, company_name, work_email, mobile,
                industry, sub_industry, status, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', CURRENT_TIMESTAMP)""",
            (campaign_id, data.get("contact_name", ""), data.get("job_title", ""),
             data.get("company_name", ""), work_email, data.get("mobile", ""),
             data.get("industry", ""), data.get("sub_industry", "")),
        )
    return True


def _classify_message(error_message):
    if not error_message:
        return None
    message = str(error_message).lower()
    if "bounce limit" in message or "rate limit" in message:
        return "rate_limit"
    if "mailbox not found" in message or "user unknown" in message:
        return "invalid_email"
    if "domain not found" in message or "no such domain" in message:
        return "invalid_domain"
    if "timeout" in message or "timed out" in message:
        return "temporary_failure"
    return "unknown"


def update_recipient_status(work_email, status, error_message=None, campaign_id=None,
                            smtp_category=None, increment_retry=False, recipient_id=None):
    clauses = []
    params = []
    if recipient_id is not None:
        clauses.append("id=?")
        params.append(recipient_id)
    else:
        clauses.append("work_email=?")
        params.append(str(work_email).strip().lower())
        if campaign_id is not None:
            clauses.append("campaign_id=?")
            params.append(campaign_id)
    category = smtp_category if smtp_category is not None else _classify_message(error_message)
    with transaction() as conn:
        conn.execute(
            f"""UPDATE recipients SET status=?, error_message=?, smtp_category=?,
                    retry_count=retry_count+?, last_attempt_at=CURRENT_TIMESTAMP,
                    updated_at=CURRENT_TIMESTAMP,
                    sent_at=CASE WHEN ?='sent' THEN CURRENT_TIMESTAMP ELSE sent_at END
                WHERE {' AND '.join(clauses)}""",
            (status, error_message, category, int(increment_retry), status, *params),
        )


def record_email_log(recipient_id, campaign_id, status, smtp_response=None,
                     smtp_category=None, duration_ms=None):
    with transaction() as conn:
        conn.execute(
            "INSERT INTO email_logs (recipient_id, campaign_id, smtp_response, status, smtp_category, duration_ms) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (recipient_id, campaign_id, smtp_response, status, smtp_category, duration_ms),
        )


def get_dashboard_metrics():
    with get_connection() as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS total_recipients,
                      SUM(CASE WHEN status='sent' THEN 1 ELSE 0 END) AS sent_emails,
                      SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed_emails,
                      SUM(CASE WHEN status IN ('pending','retrying') THEN 1 ELSE 0 END) AS pending_emails,
                      SUM(CASE WHEN status='queued' THEN 1 ELSE 0 END) AS queued_emails
               FROM recipients"""
        ).fetchone()
        return {key: row[key] or 0 for key in row.keys()}


def is_campaign_completed(campaign_id):
    with get_connection() as conn:
        row = conn.execute(
            """SELECT
                   (SELECT COUNT(*) FROM recipients
                    WHERE campaign_id=? AND status IN ('pending','queued','retrying','processing')) AS recipients_left,
                   (SELECT COUNT(*) FROM lead_list WHERE campaign_id=? AND batched=0) AS leads_left""",
            (campaign_id, campaign_id),
        ).fetchone()
        return row["recipients_left"] == 0 and row["leads_left"] == 0


def get_all_campaigns():
    with get_connection() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM campaigns ORDER BY id DESC").fetchall()]


def get_campaign(campaign_id):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
        return dict(row) if row else None


def get_recipients_for_campaign(campaign_id):
    with get_connection() as conn:
        return [dict(row) for row in conn.execute(
            "SELECT * FROM recipients WHERE campaign_id=? ORDER BY id ASC", (campaign_id,)
        ).fetchall()]


def get_recovery_recipients(campaign_id):
    with get_connection() as conn:
        return [dict(row) for row in conn.execute(
            """SELECT * FROM recipients WHERE campaign_id=?
               AND status IN ('pending','queued','retrying','processing') ORDER BY id ASC""",
            (campaign_id,),
        ).fetchall()]


def get_all_recipients():
    with get_connection() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM recipients ORDER BY id DESC").fetchall()]


def clear_all_recipients():
    with transaction() as conn:
        conn.execute("DELETE FROM email_logs")
        conn.execute("DELETE FROM campaign_analytics")
        conn.execute("DELETE FROM recipients")
        conn.execute("DELETE FROM lead_list")
        conn.execute("DELETE FROM campaigns")


def reset_recipient_status(work_email, campaign_id=None):
    sql = "UPDATE recipients SET status='pending', error_message=NULL, smtp_category=NULL, updated_at=CURRENT_TIMESTAMP WHERE work_email=?"
    params = [str(work_email).strip().lower()]
    if campaign_id is not None:
        sql += " AND campaign_id=?"
        params.append(campaign_id)
    with transaction() as conn:
        conn.execute(sql, params)


def import_lead_list(campaign_id, rows):
    normalized = []
    seen = set()
    for row in rows:
        email = str(row.get("work_email", "")).strip().lower()
        if not email or email in seen:
            continue
        seen.add(email)
        normalized.append((
            campaign_id, str(row.get("contact_name", "")).strip(),
            str(row.get("job_title", "")).strip(), str(row.get("company_name", "")).strip(),
            email, str(row.get("mobile", "")).strip(), str(row.get("industry", "")).strip(),
            str(row.get("sub_industry", "")).strip(), campaign_id, email,
        ))
    with transaction(immediate=True) as conn:
        before = conn.total_changes
        conn.executemany(
            """INSERT INTO lead_list
               (campaign_id, contact_name, job_title, company_name, work_email, mobile,
                industry, sub_industry, batched)
               SELECT ?, ?, ?, ?, ?, ?, ?, ?, 0
               WHERE NOT EXISTS (SELECT 1 FROM lead_list WHERE campaign_id=? AND work_email=?)""",
            normalized,
        )
        inserted = conn.total_changes - before
        total = conn.execute("SELECT COUNT(*) FROM lead_list WHERE campaign_id=?", (campaign_id,)).fetchone()[0]
        conn.execute(
            "UPDATE campaigns SET total_emails=?, queued_count=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (total, total, campaign_id),
        )
        return inserted


def get_next_batch(campaign_id, batch_size=25):
    """Atomically claim leads and create their durable recipient records."""
    with transaction(immediate=True) as conn:
        rows = conn.execute(
            """SELECT id, contact_name, job_title, company_name, work_email, mobile, industry, sub_industry
               FROM lead_list WHERE campaign_id=? AND batched=0 ORDER BY id ASC LIMIT ?""",
            (campaign_id, batch_size),
        ).fetchall()
        if not rows:
            return []
        conn.executemany("UPDATE lead_list SET batched=1 WHERE id=?", [(row["id"],) for row in rows])
        result = []
        for row in rows:
            data = dict(row)
            conn.execute(
                """INSERT INTO recipients
                   (campaign_id, contact_name, job_title, company_name, work_email, mobile,
                    industry, sub_industry, status, updated_at)
                   SELECT ?, ?, ?, ?, ?, ?, ?, ?, 'pending', CURRENT_TIMESTAMP
                   WHERE NOT EXISTS (SELECT 1 FROM recipients WHERE campaign_id=? AND work_email=?)""",
                (campaign_id, data["contact_name"], data["job_title"], data["company_name"],
                 data["work_email"], data["mobile"], data["industry"], data["sub_industry"],
                 campaign_id, data["work_email"]),
            )
            recipient = conn.execute(
                "SELECT * FROM recipients WHERE campaign_id=? AND work_email=? ORDER BY id DESC LIMIT 1",
                (campaign_id, data["work_email"]),
            ).fetchone()
            result.append(dict(recipient))
        conn.execute(
            "UPDATE campaigns SET status='sending', started_at=COALESCE(started_at,CURRENT_TIMESTAMP), "
            "updated_at=CURRENT_TIMESTAMP WHERE id=?", (campaign_id,)
        )
        return result


def get_lead_list_stats(campaign_id):
    with get_connection() as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN batched=1 THEN 1 ELSE 0 END) AS batched
               FROM lead_list WHERE campaign_id=?""", (campaign_id,)
        ).fetchone()
        total, batched = row["total"] or 0, row["batched"] or 0
        return {"total": total, "batched": batched, "remaining": total - batched}


def get_campaigns_with_pending_leads():
    with get_connection() as conn:
        return [dict(row) for row in conn.execute(
            """SELECT c.* FROM campaigns c WHERE EXISTS
               (SELECT 1 FROM lead_list l WHERE l.campaign_id=c.id AND l.batched=0)
               AND c.status NOT IN ('cancelled','completed') ORDER BY c.id DESC"""
        ).fetchall()]


def get_recoverable_campaigns():
    with get_connection() as conn:
        return [dict(row) for row in conn.execute(
            """SELECT * FROM campaigns c WHERE status IN ('sending','recovering') AND EXISTS
               (SELECT 1 FROM recipients r WHERE r.campaign_id=c.id
                AND r.status IN ('pending','queued','retrying','processing')) ORDER BY id"""
        ).fetchall()]


def get_campaign_runtime_metrics(campaign_id):
    with get_connection() as conn:
        row = conn.execute(
            """SELECT c.*,
                   (SELECT COUNT(*) FROM lead_list l WHERE l.campaign_id=c.id AND l.batched=0) AS unbatched,
                   (SELECT COUNT(*) FROM recipients r WHERE r.campaign_id=c.id
                    AND r.status IN ('pending','queued','retrying','processing')) AS in_flight,
                   (SELECT COUNT(*) FROM recipients r WHERE r.campaign_id=c.id AND r.status='sent'
                    AND r.sent_at >= datetime('now','-5 minutes')) AS sent_last_5m
               FROM campaigns c WHERE c.id=?""", (campaign_id,)
        ).fetchone()
        return dict(row) if row else None


def optimize_database():
    conn = get_connection()
    try:
        conn.execute("PRAGMA optimize")
        conn.execute("ANALYZE")
        conn.commit()
    finally:
        conn.close()
