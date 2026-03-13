"""
Settings interface for the QA Assistant.
"""
import os
import sys
import platform

import streamlit as st

from src.config.settings import get_settings
from src.config.api_config import APIConfig
from src.core.base import DatabaseConnection


class SettingsInterface:
    """Settings interface for viewing and configuring the QA Assistant."""
    
    def render(self) -> None:
        """Render the settings interface."""
        st.title("Settings")
        
        st.write("### API Configuration")
        self._render_api_status()
        
        st.write("### Database Configuration")
        self._render_database_status()
        
        st.write("### System Information")
        self._render_system_info()
    
    def _render_api_status(self) -> None:
        """Render API status indicators."""
        api_status = APIConfig.check_api_status()
        settings = get_settings()
        
        st.write("**Core APIs**")
        if api_status["gemini"]:
            st.success("Google Gemini API - Connected")
        else:
            st.error("Google Gemini API - Not configured")
        
        st.write("### API Key Configuration")
        
        if settings.gemini.is_configured:
            st.success("Google Gemini API Key configured")
        else:
            st.error("Google Gemini API Key not configured")
    
    def _render_database_status(self) -> None:
        """Render database connection status."""
        try:
            settings = get_settings()
            DatabaseConnection.configure(
                host=settings.database.host,
                port=settings.database.port,
                dbname=settings.database.name,
                user=settings.database.user,
                password=settings.database.password,
            )
            
            with DatabaseConnection.get_connection():
                st.success("Database Connection - Active")
        except Exception as e:
            st.error(f"Database Connection Failed: {e}")
    
    def _render_system_info(self) -> None:
        """Render system information."""
        col1, col2 = st.columns(2)
        
        with col1:
            st.write("#### Python Information:")
            st.write(f"**Python Version**: {sys.version}")
            st.write(f"**Platform**: {platform.platform()}")
        
        with col2:
            st.write("#### Application Information:")
            st.write("**Version**: 1.0.0")
            st.write("**Framework**: Streamlit")
            st.write("**LLM**: Google Gemini")
            st.write("**Database**: PostgreSQL + pgvector")
    
    def _mask_value(self, value: str | None) -> str:
        """Mask sensitive values for display."""
        if not value:
            return "Not set"
        if len(value) > 8:
            return value[:4] + "*" * (len(value) - 8) + value[-4:]
        return "*" * len(value)
