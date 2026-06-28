import streamlit as st
import pandas as pd
import plotly.express as px

from app.database.db import get_connection


def render_analytics():

    st.title("Campaign Analytics")

    # -----------------------------------
    # AUTO REFRESH (every 5 s)
    # -----------------------------------

    try:
        from streamlit_autorefresh import st_autorefresh
        st_autorefresh(interval=5000, key="analytics_refresh")
    except ImportError:
        if st.button("🔄 Refresh"):
            st.rerun()

    conn = get_connection()

    # -----------------------------------
    # RECIPIENT ANALYTICS
    # -----------------------------------

    recipients_df = pd.read_sql_query(
        """
        SELECT

            campaign_id,

            contact_name,

            company_name,

            work_email,

            industry,

            sub_industry,

            status,

            error_message,

            smtp_category,

            retry_count,

            sent_at,

            created_at

        FROM recipients
        """,
        conn
    )

    # -----------------------------------
    # CAMPAIGN ANALYTICS
    # -----------------------------------

    campaigns_df = pd.read_sql_query(
        """
        SELECT

            id,
            name,
            subject,

            status,

            total_emails,

            sent_count,
            failed_count,
            pending_count,
            queued_count,
            recovery_count,

            created_at

        FROM campaigns

        ORDER BY id DESC
        """,
        conn
    )

    logs_df = pd.read_sql_query(
        """
        SELECT campaign_id, status, smtp_category, duration_ms, created_at
        FROM email_logs ORDER BY id DESC
        """,
        conn
    )

    conn.close()

    # -----------------------------------
    # EMPTY STATE
    # -----------------------------------

    if recipients_df.empty:

        st.warning("No Analytics Data Available")
        return

    # -----------------------------------
    # DELIVERY PERFORMANCE
    # -----------------------------------

    sent_total = int((recipients_df["status"] == "sent").sum())
    failed_total = int((recipients_df["status"] == "failed").sum())
    attempted = sent_total + failed_total
    retries = int(recipients_df["retry_count"].fillna(0).sum())
    avg_duration = logs_df["duration_ms"].dropna().mean() if not logs_df.empty else 0

    p1, p2, p3, p4 = st.columns(4)
    p1.metric("Delivery Rate", f"{(sent_total / attempted * 100) if attempted else 0:.1f}%")
    p2.metric("Retries", retries)
    p3.metric("Avg Delivery Time", f"{(avg_duration or 0) / 1000:.2f}s")
    p4.metric("Failures", failed_total)

    if not logs_df.empty:
        logs_df["created_at"] = pd.to_datetime(logs_df["created_at"], errors="coerce")
        trend = (
            logs_df.dropna(subset=["created_at"])
            .assign(period=lambda frame: frame["created_at"].dt.floor("h"))
            .groupby(["period", "status"]).size().reset_index(name="Count")
        )
        if not trend.empty:
            st.subheader("Delivery Trend")
            trend_fig = px.line(
                trend, x="period", y="Count", color="status", markers=True,
                title="Hourly Delivery Performance",
            )
            st.plotly_chart(trend_fig, use_container_width=True)

    # -----------------------------------
    # DELIVERY STATUS PIE CHART
    # -----------------------------------

    st.subheader("Email Delivery Status")

    status_counts = (
        recipients_df["status"]
        .value_counts()
        .reset_index()
    )

    status_counts.columns = ["Status", "Count"]

    fig = px.pie(
        status_counts,
        names="Status",
        values="Count",
        title="Delivery Status Distribution",
        color="Status",
        color_discrete_map={
            "sent":    "#22c55e",
            "failed":  "#ef4444",
            "pending": "#f59e0b",
            "queued":  "#3b82f6",
        }
    )

    st.plotly_chart(fig, use_container_width=True)

    # -----------------------------------
    # INDUSTRY SEGMENTATION
    # -----------------------------------

    st.subheader("Recipients By Industry")

    industry_df = recipients_df[
        recipients_df["industry"].notna()
        & (recipients_df["industry"] != "")
    ]

    if not industry_df.empty:

        industry_counts = (
            industry_df["industry"]
            .value_counts()
            .reset_index()
        )

        industry_counts.columns = ["Industry", "Count"]

        fig2 = px.bar(
            industry_counts,
            x="Industry",
            y="Count",
            title="Industry Segmentation",
            color="Count",
            color_continuous_scale="Blues"
        )

        st.plotly_chart(fig2, use_container_width=True)

    else:

        st.info("No Industry Data Available")

    # -----------------------------------
    # SMTP CATEGORY BREAKDOWN
    # -----------------------------------

    smtp_df = recipients_df[
        recipients_df["smtp_category"].notna()
        & (recipients_df["smtp_category"] != "")
    ]

    if not smtp_df.empty:

        st.subheader("SMTP Failure Categories")

        smtp_counts = (
            smtp_df["smtp_category"]
            .value_counts()
            .reset_index()
        )

        smtp_counts.columns = ["Category", "Count"]

        fig_smtp = px.bar(
            smtp_counts,
            x="Category",
            y="Count",
            title="SMTP Failure Classification"
        )

        st.plotly_chart(fig_smtp, use_container_width=True)

    # -----------------------------------
    # CAMPAIGN PERFORMANCE TABLE
    # -----------------------------------

    st.subheader("Campaign Performance")

    if campaigns_df.empty:

        st.warning("No Campaign Data Available")

    else:

        performance_df = campaigns_df[[
            "id",
            "name",
            "status",
            "total_emails",
            "sent_count",
            "failed_count",
            "pending_count",
            "queued_count",
            "recovery_count",
            "created_at"
        ]]

        st.dataframe(
            performance_df,
            use_container_width=True
        )

    # -----------------------------------
    # CAMPAIGN STATUS BREAKDOWN
    # -----------------------------------

    st.subheader("Campaign Status Breakdown")

    if not campaigns_df.empty:

        campaign_status_counts = (
            campaigns_df["status"]
            .value_counts()
            .reset_index()
        )

        campaign_status_counts.columns = ["Status", "Count"]

        fig3 = px.bar(
            campaign_status_counts,
            x="Status",
            y="Count",
            title="Campaign Lifecycle Status"
        )

        st.plotly_chart(fig3, use_container_width=True)

    # -----------------------------------
    # RECENT RECIPIENT ACTIVITY
    # -----------------------------------

    st.subheader("Recent Recipient Activity")

    recent_df = recipients_df.sort_values(
        by="created_at",
        ascending=False
    ).head(20)

    st.dataframe(
        recent_df,
        use_container_width=True
    )

    # -----------------------------------
    # FAILED EMAIL RECOVERY
    # -----------------------------------

    st.divider()

    st.subheader("Failed Email Recovery")

    failed_df = recipients_df[
        recipients_df["status"] == "failed"
    ]

    if failed_df.empty:

        st.success("No Failed Emails Found")

    else:

        st.warning(
            f"{len(failed_df)} Failed Emails Detected"
        )

        failed_export_df = failed_df[[

            "contact_name",
            "company_name",
            "work_email",
            "industry",
            "sub_industry",
            "smtp_category",
            "error_message",
            "retry_count",
            "created_at"
        ]]

        st.dataframe(
            failed_export_df,
            use_container_width=True
        )

        # -----------------------------------
        # DOWNLOAD FAILED EMAILS CSV
        # -----------------------------------

        csv_data = failed_export_df.to_csv(
            index=False
        ).encode("utf-8")

        st.download_button(
            label="⬇️ Download Failed Emails CSV",
            data=csv_data,
            file_name="failed_emails.csv",
            mime="text/csv"
        )

        # -----------------------------------
        # FAILURE INSIGHTS
        # -----------------------------------

        st.subheader("Failure Insights")

        failure_reasons = (
            failed_df["error_message"]
            .fillna("Unknown Error")
            .value_counts()
            .reset_index()
        )

        failure_reasons.columns = ["Error", "Count"]

        fig4 = px.bar(
            failure_reasons,
            x="Error",
            y="Count",
            title="Top Failure Reasons"
        )

        st.plotly_chart(fig4, use_container_width=True)

        st.info(
            "Recommended Workflow:\n\n"
            "1. Download Failed Emails CSV\n"
            "2. Remove Invalid Emails\n"
            "3. Clean Master Lead List\n"
            "4. Retry ONLY Temporary Failures\n\n"
            "Avoid aggressive retries to "
            "protect Titan SMTP reputation."
        )
