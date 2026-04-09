"""Integration tests that hit real external APIs.

These are gated behind the ``integration`` marker and skipped by default.
Run them explicitly with::

    pytest -m integration

They require real credentials in the environment:
    TWITTER_BEARER_TOKEN, TWITTER_HANDLE   — for Twitter read tests
    BLUESKY_HANDLE, BLUESKY_PASSWORD       — for Bluesky write tests
"""
from __future__ import annotations

import os

import pytest

from bot import config

# ---------------------------------------------------------------------------
# Skip the entire module if credentials are absent
# ---------------------------------------------------------------------------
_has_twitter_creds = bool(
    os.environ.get("TWITTER_BEARER_TOKEN") and os.environ.get("TWITTER_HANDLE")
)
_has_bluesky_creds = bool(
    os.environ.get("BLUESKY_HANDLE") and os.environ.get("BLUESKY_PASSWORD")
)


@pytest.mark.integration
class TestTwitterIntegration:
    """Read-only smoke tests against the live Twitter API."""

    pytestmark = pytest.mark.skipif(
        not _has_twitter_creds,
        reason="TWITTER_BEARER_TOKEN and TWITTER_HANDLE not set",
    )

    @pytest.fixture(autouse=True)
    def _load_config(self) -> None:
        config.load()

    def test_fetch_recent_tweets(self) -> None:
        from bot.twitter_client import TwitterClient

        client = TwitterClient()
        tweets = client.fetch_recent_tweets(max_results=5)

        # We can't guarantee the account has tweets, but the call should
        # succeed without error and return a list.
        assert isinstance(tweets, list)
        for t in tweets:
            assert t.id
            assert t.text


@pytest.mark.integration
class TestBlueskyIntegration:
    """Smoke tests against the live Bluesky API.

    Currently limited to login verification — no posts are created.
    """

    pytestmark = pytest.mark.skipif(
        not _has_bluesky_creds,
        reason="BLUESKY_HANDLE and BLUESKY_PASSWORD not set",
    )

    @pytest.fixture(autouse=True)
    def _load_config(self) -> None:
        config.load()

    def test_login_succeeds(self) -> None:
        from bot.bluesky_client import BlueskyClient

        client = BlueskyClient()
        client.login()

        assert client._logged_in

    def test_export_session(self) -> None:
        from bot.bluesky_client import BlueskyClient

        client = BlueskyClient()
        client.login()
        session = client.export_session()

        assert isinstance(session, str)
        assert len(session) > 0
