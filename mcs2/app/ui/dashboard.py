import streamlit as st

from app.database.db import (
    get_dashboard_metrics,
    get_all_campaigns
)

from app.core.queue_manager import worker_status
from app.core.campaign_monitor import get_system_health, recover_campaign
from app.core.mailer import get_smtp_health
from app.core.rate_limiter import get_rate_limiter


def render_dashboard():

    st.title("Dashboard")

    # -----------------------------------
    # AUTO REFRESH
    # -----------------------------------

    try:
        from streamlit_autorefresh import st_autorefresh
        st_autorefresh(interval=5000, key="dashboard_refresh")
    except ImportError:
        if st.button("🔄 Refresh"):
            st.rerun()

    # -----------------------------------
    # GLOBAL METRICS
    # -----------------------------------

    metrics = get_dashboard_metrics()

    st.subheader("📊 Global Email Stats")

    col1, col2, col3, col4, col5 = st.columns(5)

    col1.metric(
        "Total Recipients",
        metrics["total_recipients"]
    )

    col2.metric(
        "✅ Sent",
        metrics["sent_emails"]
    )

    col3.metric(
        "❌ Failed",
        metrics["failed_emails"]
    )

    col4.metric(
        "⏳ Pending",
        metrics["pending_emails"]
    )

    col5.metric(
        "🔵 Queued",
        metrics["queued_emails"]
    )

    # Overall delivery rate
    total = metrics["total_recipients"]

    if total > 0:

        rate = metrics["sent_emails"] / total

        st.progress(
            rate,
            text=f"Overall Delivery Rate: {int(rate * 100)}%"
        )

    st.divider()

    # -----------------------------------
    # ENTERPRISE HEALTH
    # -----------------------------------

    st.subheader("Campaign Engine Health")
    health = get_system_health()
    smtp = get_smtp_health()
    limiter = get_rate_limiter().status()

    hc1, hc2, hc3, hc4 = st.columns(4)
    hc1.metric("System Health", health["health"].title())
    hc2.metric("Queue Depth", health["queue_depth"])
    hc3.metric("Stalled Campaigns", health["stalled_campaigns"])
    hc4.metric("Daily Quota Remaining", limiter["remaining_today"])

    sc1, sc2, sc3, sc4 = st.columns(4)
    sc1.metric("SMTP Connections", smtp["connections"])
    sc2.metric("SMTP Reconnects", smtp["reconnections"])
    sc3.metric("SMTP Retries", smtp["retries"])
    sc4.metric("SMTP Failures", smtp["failed"])

    active_health = [
        item for item in health["campaigns"]
        if item["status"] not in {"completed", "cancelled"}
    ]
    for item in active_health:
        icon = {"healthy": "🟢", "warning": "🟠", "critical": "🔴"}[item["health"]]
        eta = f"{item['eta_minutes']} min" if item["eta_minutes"] is not None else "Calculating"
        with st.expander(f"{icon} {item['name']} — {item['health'].title()}"):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Worker", item["worker_status"].title())
            c2.metric("Throughput", f"{item['throughput_per_minute']}/min")
            c3.metric("Remaining", item["remaining"])
            c4.metric("ETA", eta)
            st.caption(
                f"Success: {item['success_rate']}% · Failure: {item['failure_rate']}% · "
                f"Recovery attempts: {item['recovery_count']} · {item['recommendation']}"
            )
            if item["stalled"] and st.button(
                "Recover Campaign", key=f"recover_campaign_{item['campaign_id']}"
            ):
                if recover_campaign(item["campaign_id"]):
                    st.success("Campaign worker recovered.")
                    st.rerun()
                else:
                    st.warning("Campaign could not be recovered or is already running.")

    st.divider()

    # -----------------------------------
    # WORKER STATUS
    # -----------------------------------

    st.subheader("⚙️ Queue Worker")

    ws = worker_status()

    wc1, wc2, wc3 = st.columns(3)

    wc1.metric(
        "Active Campaigns",
        ws["active_campaigns"]
    )

    wc2.metric(
        "Total Processed",
        ws["total_processed"]
    )

    wc3.metric(
        "Total Failed",
        ws["total_failed"]
    )

    if ws["workers"]:

        st.success(
            "🟢 Workers Running"
        )

        for w in ws["workers"]:
            st.caption(
                f"Campaign {w['campaign_id']} | "
                f"Started: {w['started_at']} | "
                f"Alive: {w['alive']}"
            )

    else:

        st.info(
            "No active workers. "
            "Start a campaign to begin sending."
        )

    st.divider()

    # -----------------------------------
    # RECENT CAMPAIGNS
    # -----------------------------------

    st.subheader("🗂️ Recent Campaigns")

    campaigns = get_all_campaigns()

    if not campaigns:

        st.info(
            "No campaigns yet. "
            "Go to Campaigns to create one."
        )

        return

    for c in campaigns[:8]:

        status_icon = {
            "sending":   "🚀",
            "completed": "✅",
            "failed":    "❌",
            "queued":    "⏳",
        }.get(c["status"], "📝")

        pct = 0

        if c["total_emails"] > 0:
            pct = c["sent_count"] / c["total_emails"]

        with st.expander(
            f"{status_icon} {c['name']}  |  {c['status'].upper()}"
        ):

            ca, cb, cc = st.columns(3)

            ca.metric("Sent",   c["sent_count"])
            cb.metric("Failed", c["failed_count"])
            cc.metric("Queued", c["queued_count"])

            if c["total_emails"] > 0:
                st.progress(
                    pct,
                    text=f"{int(pct * 100)}%"
                )

            st.caption(
                f"Subject: {c['subject']}  |  "
                f"Created: {c['created_at']}"
            )
