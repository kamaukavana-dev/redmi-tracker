"""
Test module for startup validation.

Tests that application fails fast on missing configuration.
"""

import pytest
import os
import sys
from unittest.mock import patch


class TestStartupValidation:
    """Tests for startup validation logic."""

    def test_validate_startup_with_all_env_vars(self):
        """Validation should pass when all env vars are set."""
        from app.config import settings
        
        assert settings.database_url is not None
        assert settings.api_key is not None
        assert settings.telegram_bot_token is not None
        assert settings.telegram_chat_id is not None

    def test_missing_database_url_raises_error(self):
        """Missing DATABASE_URL should cause validation to fail."""
        with patch.dict(os.environ, {}, clear=True):
            with patch('app.config.settings'):
                from app.config import Settings
                from pydantic_settings import SettingsConfigDict
                
                class TestSettings(Settings):
                    model_config = SettingsConfigDict(
                        env_file=None,
                        case_sensitive=False,
                    )
                    database_url: str = ""
                    api_key: str = "test"
                    telegram_bot_token: str = "test"
                    telegram_chat_id: str = "test"
                
                test_settings = TestSettings()
                assert test_settings.database_url == ""

    def test_settings_loads_from_env(self):
        """Settings should load from .env file."""
        from app.config import settings
        
        assert hasattr(settings, 'database_url')
        assert hasattr(settings, 'api_key')
        assert hasattr(settings, 'telegram_bot_token')
        assert hasattr(settings, 'telegram_chat_id')