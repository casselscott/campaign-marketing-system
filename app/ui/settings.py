import streamlit as st

from app.database.db import get_connection
from app.core.queue_manager import worker_status


# -----------------------------------
# SMTP SETTINGS TABLE BOOTSTRAP
# -----------------------------------

def _ensure_settings_table():

    conn = get_connection()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS smtp_settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )

    conn.commit()
    conn.close()


def _get_all_smtp():

    _ensure_settings_table()

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute(
        "SELECT key, value FROM smtp_settings"
    )

    rows = cursor.fetchall()

    conn.close()

    return {row[0]: row[1] for row in rows}


def _save_smtp(data: dict):

    _ensure_settings_table()

    conn = get_connection()

    for key, value in data.items():

        conn.execute(
            """
            INSERT INTO smtp_settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key)
            DO UPDATE SET value = excluded.value
            """,
            (key, str(value))
        )

    conn.commit()
    conn.close()


# -----------------------------------
# MAIN SETTINGS PAGE
# -----------------------------------

def render_settings():

    st.title("Settings")

    tab_smtp, tab_queue, tab_about, tab_reset = st.tabs([
        "📬 SMTP",
        "🔧 Queue Worker",
        "ℹ️ About",
        "🗑️ Reset"
    ])

    with tab_smtp:
        _render_smtp_settings()

    with tab_queue:
        _render_queue_status()

    with tab_about:
        _render_about()

    with tab_reset:
        _render_reset()


# -----------------------------------
# SMTP SETTINGS
# -----------------------------------

def _render_smtp_settings():

    st.subheader("SMTP Configuration")

    st.caption(
        "Settings are saved to SQLite and persist across restarts. "
        "You can also set them as environment variables on Streamlit Cloud."
    )

    stored = _get_all_smtp()

    with st.form("smtp_form"):

        smtp_server = st.text_input(
            "SMTP Server",
            value=stored.get("smtp_server", "smtp.titan.email")
        )

        smtp_port = st.number_input(
            "SMTP Port",
            value=int(stored.get("smtp_port", 465)),
            min_value=1,
            max_value=65535
        )

        smtp_username = st.text_input(
            "SMTP Username (your email)",
            value=stored.get("smtp_username", "")
        )

        smtp_password = st.text_input(
            "SMTP Password",
            value=stored.get("smtp_password", ""),
            type="password"
        )

        sender_name = st.text_input(
            "Sender Display Name",
            value=stored.get("sender_name", "")
        )

        use_ssl = st.checkbox(
            "Use SSL (Port 465) – recommended for Titan",
            value=stored.get("use_ssl", "true").lower() == "true"
        )

        col1, col2 = st.columns(2)

        save_btn = col1.form_submit_button(
            "💾 Save Settings",
            type="primary",
            use_container_width=True
        )

        test_btn = col2.form_submit_button(
            "🔌 Test Connection",
            use_container_width=True
        )

    if save_btn:

        _save_smtp({
            "smtp_server":   smtp_server,
            "smtp_port":     str(int(smtp_port)),
            "smtp_username": smtp_username,
            "smtp_password": smtp_password,
            "sender_name":   sender_name,
            "use_ssl":       "true" if use_ssl else "false",
        })

        st.success("SMTP Settings Saved.")

    if test_btn:

        from app.core.mailer import Mailer

        # Temporarily save so Mailer picks them up
        _save_smtp({
            "smtp_server":   smtp_server,
            "smtp_port":     str(int(smtp_port)),
            "smtp_username": smtp_username,
            "smtp_password": smtp_password,
            "sender_name":   sender_name,
            "use_ssl":       "true" if use_ssl else "false",
        })

        with st.spinner("Testing SMTP connection…"):

            mailer = Mailer()

            try:
                mailer.connect()
                mailer.disconnect()
                st.success("✅ SMTP Connection Successful!")

            except Exception as e:
                st.error(f"❌ Connection Failed: {str(e)}")

    # Provider hints
    with st.expander("💡 Provider Quick Setup"):
        st.markdown("""
**Titan Email (recommended)**
- Server: `smtp.titan.email`  |  Port: `465`  |  SSL: ✅

**Gmail**
- Server: `smtp.gmail.com`  |  Port: `465`  |  SSL: ✅
- Requires an [App Password](https://myaccount.google.com/apppasswords)

**Outlook / Office 365**
- Server: `smtp.office365.com`  |  Port: `587`  |  SSL: ❌ (uses STARTTLS)

**Streamlit Cloud Secrets** – add to `secrets.toml`:
```toml
SMTP_SERVER   = "smtp.titan.email"
SMTP_PORT     = "465"
SMTP_USERNAME = "you@yourdomain.com"
SMTP_PASSWORD = "yourpassword"
SENDER_NAME   = "Your Name"
USE_SSL       = "true"
```
        """)


# -----------------------------------
# QUEUE WORKER STATUS
# -----------------------------------

def _render_queue_status():

    st.subheader("Queue Worker Status")

    ws = worker_status()

    c1, c2, c3 = st.columns(3)

    c1.metric("Active Campaigns", ws["active_campaigns"])
    c2.metric("Total Processed",  ws["total_processed"])
    c3.metric("Total Failed",     ws["total_failed"])

    st.caption(f"Worker system started: {ws['started_at']}")

    if ws["workers"]:

        st.success("🟢 Workers Running")

        for w in ws["workers"]:
            st.markdown(
                f"- Campaign **{w['campaign_id']}** | "
                f"Started: `{w['started_at']}` | "
                f"Alive: `{w['alive']}`"
            )

    else:

        st.info(
            "No active workers. "
            "Launch a campaign to start a worker thread."
        )

    st.divider()

    st.subheader("How The Queue Works")

    st.markdown("""
| | **Old (Celery + Redis)** | **New (Thread Queue)** |
|---|---|---|
| Broker | Redis server | `queue.Queue` (in-memory) |
| Worker | Separate `celery worker` process | Daemon thread inside Streamlit |
| Job persistence | Redis + Celery backend | SQLite DB + in-memory queue |
| Batch limit | Per Celery task | 25 per `EmailWorker` batch |
| Titan delays | `8–15s` per email in task | Same delays preserved |
| Batch cooldown | N/A | 120s between batches |
| Hosting | Needs Redis add-on | Streamlit Cloud free tier ✅ |
    """)


# -----------------------------------
# ABOUT
# -----------------------------------

def _render_about():

    st.subheader("Marketing Campaign System v2")

    st.markdown("""
**Streamlit Cloud Edition** — no Redis, no Celery, no separate worker process.

### Architecture
```
app/
├── core/
│   ├── queue_manager.py   ← replaces celery_app.py + Redis
│   ├── worker.py          ← EmailWorker thread (same logic as tasks.py)
│   ├── mailer.py          ← Titan SSL SMTP (unchanged interface)
│   ├── csv_processor.py   ← same required columns
│   └── template_engine.py ← same Jinja2 interface
├── database/
│   └── db.py              ← SQLite (same schema + functions)
└── ui/
    ├── dashboard.py
    ├── campaigns.py
    ├── analytics.py
    └── settings.py
```

### CSV Format
Your CSV must have at minimum:

| contact_name | work_email |
|---|---|
| John Smith | john@company.com |

Optional: `job_title`, `company_name`, `mobile`, `industry`, `sub_industry`

All columns are available as Jinja2 variables in your HTML template.
    """)


# -----------------------------------
# DATABASE RESET
# -----------------------------------

def _render_reset():

    st.subheader("Reset Database")

    st.warning(
        "⚠️ This will permanently delete ALL campaigns, "
        "recipients, and email logs. Use only for testing."
    )

    confirm = st.checkbox(
        "I understand this cannot be undone"
    )

    if st.button(
        "🗑️ Clear All Data",
        type="primary",
        disabled=not confirm
    ):
        from app.database.db import clear_all_recipients
        clear_all_recipients()
        st.success("All data cleared. You can now run fresh campaigns.")
        st.rerun()

