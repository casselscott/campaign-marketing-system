import streamlit as st

from app.database.db import (
    get_dashboard_metrics,
    get_all_campaigns
)

from app.core.queue_manager import worker_status


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
