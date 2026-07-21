from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from bot import config

pytestmark = pytest.mark.unit


class TestLoad:
    def test_loads_all_required_vars(self) -> None:
        env = {
            "TWITTER_BEARER_TOKEN": "bearer",
            "TWITTER_HANDLE": "handle",
            "BLUESKY_HANDLE": "bsky.social",
            "BLUESKY_PASSWORD": "pass",
        }
        with patch.dict(os.environ, env, clear=False):
            config.load()

        assert config.cfg.TWITTER_BEARER_TOKEN == "bearer"
        assert config.cfg.TWITTER_HANDLE == "handle"
        assert config.cfg.BLUESKY_HANDLE == "bsky.social"
        assert config.cfg.BLUESKY_PASSWORD == "pass"

    def test_exits_on_missing_required_var(self) -> None:
        env = {
            "TWITTER_BEARER_TOKEN": "bearer",
            # TWITTER_HANDLE missing
            "BLUESKY_HANDLE": "bsky.social",
            "BLUESKY_PASSWORD": "pass",
        }
        # Ensure the var is not set from a previous test
        clean_env = {k: v for k, v in env.items()}

        with patch.dict(os.environ, clean_env, clear=True):
            with pytest.raises(SystemExit):
                config.load()

    def test_exits_on_empty_required_var(self) -> None:
        env = {
            "TWITTER_BEARER_TOKEN": "",
            "TWITTER_HANDLE": "handle",
            "BLUESKY_HANDLE": "bsky.social",
            "BLUESKY_PASSWORD": "pass",
        }
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(SystemExit):
                config.load()

    def test_optional_session_loaded(self) -> None:
        env = {
            "TWITTER_BEARER_TOKEN": "bearer",
            "TWITTER_HANDLE": "handle",
            "BLUESKY_HANDLE": "bsky.social",
            "BLUESKY_PASSWORD": "pass",
            "BLUESKY_SESSION": "my-session",
        }
        with patch.dict(os.environ, env, clear=False):
            config.load()

        assert config.cfg.BLUESKY_SESSION == "my-session"

    def test_optional_session_defaults_empty(self) -> None:
        env = {
            "TWITTER_BEARER_TOKEN": "bearer",
            "TWITTER_HANDLE": "handle",
            "BLUESKY_HANDLE": "bsky.social",
            "BLUESKY_PASSWORD": "pass",
        }
        # Make sure BLUESKY_SESSION is not in the environment
        with patch.dict(os.environ, env, clear=True):
            config.load()

        assert config.cfg.BLUESKY_SESSION == ""

    def test_pin_sync_defaults_true(self) -> None:
        assert config.Config().PIN_SYNC_ENABLED is True

    def test_pin_sync_disabled_by_env(self) -> None:
        env = {
            "TWITTER_BEARER_TOKEN": "bearer",
            "TWITTER_HANDLE": "handle",
            "BLUESKY_HANDLE": "bsky.social",
            "BLUESKY_PASSWORD": "pass",
            "PIN_SYNC_ENABLED": "false",
        }
        with patch.dict(os.environ, env, clear=True):
            config.load()

        assert config.cfg.PIN_SYNC_ENABLED is False

    def test_pin_sync_enabled_by_env(self) -> None:
        env = {
            "TWITTER_BEARER_TOKEN": "bearer",
            "TWITTER_HANDLE": "handle",
            "BLUESKY_HANDLE": "bsky.social",
            "BLUESKY_PASSWORD": "pass",
            "PIN_SYNC_ENABLED": "1",
        }
        config.cfg.PIN_SYNC_ENABLED = False
        with patch.dict(os.environ, env, clear=True):
            config.load()

        assert config.cfg.PIN_SYNC_ENABLED is True

    def test_twitter_max_results_defaults_to_5(self) -> None:
        assert config.Config().TWITTER_MAX_RESULTS == 5

    def test_twitter_max_results_overridden_by_env(self) -> None:
        env = {
            "TWITTER_BEARER_TOKEN": "bearer",
            "TWITTER_HANDLE": "handle",
            "BLUESKY_HANDLE": "bsky.social",
            "BLUESKY_PASSWORD": "pass",
            "TWITTER_MAX_RESULTS": "10",
        }
        with patch.dict(os.environ, env, clear=True):
            config.load()

        assert config.cfg.TWITTER_MAX_RESULTS == 10
