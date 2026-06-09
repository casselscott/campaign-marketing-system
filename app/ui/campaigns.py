import os

import streamlit as st

from app.core.csv_processor import load_csv
from app.core.queue_manager import (
    get_queue,
    launch_campaign_worker,
    get_active_workers
)
from app.core.worker import EmailWorker

from app.database.db import (
    create_campaign,
    get_all_campaigns,
    get_recipients_for_campaign,
    update_campaign_status,
    clear_all_recipients,
    get_connection,
    import_lead_list,
    get_next_batch,
    get_lead_list_stats,
    get_campaigns_with_pending_leads,
    insert_recipient,
    update_campaign_counts,
)


# -----------------------------------
# BATCH SIZE
# -----------------------------------

BATCH_SIZE = 25


def render_campaign_page():

    st.title("Email Campaigns")

    tab_send, tab_create, tab_list = st.tabs([
        "🚀 Send Next Batch",
        "➕ New Campaign",
        "📋 All Campaigns"
    ])

    with tab_send:
        _render_send_batch()

    with tab_create:
        _render_create_form()

    with tab_list:
        _render_campaign_list()


# -----------------------------------
# SEND NEXT BATCH (main workflow)
# -----------------------------------

def _render_send_batch():

    st.subheader("Send Next Batch")

    st.caption(
        f"Sends the next {BATCH_SIZE} unsent contacts "
        f"from your stored lead list. "
        f"Click again after each batch to continue."
    )

    # Get campaigns that still have leads to send
    pending_campaigns = get_campaigns_with_pending_leads()

    if not pending_campaigns:
        st.info(
            "No campaigns with pending leads. "
            "Create a campaign first in the **New Campaign** tab."
        )
        return

    # Campaign selector
    campaign_options = {
        c["id"]: f"{c['name']} — {c['subject']}"
        for c in pending_campaigns
    }

    selected_id = st.selectbox(
        "Select Campaign",
        options=list(campaign_options.keys()),
        format_func=lambda x: campaign_options[x]
    )

    if not selected_id:
        return

    # Show lead list progress
    stats = get_lead_list_stats(selected_id)

    col1, col2, col3 = st.columns(3)
    col1.metric("Total Leads",     stats["total"])
    col2.metric("Already Batched", stats["batched"])
    col3.metric("Remaining",       stats["remaining"])

    if stats["total"] > 0:
        pct = stats["batched"] / stats["total"]
        st.progress(pct, text=f"{int(pct * 100)}% of leads batched")

    if stats["remaining"] == 0:
        st.success(
            "✅ All leads have been batched for this campaign."
        )
        return

    # How many will go in this batch
    this_batch = min(BATCH_SIZE, stats["remaining"])

    st.info(
        f"Next batch will send **{this_batch} emails** "
        f"({stats['remaining']} remaining after this: "
        f"{max(0, stats['remaining'] - this_batch)})"
    )

    # Active worker check
    workers = get_active_workers()
    active_ids = [w["campaign_id"] for w in workers]

    if selected_id in active_ids:
        st.warning(
            "⏳ A worker is already running for this campaign. "
            "Wait for it to finish before sending the next batch."
        )
        return

    if st.button(
        f"🚀 Send Next {this_batch} Emails",
        type="primary",
        use_container_width=True
    ):
        _dispatch_batch(selected_id)


def _dispatch_batch(campaign_id):
    """Pull next batch from lead_list and launch worker."""

    # Get campaign for subject
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT subject FROM campaigns WHERE id=?",
        (campaign_id,)
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        st.error("Campaign not found.")
        return

    subject = row[0]

    # Pull next batch from lead_list (marks them batched=1)
    batch = get_next_batch(campaign_id, BATCH_SIZE)

    if not batch:
        st.warning("No more leads to send.")
        return

    # Insert into recipients table + push to queue
    q = get_queue()
    queued = 0

    for recipient in batch:

        insert_recipient(campaign_id, recipient)
        q.put(recipient)
        queued += 1

    update_campaign_counts(campaign_id)

    # Launch worker thread
    worker = EmailWorker(
        campaign_id=campaign_id,
        subject=subject
    )

    launch_campaign_worker(worker)

    st.success(
        f"✅ Batch of **{queued} emails** queued and worker started!"
    )

    stats = get_lead_list_stats(campaign_id)

    if stats["remaining"] > 0:
        st.info(
            f"**{stats['remaining']} leads still remaining.** "
            f"Come back after this batch finishes and click "
            f"'Send Next Batch' again."
        )
    else:
        st.success(
            "🎉 That was the final batch — all leads have been dispatched!"
        )

    st.caption(
        "Recommended Titan Strategy:\n"
        "- 25 Emails Per Batch\n"
        "- Wait for batch to finish before next\n"
        "- Avoid Aggressive Retries\n"
        "- Protect SMTP Reputation"
    )


# -----------------------------------
# CREATE CAMPAIGN FORM
# -----------------------------------

def _render_create_form():

    st.subheader("Create New Campaign")

    st.caption(
        "Upload your full CSV once here. "
        "The system stores all contacts and lets you "
        "send in batches of 25 from the **Send Next Batch** tab."
    )

    campaign_name = st.text_input("Campaign Name")

    subject = st.text_input("Email Subject")

    uploaded_csv = st.file_uploader(
        "Upload Full Contacts CSV (upload once — all 500 contacts)",
        type=["csv"]
    )

    uploaded_html = st.file_uploader(
        "Upload HTML Template",
        type=["html"]
    )

    df = None

    if uploaded_csv:

        try:

            df = load_csv(uploaded_csv)

            st.success("CSV Loaded Successfully")

            st.dataframe(
                df.head(5),
                use_container_width=True
            )

            st.info(
                f"**{len(df)} total contacts loaded.** "
                f"They will be stored and sent in batches of {BATCH_SIZE}."
            )

        except Exception as e:

            st.error(str(e))
            return

    if st.button(
        "💾 Create Campaign & Store Contacts",
        type="primary",
        use_container_width=True
    ):

        if not campaign_name:
            st.error("Please Enter Campaign Name")
            return

        if not subject:
            st.error("Please Enter Email Subject")
            return

        if uploaded_csv is None or df is None:
            st.error("Please Upload CSV File")
            return

        if uploaded_html is None:
            st.error("Please Upload HTML Template")
            return

        try:

            # Save HTML template
            os.makedirs("templates", exist_ok=True)

            with open("templates/campaign.html", "wb") as f:
                f.write(uploaded_html.read())

            # Create campaign (total_emails set later by import)
            campaign_id = create_campaign(
                campaign_name,
                subject,
                0
            )

            # Import ALL contacts into lead_list
            rows = df.to_dict(orient="records")
            imported = import_lead_list(campaign_id, rows)

            st.success(
                f"✅ Campaign **{campaign_name}** created with "
                f"**{imported} contacts** stored."
            )

            stats = get_lead_list_stats(campaign_id)

            st.info(
                f"Go to the **🚀 Send Next Batch** tab to start sending. "
                f"You can send {BATCH_SIZE} at a time until all "
                f"{stats['total']} contacts are done."
            )

            if imported < len(df):
                st.warning(
                    f"{len(df) - imported} contacts were skipped "
                    f"(duplicate emails within the CSV)."
                )

        except Exception as e:

            st.error(f"Campaign Error: {str(e)}")


# -----------------------------------
# CAMPAIGN LIST
# -----------------------------------

def _render_campaign_list():

    st.subheader("All Campaigns")

    campaigns = get_all_campaigns()

    if not campaigns:
        st.info("No campaigns yet.")
        return

    workers = get_active_workers()
    active_ids = [w["campaign_id"] for w in workers]

    if active_ids:
        st.success(
            f"🟢 Active workers for campaign(s): "
            f"{', '.join(str(i) for i in active_ids)}"
        )

    for c in campaigns:

        status_icon = {
            "sending":   "🚀",
            "completed": "✅",
            "failed":    "❌",
            "queued":    "⏳",
        }.get(c["status"], "📝")

        # Lead list progress
        stats = get_lead_list_stats(c["id"])

        with st.expander(
            f"{status_icon} {c['name']}  —  {c['subject']}"
        ):

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Total Leads",  stats["total"])
            col2.metric("Sent",         c["sent_count"])
            col3.metric("Failed",       c["failed_count"])
            col4.metric("Remaining",    stats["remaining"])

            if stats["total"] > 0:
                pct = stats["batched"] / stats["total"]
                st.progress(
                    pct,
                    text=f"{int(pct * 100)}% batched"
                )

            st.caption(
                f"Status: {c['status']}  |  "
                f"Created: {c['created_at']}  |  "
                f"Completed: {c['completed_at'] or '—'}"
            )

            recipients = get_recipients_for_campaign(c["id"])
            if recipients:
                with st.expander(
                    f"👥 Sent Recipients ({len(recipients)})"
                ):
                    rows = [
                        {
                            "name":    r["contact_name"],
                            "email":   r["work_email"],
                            "company": r["company_name"],
                            "status":  r["status"],
                            "error":   r["error_message"] or "",
                        }
                        for r in recipients[:200]
                    ]
                    st.dataframe(
                        rows,
                        use_container_width=True,
                        hide_index=True
                    )
