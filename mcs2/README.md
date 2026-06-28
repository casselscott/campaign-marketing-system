# Marketing Campaign System v3.0

Streamlit marketing campaign engine using SQLite, Titan SMTP, Jinja2 templates,
and one Python thread worker per active campaign.

## Enterprise safeguards

- SQLite WAL mode, busy timeout, foreign keys, memory-backed temporary tables,
  aggregate queries, indexes, and transactional CSV/batch operations.
- One isolated queue and one worker per campaign, protected by locks.
- Persistent SMTP sessions with periodic `NOOP` validation, reconnects,
  classified retries, timeouts, and process-level health statistics.
- Durable recipient state, worker heartbeats, stalled-campaign detection,
  queue rebuilding, and automatic recovery after a Streamlit restart.
- Business-hour, daily-quota, batch-pause, and human-delay enforcement.
- Live health, throughput, ETA, queue, worker, SMTP, retry, and delivery metrics.
- Rotating logs at `logs/mailer.log` (five 5 MiB backups).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Set configuration in an uncommitted `.env` file:

```dotenv
AUTH_USERNAME=admin
AUTH_PASSWORD=choose-a-strong-password
SMTP_SERVER=smtp.titan.email
SMTP_PORT=465
SMTP_USERNAME=sender@example.com
SMTP_PASSWORD=your-smtp-password
SENDER_NAME=Your Company
USE_SSL=true
```

Run the application:

```bash
streamlit run main.py
```

The database is created at `data/campaigns.db`. Existing v2 tables are migrated
in place when `initialize_database()` runs. Campaign-specific templates are
stored under `templates/` and excluded from Git.

## Recovery behavior

When the application process restarts, campaigns in `sending` or `recovering`
state have their pending recipients rebuilt into their campaign queue and a new
worker is launched. Sent recipients are never requeued. Leads not yet claimed
by the manual batch workflow remain available through **Send Next Batch**.

## Verification

```bash
python -m unittest discover -v
python -m compileall -q app tests config.py main.py
```

Tests use temporary SQLite databases and fake SMTP clients; they do not send
email.
