from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from atproto_client.models.blob_ref import BlobRef

from bot import config
from bot.bluesky_client import BlueskyClient
from bot.twitter_client import MediaItem, Tweet

pytestmark = pytest.mark.unit

_FAKE_BLOB = BlobRef(
    mime_type="image/jpeg",
    size=100,
    ref="bafyreie5cvv4h45feadgeuwhbcutmh6t7ceseocckahdoe6uat64zmz454",
)


@pytest.fixture(autouse=True)
def _set_config() -> None:
    config.BLUESKY_HANDLE = "test.bsky.social"
    config.BLUESKY_PASSWORD = "testpass"
    config.BLUESKY_SESSION = ""


class TestLogin:
    def test_password_login(self) -> None:
        client = BlueskyClient()
        with patch.object(client._client, "login") as mock_login:
            client.login()
            mock_login.assert_called_once_with("test.bsky.social", "testpass")
        assert client._logged_in

    def test_session_login(self) -> None:
        config.BLUESKY_SESSION = "session-string"
        client = BlueskyClient()
        with patch.object(client._client, "login") as mock_login:
            client.login()
            mock_login.assert_called_once_with(session_string="session-string")
        assert client._logged_in

    def test_session_fallback_to_password(self) -> None:
        config.BLUESKY_SESSION = "bad-session"
        client = BlueskyClient()

        call_count = 0
        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if "session_string" in kwargs:
                raise Exception("expired")
            # password login succeeds (called with positional args)

        with patch.object(client._client, "login", side_effect=side_effect):
            client.login()
        assert client._logged_in
        assert call_count == 2


class TestBuildImageEmbed:
    def test_no_photos_returns_none(self) -> None:
        client = BlueskyClient()
        tweet = Tweet(id="1", text="no media")
        assert client._build_image_embed(tweet) is None

    def test_video_only_returns_none(self) -> None:
        client = BlueskyClient()
        tweet = Tweet(
            id="1",
            text="video",
            media=[MediaItem(url="https://example.com/v.mp4", type="video")],
        )
        assert client._build_image_embed(tweet) is None

    @patch("bot.bluesky_client.download_image", return_value=b"\xff\xd8fake-jpg")
    def test_builds_embed_with_photos(self, mock_dl: MagicMock) -> None:
        client = BlueskyClient()
        blob_resp = SimpleNamespace(blob=_FAKE_BLOB)
        client._client.upload_blob = MagicMock(return_value=blob_resp)

        tweet = Tweet(
            id="1",
            text="photos",
            media=[
                MediaItem(url="https://pbs.twimg.com/1.jpg", type="photo", alt_text="pic one"),
                MediaItem(url="https://pbs.twimg.com/2.jpg", type="photo", alt_text="pic two"),
            ],
        )

        embed = client._build_image_embed(tweet)

        assert embed is not None
        assert len(embed.images) == 2
        assert embed.images[0].alt == "pic one"
        assert embed.images[1].alt == "pic two"
        assert mock_dl.call_count == 2

    @patch("bot.bluesky_client.download_image", return_value=b"\xff\xd8fake-jpg")
    def test_caps_at_four_images(self, mock_dl: MagicMock) -> None:
        client = BlueskyClient()
        blob_resp = SimpleNamespace(blob=_FAKE_BLOB)
        client._client.upload_blob = MagicMock(return_value=blob_resp)

        tweet = Tweet(
            id="1",
            text="many photos",
            media=[MediaItem(url=f"https://pbs.twimg.com/{i}.jpg", type="photo") for i in range(6)],
        )

        embed = client._build_image_embed(tweet)

        assert embed is not None
        assert len(embed.images) == 4

    @patch("bot.bluesky_client.download_image", side_effect=Exception("timeout"))
    def test_skips_failed_downloads(self, mock_dl: MagicMock) -> None:
        client = BlueskyClient()
        tweet = Tweet(
            id="1",
            text="broken",
            media=[MediaItem(url="https://pbs.twimg.com/1.jpg", type="photo")],
        )

        embed = client._build_image_embed(tweet)

        assert embed is None


class TestBuildLinkCard:
    def test_no_urls_returns_none(self) -> None:
        client = BlueskyClient()
        tweet = Tweet(id="1", text="no links")
        assert client._build_link_card(tweet) is None

    def test_skipped_when_photos_present(self) -> None:
        client = BlueskyClient()
        tweet = Tweet(
            id="1",
            text="photo + link",
            media=[MediaItem(url="https://pbs.twimg.com/1.jpg", type="photo")],
            urls=[{"url": "https://t.co/x", "expanded_url": "https://example.com", "display_url": "example.com"}],
        )
        assert client._build_link_card(tweet) is None

    def test_skips_twitter_photo_urls(self) -> None:
        client = BlueskyClient()
        tweet = Tweet(
            id="1",
            text="media url only",
            urls=[{
                "url": "https://t.co/x",
                "expanded_url": "https://twitter.com/user/status/1/photo/1",
                "display_url": "pic.twitter.com/x",
            }],
        )
        assert client._build_link_card(tweet) is None

    @patch("bot.bluesky_client.fetch_og_metadata", return_value={"title": "", "description": "", "image": ""})
    def test_no_og_title_returns_none(self, mock_og: MagicMock) -> None:
        client = BlueskyClient()
        tweet = Tweet(
            id="1",
            text="link",
            urls=[{"url": "https://t.co/x", "expanded_url": "https://example.com", "display_url": "example.com"}],
        )
        assert client._build_link_card(tweet) is None

    @patch("bot.bluesky_client.download_image", return_value=b"\x89PNGfake")
    @patch("bot.bluesky_client.fetch_og_metadata", return_value={
        "title": "Example Page",
        "description": "A description",
        "image": "https://example.com/og.png",
    })
    def test_builds_card_with_thumbnail(self, mock_og: MagicMock, mock_dl: MagicMock) -> None:
        client = BlueskyClient()
        blob_resp = SimpleNamespace(blob=_FAKE_BLOB)
        client._client.upload_blob = MagicMock(return_value=blob_resp)

        tweet = Tweet(
            id="1",
            text="Read this",
            urls=[{"url": "https://t.co/x", "expanded_url": "https://example.com/article", "display_url": "example.com/article"}],
        )

        card = client._build_link_card(tweet)

        assert card is not None
        assert card.external.uri == "https://example.com/article"
        assert card.external.title == "Example Page"
        assert card.external.description == "A description"
        assert card.external.thumb is not None

    @patch("bot.bluesky_client.fetch_og_metadata", return_value={
        "title": "No Image Page",
        "description": "desc",
        "image": "",
    })
    def test_builds_card_without_thumbnail(self, mock_og: MagicMock) -> None:
        client = BlueskyClient()
        tweet = Tweet(
            id="1",
            text="link",
            urls=[{"url": "https://t.co/x", "expanded_url": "https://example.com", "display_url": "example.com"}],
        )

        card = client._build_link_card(tweet)

        assert card is not None
        assert card.external.thumb is None


class TestPost:
    @patch("bot.bluesky_client.download_image", return_value=b"\xff\xd8jpg")
    @patch.object(BlueskyClient, "login")
    def test_auto_login_if_not_logged_in(self, mock_login: MagicMock, mock_dl: MagicMock) -> None:
        client = BlueskyClient()
        client._client.send_post = MagicMock()
        blob_resp = SimpleNamespace(blob=_FAKE_BLOB)
        client._client.upload_blob = MagicMock(return_value=blob_resp)

        tweet = Tweet(id="1", text="auto login test")

        client.post(tweet)

        mock_login.assert_called_once()
        client._client.send_post.assert_called_once()
