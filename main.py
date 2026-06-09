import streamlit as st
from dotenv import load_dotenv
load_dotenv()

# ── Must be first ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Marketing Campaign System",
    page_icon="📧",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── Bootstrap ─────────────────────────────────────────────────────────────────
from app.database.db import initialize_database

initialize_database()

# ── Pages ─────────────────────────────────────────────────────────────────────
from app.ui.dashboard  import render_dashboard
from app.ui.campaigns  import render_campaign_page
from app.ui.analytics  import render_analytics
from app.ui.settings   import render_settings

# ── Sidebar Navigation ────────────────────────────────────────────────────────
with st.sidebar:

    st.image(
        "https://res.cloudinary.com/dxvfabxw8/image/upload/v1772831186/logo_zqzkzj.png",
        use_container_width=True
    )

    st.divider()

    page = st.radio(
        "Navigation",
        [
            "📊 Dashboard",
            "📧 Campaigns",
            "📈 Analytics",
            "⚙️ Settings"
        ],
        label_visibility="collapsed"
    )

    st.divider()

    from app.core.queue_manager import worker_status
    ws = worker_status()

    st.metric(
        "Active Workers",
        ws["active_campaigns"]
    )

    st.metric(
        "Emails Sent",
        ws["total_processed"]
    )

# ── Render ────────────────────────────────────────────────────────────────────
if page == "📊 Dashboard":
    render_dashboard()

elif page == "📧 Campaigns":
    render_campaign_page()

elif page == "📈 Analytics":
    render_analytics()

elif page == "⚙️ Settings":
    render_settings()
