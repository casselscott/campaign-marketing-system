import streamlit as st
import hashlib
import os


# -----------------------------------
# CREDENTIALS
# Stored in Streamlit secrets or env.
# Default: admin / softech2026
# -----------------------------------

def _get_credentials():
    try:
        users = {
            st.secrets.get("AUTH_USERNAME", os.getenv("AUTH_USERNAME", "admin")):
            st.secrets.get("AUTH_PASSWORD", os.getenv("AUTH_PASSWORD", "softtech2026"))
        }
    except Exception:
        users = {
            os.getenv("AUTH_USERNAME", "admin"):
            os.getenv("AUTH_PASSWORD", "softtech2026")
        }
    return users


def _hash(password):
    return hashlib.sha256(password.encode()).hexdigest()


def is_authenticated():
    return st.session_state.get("authenticated", False)


def logout():
    st.session_state["authenticated"] = False
    st.session_state["auth_user"] = ""
    st.rerun()


def render_login():
    # Full-page centered login — no sidebar
    st.markdown("""
        <style>
            [data-testid="stSidebar"] { display: none; }
            [data-testid="collapsedControl"] { display: none; }
            .block-container {
                max-width: 480px !important;
                padding-top: 60px !important;
                margin: 0 auto;
            }
            .login-card {
                background: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 20px;
                padding: 48px 40px 40px;
                box-shadow: 0 4px 32px rgba(0,0,0,0.08);
            }
            .login-label {
                font-size: 13px;
                font-weight: 600;
                color: #64748b;
                letter-spacing: 0.06em;
                text-transform: uppercase;
                margin-bottom: 6px;
            }
            .login-title {
                font-size: 22px;
                font-weight: 700;
                color: #0f172a;
                margin: 0 0 4px;
                text-align: center;
            }
            .login-sub {
                font-size: 14px;
                color: #94a3b8;
                text-align: center;
                margin-bottom: 36px;
            }
            div[data-testid="stForm"] {
                border: none !important;
                padding: 0 !important;
            }
        </style>
    """, unsafe_allow_html=True)

    # Logo
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.image(
            "https://res.cloudinary.com/dxvfabxw8/image/upload/v1772831186/logo_zqzkzj.png",
            use_container_width=True
        )

    st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)
    st.markdown("<div class='login-title'>Campaign System</div>", unsafe_allow_html=True)
    st.markdown("<div class='login-sub'>Soft Tech Group · Internal Platform</div>", unsafe_allow_html=True)
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # Login form
    with st.form("login_form"):
        username = st.text_input(
            "Username",
            placeholder="Enter username",
        )
        password = st.text_input(
            "Password",
            type="password",
            placeholder="Enter password",
        )
        submitted = st.form_submit_button(
            "Sign In →",
            use_container_width=True,
            type="primary"
        )

    if submitted:
        credentials = _get_credentials()
        if username in credentials and credentials[username] == password:
            st.session_state["authenticated"] = True
            st.session_state["auth_user"] = username
            st.rerun()
        else:
            st.error("Invalid username or password.")

    st.markdown(
        "<div style='text-align:center;margin-top:32px;font-size:12px;color:#cbd5e1'>"
        "© 2026 Soft Tech Group · Confidential</div>",
        unsafe_allow_html=True
    )