import sqlite3
from datetime import datetime

DB_NAME = "data/campaigns.db"

def get_connection():
    import os
    os.makedirs("data", exist_ok=True)
    return sqlite3.connect(DB_NAME, check_same_thread=False)

def initialize_database():
    conn = get_connection()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS campaigns (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, subject TEXT, status TEXT DEFAULT 'queued', total_emails INTEGER DEFAULT 0, sent_count INTEGER DEFAULT 0, failed_count INTEGER DEFAULT 0, pending_count INTEGER DEFAULT 0, queued_count INTEGER DEFAULT 0, completed_at TIMESTAMP, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS recipients (id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id INTEGER, contact_name TEXT, job_title TEXT, company_name TEXT, work_email TEXT, mobile TEXT, industry TEXT, sub_industry TEXT, status TEXT DEFAULT 'queued', retry_count INTEGER DEFAULT 0, error_message TEXT, smtp_category TEXT, sent_at TIMESTAMP, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS email_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, recipient_id INTEGER, campaign_id INTEGER, smtp_response TEXT, status TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS campaign_analytics (id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id INTEGER, sent_count INTEGER DEFAULT 0, failed_count INTEGER DEFAULT 0, pending_count INTEGER DEFAULT 0, queued_count INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS lead_list (id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id INTEGER, contact_name TEXT, job_title TEXT, company_name TEXT, work_email TEXT, mobile TEXT, industry TEXT, sub_industry TEXT, batched INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS smtp_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)""")
    conn.commit()
    conn.close()

def create_campaign(name, subject, total_emails):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO campaigns (name, subject, status, total_emails, queued_count) VALUES (?,?,?,?,?)", (name, subject, "sending", total_emails, total_emails))
    campaign_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return campaign_id

def update_campaign_status(campaign_id, status):
    conn = get_connection()
    conn.execute("UPDATE campaigns SET status=?, completed_at=CURRENT_TIMESTAMP WHERE id=?", (status, campaign_id))
    conn.commit()
    conn.close()

def update_campaign_counts(campaign_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM recipients WHERE campaign_id=? AND status='sent'", (campaign_id,))
    sent = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM recipients WHERE campaign_id=? AND status='failed'", (campaign_id,))
    failed = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM recipients WHERE campaign_id=? AND status='pending'", (campaign_id,))
    pending = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM recipients WHERE campaign_id=? AND status='queued'", (campaign_id,))
    queued = cursor.fetchone()[0]
    cursor.execute("UPDATE campaigns SET sent_count=?, failed_count=?, pending_count=?, queued_count=? WHERE id=?", (sent, failed, pending, queued, campaign_id))
    conn.commit()
    conn.close()

def recipient_exists(work_email):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM recipients WHERE work_email=? ORDER BY id DESC LIMIT 1", (work_email,))
    result = cursor.fetchone()
    conn.close()
    return result

def insert_recipient(campaign_id, data):
    conn = get_connection()
    cursor = conn.cursor()
    work_email = data.get("work_email", "").strip()
    cursor.execute("INSERT INTO recipients (campaign_id, contact_name, job_title, company_name, work_email, mobile, industry, sub_industry, status) VALUES (?,?,?,?,?,?,?,?,?)", (campaign_id, data.get("contact_name",""), data.get("job_title",""), data.get("company_name",""), work_email, data.get("mobile",""), data.get("industry",""), data.get("sub_industry",""), "pending"))
    conn.commit()
    conn.close()
    return True

def update_recipient_status(work_email, status, error_message=None):
    conn = get_connection()
    smtp_category = None
    if error_message:
        e = error_message.lower()
        if "bounce limit exceeded" in e: smtp_category = "rate_limited"
        elif "mailbox not found" in e: smtp_category = "invalid_mailbox"
        elif "domain not found" in e: smtp_category = "invalid_domain"
        elif "timeout" in e: smtp_category = "timeout"
        else: smtp_category = "unknown"
    conn.execute("UPDATE recipients SET status=?, error_message=?, smtp_category=?, sent_at=CURRENT_TIMESTAMP WHERE work_email=?", (status, error_message, smtp_category, work_email))
    conn.commit()
    conn.close()

def get_dashboard_metrics():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM recipients")
    total = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM recipients WHERE status='sent'")
    sent = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM recipients WHERE status='failed'")
    failed = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM recipients WHERE status='pending'")
    pending = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM recipients WHERE status='queued'")
    queued = cursor.fetchone()[0]
    conn.close()
    return {"total_recipients": total, "sent_emails": sent, "failed_emails": failed, "pending_emails": pending, "queued_emails": queued}

def is_campaign_completed(campaign_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM recipients WHERE campaign_id=? AND status IN ('pending','queued')", (campaign_id,))
    remaining = cursor.fetchone()[0]
    conn.close()
    return remaining == 0

def get_all_campaigns():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM campaigns ORDER BY id DESC")
    columns = [d[0] for d in cursor.description]
    rows = cursor.fetchall()
    conn.close()
    return [dict(zip(columns, r)) for r in rows]

def get_recipients_for_campaign(campaign_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM recipients WHERE campaign_id=? ORDER BY id ASC", (campaign_id,))
    columns = [d[0] for d in cursor.description]
    rows = cursor.fetchall()
    conn.close()
    return [dict(zip(columns, r)) for r in rows]

def get_all_recipients():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM recipients ORDER BY id DESC")
    columns = [d[0] for d in cursor.description]
    rows = cursor.fetchall()
    conn.close()
    return [dict(zip(columns, r)) for r in rows]

def clear_all_recipients():
    conn = get_connection()
    conn.execute("DELETE FROM recipients")
    conn.execute("DELETE FROM campaigns")
    conn.execute("DELETE FROM email_logs")
    conn.execute("DELETE FROM lead_list")
    conn.commit()
    conn.close()

def reset_recipient_status(work_email):
    conn = get_connection()
    conn.execute("UPDATE recipients SET status='pending', error_message=NULL WHERE work_email=?", (work_email,))
    conn.commit()
    conn.close()

def import_lead_list(campaign_id, rows):
    conn = get_connection()
    cursor = conn.cursor()
    inserted = 0
    for row in rows:
        work_email = str(row.get("work_email", "")).strip().lower()
        if not work_email:
            continue
        cursor.execute("SELECT id FROM lead_list WHERE campaign_id=? AND work_email=? LIMIT 1", (campaign_id, work_email))
        if cursor.fetchone():
            continue
        cursor.execute("INSERT INTO lead_list (campaign_id, contact_name, job_title, company_name, work_email, mobile, industry, sub_industry, batched) VALUES (?,?,?,?,?,?,?,?,0)", (campaign_id, str(row.get("contact_name","")).strip(), str(row.get("job_title","")).strip(), str(row.get("company_name","")).strip(), work_email, str(row.get("mobile","")).strip(), str(row.get("industry","")).strip(), str(row.get("sub_industry","")).strip()))
        inserted += 1
    cursor.execute("SELECT COUNT(*) FROM lead_list WHERE campaign_id=?", (campaign_id,))
    total = cursor.fetchone()[0]
    cursor.execute("UPDATE campaigns SET total_emails=? WHERE id=?", (total, campaign_id))
    conn.commit()
    conn.close()
    return inserted

def get_next_batch(campaign_id, batch_size=25):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, contact_name, job_title, company_name, work_email, mobile, industry, sub_industry FROM lead_list WHERE campaign_id=? AND batched=0 ORDER BY id ASC LIMIT ?", (campaign_id, batch_size))
    columns = [d[0] for d in cursor.description]
    rows = cursor.fetchall()
    if not rows:
        conn.close()
        return []
    ids = [r[0] for r in rows]
    placeholders = ",".join("?" * len(ids))
    cursor.execute(f"UPDATE lead_list SET batched=1 WHERE id IN ({placeholders})", ids)
    conn.commit()
    conn.close()
    return [dict(zip(columns[1:], r[1:])) for r in rows]

def get_lead_list_stats(campaign_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM lead_list WHERE campaign_id=?", (campaign_id,))
    total = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM lead_list WHERE campaign_id=? AND batched=1", (campaign_id,))
    batched = cursor.fetchone()[0]
    conn.close()
    return {"total": total, "batched": batched, "remaining": total - batched}

def get_campaigns_with_pending_leads():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT c.* FROM campaigns c JOIN lead_list l ON l.campaign_id=c.id WHERE l.batched=0 ORDER BY c.id DESC")
    columns = [d[0] for d in cursor.description]
    rows = cursor.fetchall()
    conn.close()
    return [dict(zip(columns, r)) for r in rows]
