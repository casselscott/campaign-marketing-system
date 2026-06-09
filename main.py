import streamlit as st
from dotenv import load_dotenv
load_dotenv()

# ── Must be first ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Soft Tech · Campaign System",
    page_icon="📧",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── Auth gate ─────────────────────────────────────────────────────────────────
from app.ui.auth import is_authenticated, render_login

if not is_authenticated():
    render_login()
    st.stop()

# ── Bootstrap (only runs when authenticated) ──────────────────────────────────
from app.database.db import initialize_database
initialize_database()

# ── Pages ─────────────────────────────────────────────────────────────────────
from app.ui.dashboard  import render_dashboard
from app.ui.campaigns  import render_campaign_page
from app.ui.analytics  import render_analytics
from app.ui.settings   import render_settings
from app.ui.auth       import logout

# ── Sidebar ───────────────────────────────────────────────────────────────────
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

    st.metric("Active Workers", ws["active_campaigns"])
    st.metric("Emails Sent",    ws["total_processed"])

    st.divider()

    # Logged in user + logout
    user = st.session_state.get("auth_user", "admin")
    st.caption(f"Signed in as **{user}**")
    if st.button("🚪 Sign Out", use_container_width=True):
        logout()

# ── Render ────────────────────────────────────────────────────────────────────
if page == "📊 Dashboard":
    render_dashboard()

elif page == "📧 Campaigns":
    render_campaign_page()

elif page == "📈 Analytics":
    render_analytics()

elif page == "⚙️ Settings":
    render_settings()