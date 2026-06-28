"""
Enterprise Authentication UI
Soft Tech Group
"""

import hmac
import os

import streamlit as st


# ---------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------

def is_authenticated():
    return bool(st.session_state.get("authenticated"))


# ---------------------------------------------------------------------
# Login Page
# ---------------------------------------------------------------------

def render_login():

    st.markdown("""
<style>

/* ------------------------------------------------ */
/* Hide Streamlit UI */
/* ------------------------------------------------ */

#MainMenu {visibility:hidden;}
footer {visibility:hidden;}
header {visibility:hidden;}

.block-container{
    max-width:1250px;
    padding-top:3rem;
}


/* ------------------------------------------------ */
/* Background */
/* ------------------------------------------------ */

.stApp{

background:
radial-gradient(circle at top left,#18203d 0%,#0d1320 40%,#090b12 100%);
}


/* ------------------------------------------------ */
/* Layout */
/* ------------------------------------------------ */

.auth-wrapper{

display:flex;
gap:70px;
align-items:center;
justify-content:center;

}


/* ------------------------------------------------ */
/* Left Side */
/* ------------------------------------------------ */

.hero{

flex:1;

}

.logo{

width:170px;
margin-bottom:30px;

}

.hero h1{

font-size:62px;
font-weight:700;
line-height:1.05;
color:white;
margin-bottom:25px;

}

.hero span{

background:linear-gradient(90deg,#4EA8FF,#8B5CF6);

-webkit-background-clip:text;
-webkit-text-fill-color:transparent;

}

.hero p{

font-size:21px;
color:#AEB6C7;
line-height:1.7;
max-width:520px;

}


/* ------------------------------------------------ */
/* Login Card */
/* ------------------------------------------------ */

.login-card{

flex:1;

background:rgba(17,24,39,.78);

border:1px solid rgba(255,255,255,.08);

backdrop-filter:blur(16px);

border-radius:22px;

padding:45px;

box-shadow:0 20px 70px rgba(0,0,0,.35);

}

.login-card h2{

color:white;

font-size:40px;

margin-bottom:10px;

}

.login-card p{

color:#9CA3AF;

margin-bottom:35px;

font-size:18px;

}


/* ------------------------------------------------ */
/* Inputs */
/* ------------------------------------------------ */

div[data-baseweb="input"]{

background:#1C2435;

border-radius:14px;

border:1px solid #2D3748;

}

div[data-baseweb="input"]:focus-within{

border:1px solid #4F46E5;

box-shadow:0 0 15px rgba(99,102,241,.3);

}


/* ------------------------------------------------ */
/* Button */
/* ------------------------------------------------ */

.stButton>button,
.stFormSubmitButton>button{

width:100%;

height:56px;

border:none;

border-radius:14px;

font-size:18px;

font-weight:600;

color:white;

background:linear-gradient(90deg,#2D7FFF,#8B5CF6);

transition:.3s;

}

.stButton>button:hover,
.stFormSubmitButton>button:hover{

transform:translateY(-2px);

box-shadow:0 15px 30px rgba(80,100,255,.35);

}


/* ------------------------------------------------ */

.footer{

margin-top:30px;

text-align:center;

color:#6B7280;

font-size:13px;

}

</style>
""", unsafe_allow_html=True)

    username = os.getenv("AUTH_USERNAME", "")
    password = os.getenv("AUTH_PASSWORD", "")

    if not username or not password:
        st.error("AUTH_USERNAME and AUTH_PASSWORD are not configured.")
        st.stop()

    left, right = st.columns([1.1, 1])

    with left:

        st.markdown(f"""
<div class="hero">

<img class="logo"
src="https://res.cloudinary.com/dxvfabxw8/image/upload/v1772831186/logo_zqzkzj.png">

<h1>
Marketing<br>
<span>Campaign System</span>
</h1>

<p>
Powerful enterprise email campaigns with intelligent automation,
analytics, personalization and reliable delivery.
</p>

</div>
""", unsafe_allow_html=True)

    with right:

        st.markdown("""
<div class="login-card">

<h2>Welcome Back</h2>

<p>Sign in to continue.</p>

</div>
""", unsafe_allow_html=True)

        with st.form("login_form", clear_on_submit=False):

            entered_user = st.text_input(
                "Username",
                placeholder="Enter username"
            )

            entered_password = st.text_input(
                "Password",
                type="password",
                placeholder="Enter password"
            )

            submitted = st.form_submit_button(
                "Sign In →",
                use_container_width=True
            )

        if submitted:

            valid = (
                hmac.compare_digest(entered_user, username)
                and
                hmac.compare_digest(entered_password, password)
            )

            if valid:

                st.session_state["authenticated"] = True
                st.session_state["auth_user"] = entered_user
                st.rerun()

            else:

                st.error("Invalid username or password.")

        st.markdown(
            """
<div class="footer">
© 2026 Soft Tech Group • Enterprise Marketing Platform
</div>
""",
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------

def logout():

    st.session_state.pop("authenticated", None)
    st.session_state.pop("auth_user", None)

    st.rerun()