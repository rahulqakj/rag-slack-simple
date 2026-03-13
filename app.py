"""
QA Assistant - Main Application Entry Point
"""
import streamlit as st
from streamlit_option_menu import option_menu
from streamlit_authenticator.utilities.hasher import Hasher
import streamlit_authenticator as stauth
from dotenv import load_dotenv

from src.config.settings import get_settings
from src.config.database import DatabaseConfig
from src.ui.chat_interface import ChatInterface
from src.ui.upload_interface import UploadInterface
from src.ui.analytics_interface import AnalyticsInterface
from src.ui.settings_interface import SettingsInterface


load_dotenv()


def create_authenticator() -> stauth.Authenticate:
    """Create and configure the authenticator."""
    settings = get_settings()
    auth = settings.auth
    
    hashed_password = Hasher.hash(auth.password)
    credentials = {
        "usernames": {
            auth.username: {
                "name": auth.display_name,
                "password": hashed_password,
            }
        }
    }
    
    return stauth.Authenticate(
        credentials,
        auth.cookie_name,
        auth.cookie_key,
        cookie_expiry_days=auth.cookie_expiry_days,
    )


def render_sidebar(authenticator: stauth.Authenticate, username: str) -> str:
    """Render sidebar navigation and return selected page."""
    with st.sidebar:
        st.title("QA Assistant")
        authenticator.logout("Log out", "sidebar")
        st.caption(f"Logged in as `{username}`")
        st.write("---")
        
        selected = option_menu(
            "Navigation",
            ["Chat", "Upload Knowledge", "Analytics", "Settings"],
            icons=["chat", "upload", "graph-up", "gear"],
            menu_icon="robot",
            default_index=0,
        )
        
        st.write("---")
        st.write("**Features:**")
        st.write("Multi-source knowledge retrieval")
        st.write("Feedback-aware responses")
        st.write("Chat memory & analytics")
        st.write("External API integrations")
    
    return selected


def main() -> None:
    """Main application entry point."""
    st.set_page_config(
        page_title="QA Assistant",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    
    authenticator = create_authenticator()
    authenticator.login(location="main")
    
    auth_status = st.session_state.get("authentication_status")
    username = st.session_state.get("username")
    
    if auth_status is True:
        logged_user = username or get_settings().auth.username
    elif auth_status is False:
        st.error("Invalid username or password.")
        st.stop()
    else:
        st.info("Please enter your username and password.")
        st.stop()
    
    try:
        DatabaseConfig.setup_database()
    except Exception as e:
        st.error(f"Error setting up the database: {e}")
        return
    
    selected = render_sidebar(authenticator, logged_user)
    
    if selected == "Chat":
        ChatInterface().render()
    elif selected == "Upload Knowledge":
        UploadInterface().render()
    elif selected == "Analytics":
        AnalyticsInterface().render()
    elif selected == "Settings":
        SettingsInterface().render()


if __name__ == "__main__":
    main()
