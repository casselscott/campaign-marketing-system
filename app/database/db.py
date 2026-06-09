import os
import psycopg2
import psycopg2.extras
from datetime import datetime




def _is_postgres(conn):
    return 'psycopg2' in type(conn).__module__

def _cursor(conn):
    if _is_postgres(conn):
        return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    else:
        import sqlite3
        conn.row_factory = sqlite3.Row
        return conn.cursor()

def get_connection():
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        try:
            import streamlit as st
            database_url = st.secrets["DATABASE_URL"]
        except Exception:
            pass

    if database_url:
        try:
            conn = psycopg2.connect(database_url, connect_timeout=5)
            return conn
        except Exception as e:
            print(f"Supabase connection failed: {e}. Falling back to SQLite.")

    # SQLite fallback for local dev
    import sqlite3, os as _os
    _os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect("data/campaigns.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def initialize_database():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""CREATE TABLE IF NOT EXISTS campaigns (id SERIAL PRIMARY KEY, name TEXT, subject TEXT, status TEXT DEFAULT 'queued', total_emails INTEGER DEFAULT 0, sent_count INTEGER DEFAULT 0, failed_count INTEGER DEFAULT 0, pending_count INTEGER DEFAULT 0, queued_count INTEGER DEFAULT 0, completed_at TIMESTAMP, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS recipients (id SERIAL PRIMARY KEY, campaign_id INTEGER, contact_name TEXT, job_title TEXT, company_name TEXT, work_email TEXT, mobile TEXT, industry TEXT, sub_industry TEXT, status TEXT DEFAULT 'queued', retry_count INTEGER DEFAULT 0, error_message TEXT, smtp_category TEXT, sent_at TIMESTAMP, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS email_logs (id SERIAL PRIMARY KEY, recipient_id INTEGER, campaign_id INTEGER, smtp_response TEXT, status TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS campaign_analytics (id SERIAL PRIMARY KEY, campaign_id INTEGER, sent_count INTEGER DEFAULT 0, failed_count INTEGER DEFAULT 0, pending_count INTEGER DEFAULT 0, queued_count INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS lead_list (id SERIAL PRIMARY KEY, campaign_id INTEGER, contact_name TEXT, job_title TEXT, company_name TEXT, work_email TEXT, mobile TEXT, industry TEXT, sub_industry TEXT, batched INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS smtp_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)""")
    conn.commit()
    cursor.close()
    conn.close()


def create_campaign(name, subject, total_emails):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO campaigns (name, subject, status, total_emails, queued_count) VALUES (%s,%s,%s,%s,%s) RETURNING id", (name, subject, "sending", total_emails, total_emails))
    campaign_id = cursor.fetchone()[0]
    conn.commit()
    cursor.close()
    conn.close()
    return campaign_id


def update_campaign_status(campaign_id, status):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE campaigns SET status=%s, completed_at=CURRENT_TIMESTAMP WHERE id=%s", (status, campaign_id))
    conn.commit()
    cursor.close()
    conn.close()


def update_campaign_counts(campaign_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM recipients WHERE campaign_id=%s AND status='sent'", (campaign_id,))
    sent = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM recipients WHERE campaign_id=%s AND status='failed'", (campaign_id,))
    failed = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM recipients WHERE campaign_id=%s AND status='pending'", (campaign_id,))
    pending = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM recipients WHERE campaign_id=%s AND status='queued'", (campaign_id,))
    queued = cursor.fetchone()[0]
    cursor.execute("UPDATE campaigns SET sent_count=%s, failed_count=%s, pending_count=%s, queued_count=%s WHERE id=%s", (sent, failed, pending, queued, campaign_id))
    conn.commit()
    cursor.close()
    conn.close()


def get_all_campaigns():
    conn = get_connection()
    cursor = _cursor(conn)
    cursor.execute("SELECT * FROM campaigns ORDER BY id DESC")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [dict(r) for r in rows]


def get_recipients_for_campaign(campaign_id):
    conn = get_connection()
    cursor = _cursor(conn)
    cursor.execute("SELECT * FROM recipients WHERE campaign_id=%s ORDER BY id ASC", (campaign_id,))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [dict(r) for r in rows]


def get_all_recipients():
    conn = get_connection()
    cursor = _cursor(conn)
    cursor.execute("SELECT * FROM recipients ORDER BY id DESC")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [dict(r) for r in rows]


def recipient_exists(work_email):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM recipients WHERE work_email=%s ORDER BY id DESC LIMIT 1", (work_email,))
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    return result


def insert_recipient(campaign_id, data):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO recipients (campaign_id, contact_name, job_title, company_name, work_email, mobile, industry, sub_industry, status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", (campaign_id, data.get("contact_name",""), data.get("job_title",""), data.get("company_name",""), data.get("work_email","").strip(), data.get("mobile",""), data.get("industry",""), data.get("sub_industry",""), "pending"))
    conn.commit()
    cursor.close()
    conn.close()
    return True


def update_recipient_status(work_email, status, error_message=None):
    conn = get_connection()
    cursor = conn.cursor()
    smtp_category = None
    if error_message:
        e = error_message.lower()
        if "bounce limit exceeded" in e: smtp_category = "rate_limited"
        elif "mailbox not found" in e: smtp_category = "invalid_mailbox"
        elif "domain not found" in e: smtp_category = "invalid_domain"
        elif "timeout" in e: smtp_category = "timeout"
        else: smtp_category = "unknown"
    cursor.execute("UPDATE recipients SET status=%s, error_message=%s, smtp_category=%s, sent_at=CURRENT_TIMESTAMP WHERE work_email=%s", (status, error_message, smtp_category, work_email))
    conn.commit()
    cursor.close()
    conn.close()


def get_dashboard_metrics():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM recipients"); total = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM recipients WHERE status='sent'"); sent = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM recipients WHERE status='failed'"); failed = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM recipients WHERE status='pending'"); pending = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM recipients WHERE status='queued'"); queued = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return {"total_recipients": total, "sent_emails": sent, "failed_emails": failed, "pending_emails": pending, "queued_emails": queued}


def is_campaign_completed(campaign_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM recipients WHERE campaign_id=%s AND status IN ('pending','queued')", (campaign_id,))
    remaining = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return remaining == 0


def clear_all_recipients():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM recipients")
    cursor.execute("DELETE FROM campaigns")
    cursor.execute("DELETE FROM email_logs")
    cursor.execute("DELETE FROM lead_list")
    conn.commit()
    cursor.close()
    conn.close()


def reset_recipient_status(work_email):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE recipients SET status='pending', error_message=NULL WHERE work_email=%s", (work_email,))
    conn.commit()
    cursor.close()
    conn.close()


def import_lead_list(campaign_id, rows):
    conn = get_connection()
    cursor = conn.cursor()
    inserted = 0
    for row in rows:
        work_email = str(row.get("work_email", "")).strip().lower()
        if not work_email:
            continue
        cursor.execute("SELECT id FROM lead_list WHERE campaign_id=%s AND work_email=%s LIMIT 1", (campaign_id, work_email))
        if cursor.fetchone():
            continue
        cursor.execute("INSERT INTO lead_list (campaign_id, contact_name, job_title, company_name, work_email, mobile, industry, sub_industry, batched) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,0)", (campaign_id, str(row.get("contact_name","")).strip(), str(row.get("job_title","")).strip(), str(row.get("company_name","")).strip(), work_email, str(row.get("mobile","")).strip(), str(row.get("industry","")).strip(), str(row.get("sub_industry","")).strip()))
        inserted += 1
    cursor.execute("SELECT COUNT(*) FROM lead_list WHERE campaign_id=%s", (campaign_id,))
    total = cursor.fetchone()[0]
    cursor.execute("UPDATE campaigns SET total_emails=%s WHERE id=%s", (total, campaign_id))
    conn.commit()
    cursor.close()
    conn.close()
    return inserted


def get_next_batch(campaign_id, batch_size=25):
    conn = get_connection()
    cursor = _cursor(conn)
    cursor.execute("SELECT id, contact_name, job_title, company_name, work_email, mobile, industry, sub_industry FROM lead_list WHERE campaign_id=%s AND batched=0 ORDER BY id ASC LIMIT %s", (campaign_id, batch_size))
    rows = cursor.fetchall()
    if not rows:
        cursor.close()
        conn.close()
        return []
    ids = [r["id"] for r in rows]
    cursor.execute("UPDATE lead_list SET batched=1 WHERE id = ANY(%s)", (ids,))
    conn.commit()
    cursor.close()
    conn.close()
    return [{k: v for k, v in dict(r).items() if k != "id"} for r in rows]


def get_lead_list_stats(campaign_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM lead_list WHERE campaign_id=%s", (campaign_id,))
    total = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM lead_list WHERE campaign_id=%s AND batched=1", (campaign_id,))
    batched = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return {"total": total, "batched": batched, "remaining": total - batched}


def get_campaigns_with_pending_leads():
    conn = get_connection()
    cursor = _cursor(conn)
    cursor.execute("SELECT DISTINCT c.* FROM campaigns c JOIN lead_list l ON l.campaign_id=c.id WHERE l.batched=0 ORDER BY c.id DESC")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [dict(r) for r in rows]


def get_all_settings():
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT key, value FROM smtp_settings")
        rows = cursor.fetchall()
        return {r[0]: r[1] for r in rows}
    except Exception:
        return {}
    finally:
        cursor.close()
        conn.close()


def save_setting(key, value):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO smtp_settings (key, value) VALUES (%s,%s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value", (key, value))
    conn.commit()
    cursor.close()
    conn.close()