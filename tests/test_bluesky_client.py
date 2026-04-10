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


class TestPrepareVideo:
    def test_no_video_returns_none(self) -> None:
        client = BlueskyClient()
        tweet = Tweet(id="1", text="no video")
        data, alt = client._prepare_video(tweet)
        assert data is None
        assert alt == ""

    def test_photo_only_returns_none(self) -> None:
        client = BlueskyClient()
        tweet = Tweet(
            id="1",
            text="photo only",
            media=[MediaItem(url="https://pbs.twimg.com/1.jpg", type="photo")],
        )
        data, alt = client._prepare_video(tweet)
        assert data is None

    def test_video_without_variants_returns_none(self) -> None:
        client = BlueskyClient()
        tweet = Tweet(
            id="1",
            text="video no variants",
            media=[MediaItem(url="https://pbs.twimg.com/thumb.jpg", type="video")],
        )
        data, alt = client._prepare_video(tweet)
        assert data is None

    @patch("bot.bluesky_client.download_video", return_value=b"\x00\x00video-bytes")
    @patch("bot.bluesky_client.select_best_variant", return_value={
        "content_type": "video/mp4",
        "bit_rate": 2176000,
        "url": "https://video.twimg.com/v/hi.mp4",
    })
    def test_returns_video_data_and_alt(self, mock_variant: MagicMock, mock_dl: MagicMock) -> None:
        client = BlueskyClient()
        tweet = Tweet(
            id="1",
            text="video tweet",
            media=[MediaItem(
                url="https://pbs.twimg.com/thumb.jpg",
                type="video",
                alt_text="Goal highlight",
                variants=[
                    {"content_type": "video/mp4", "bit_rate": 2176000, "url": "https://video.twimg.com/v/hi.mp4"},
                ],
            )],
        )
        data, alt = client._prepare_video(tweet)
        assert data == b"\x00\x00video-bytes"
        assert alt == "Goal highlight"
        mock_dl.assert_called_once_with("https://video.twimg.com/v/hi.mp4")

    @patch("bot.bluesky_client.download_video", side_effect=Exception("timeout"))
    @patch("bot.bluesky_client.select_best_variant", return_value={
        "content_type": "video/mp4",
        "url": "https://video.twimg.com/v/hi.mp4",
    })
    def test_returns_none_on_download_failure(self, mock_variant: MagicMock, mock_dl: MagicMock) -> None:
        client = BlueskyClient()
        tweet = Tweet(
            id="1",
            text="video fail",
            media=[MediaItem(
                url="https://pbs.twimg.com/thumb.jpg",
                type="video",
                variants=[{"content_type": "video/mp4", "url": "https://video.twimg.com/v/hi.mp4"}],
            )],
        )
        data, alt = client._prepare_video(tweet)
        assert data is None

    @patch("bot.bluesky_client.select_best_variant", return_value=None)
    def test_returns_none_when_no_mp4_variant(self, mock_variant: MagicMock) -> None:
        client = BlueskyClient()
        tweet = Tweet(
            id="1",
            text="video no mp4",
            media=[MediaItem(
                url="https://pbs.twimg.com/thumb.jpg",
                type="video",
                variants=[{"content_type": "application/x-mpegURL", "url": "https://video.twimg.com/v/playlist.m3u8"}],
            )],
        )
        data, alt = client._prepare_video(tweet)
        assert data is None

    @patch("bot.bluesky_client.download_video", return_value=b"\x00gif-bytes")
    @patch("bot.bluesky_client.select_best_variant", return_value={
        "content_type": "video/mp4",
        "bit_rate": 0,
        "url": "https://video.twimg.com/g/gif.mp4",
    })
    def test_animated_gif(self, mock_variant: MagicMock, mock_dl: MagicMock) -> None:
        client = BlueskyClient()
        tweet = Tweet(
            id="1",
            text="gif tweet",
            media=[MediaItem(
                url="https://pbs.twimg.com/thumb.jpg",
                type="animated_gif",
                variants=[{"content_type": "video/mp4", "bit_rate": 0, "url": "https://video.twimg.com/g/gif.mp4"}],
            )],
        )
        data, alt = client._prepare_video(tweet)
        assert data == b"\x00gif-bytes"


class TestPostVideo:
    @patch("bot.bluesky_client.download_video", return_value=b"\x00video")
    @patch("bot.bluesky_client.select_best_variant", return_value={
        "content_type": "video/mp4",
        "url": "https://video.twimg.com/v/hi.mp4",
    })
    @patch.object(BlueskyClient, "login")
    def test_video_uses_send_video(self, mock_login: MagicMock, mock_variant: MagicMock, mock_dl: MagicMock) -> None:
        client = BlueskyClient()
        client._client.send_video = MagicMock()
        client._client.send_post = MagicMock()

        tweet = Tweet(
            id="1",
            text="Goal!",
            media=[MediaItem(
                url="https://pbs.twimg.com/thumb.jpg",
                type="video",
                alt_text="Goal clip",
                variants=[{"content_type": "video/mp4", "url": "https://video.twimg.com/v/hi.mp4"}],
            )],
        )

        client.post(tweet)

        client._client.send_video.assert_called_once()
        call_kwargs = client._client.send_video.call_args
        assert call_kwargs.kwargs["video"] == b"\x00video"
        assert call_kwargs.kwargs["video_alt"] == "Goal clip"
        client._client.send_post.assert_not_called()

    @patch("bot.bluesky_client.download_video", side_effect=Exception("fail"))
    @patch("bot.bluesky_client.select_best_variant", return_value={
        "content_type": "video/mp4",
        "url": "https://video.twimg.com/v/hi.mp4",
    })
    @patch.object(BlueskyClient, "login")
    def test_download_failure_falls_back_to_text_post(
        self, mock_login: MagicMock, mock_variant: MagicMock, mock_dl: MagicMock
    ) -> None:
        client = BlueskyClient()
        client._client.send_video = MagicMock()
        client._client.send_post = MagicMock()

        tweet = Tweet(
            id="1",
            text="Video post",
            media=[MediaItem(
                url="https://pbs.twimg.com/thumb.jpg",
                type="video",
                variants=[{"content_type": "video/mp4", "url": "https://video.twimg.com/v/hi.mp4"}],
            )],
        )

        client.post(tweet)

        client._client.send_video.assert_not_called()
        client._client.send_post.assert_called_once()

    @patch("bot.bluesky_client.download_video", return_value=b"\x00video")
    @patch("bot.bluesky_client.select_best_variant", return_value={
        "content_type": "video/mp4",
        "url": "https://video.twimg.com/v/hi.mp4",
    })
    @patch.object(BlueskyClient, "login")
    def test_send_video_rejection_falls_back_to_text_post(
        self, mock_login: MagicMock, mock_variant: MagicMock, mock_dl: MagicMock
    ) -> None:
        """When Bluesky rejects the video (e.g. too long), fall back to send_post."""
        client = BlueskyClient()
        client._client.send_video = MagicMock(side_effect=Exception("video too long"))
        client._client.send_post = MagicMock()

        tweet = Tweet(
            id="1",
            text="Long video",
            media=[MediaItem(
                url="https://pbs.twimg.com/thumb.jpg",
                type="video",
                variants=[{"content_type": "video/mp4", "url": "https://video.twimg.com/v/hi.mp4"}],
            )],
        )

        client.post(tweet)

        client._client.send_video.assert_called_once()
        client._client.send_post.assert_called_once()

    @patch("bot.bluesky_client.fetch_og_metadata", return_value={
        "title": "Video on X",
        "description": "Watch the clip",
        "image": "",
    })
    @patch("bot.bluesky_client.download_video", return_value=b"\x00video")
    @patch("bot.bluesky_client.select_best_variant", return_value={
        "content_type": "video/mp4",
        "url": "https://video.twimg.com/v/hi.mp4",
    })
    @patch.object(BlueskyClient, "login")
    def test_send_video_rejection_produces_link_card(
        self, mock_login: MagicMock, mock_variant: MagicMock,
        mock_dl: MagicMock, mock_og: MagicMock
    ) -> None:
        """When send_video fails and tweet has a /video/ URL, produce a link card."""
        client = BlueskyClient()
        client._client.send_video = MagicMock(side_effect=Exception("rejected"))
        client._client.send_post = MagicMock()

        tweet = Tweet(
            id="1",
            text="Check this out",
            media=[MediaItem(
                url="https://pbs.twimg.com/thumb.jpg",
                type="video",
                variants=[{"content_type": "video/mp4", "url": "https://video.twimg.com/v/hi.mp4"}],
            )],
            urls=[{
                "url": "https://t.co/vid1",
                "expanded_url": "https://x.com/user/status/1/video/1",
                "display_url": "pic.x.com/vid1",
            }],
        )

        client.post(tweet)

        # send_post was called with an embed (link card)
        call_args = client._client.send_post.call_args
        embed = call_args.kwargs.get("embed") or call_args[1].get("embed")
        assert embed is not None
        assert embed.external.uri == "https://x.com/user/status/1/video/1"


class TestBuildLinkCardVideoFallback:
    def test_video_url_used_as_link_card(self) -> None:
        """A /video/ URL from twitter.com/x.com should be usable as a link card target."""
        client = BlueskyClient()
        tweet = Tweet(
            id="1",
            text="Video",
            media=[MediaItem(
                url="https://pbs.twimg.com/thumb.jpg",
                type="video",
                variants=[{"content_type": "video/mp4", "url": "https://video.twimg.com/v.mp4"}],
            )],
            urls=[{
                "url": "https://t.co/vid1",
                "expanded_url": "https://x.com/user/status/1/video/1",
                "display_url": "pic.x.com/vid1",
            }],
        )
        with patch("bot.bluesky_client.fetch_og_metadata", return_value={
            "title": "Video on X",
            "description": "",
            "image": "",
        }):
            card = client._build_link_card(tweet)

        assert card is not None
        assert card.external.uri == "https://x.com/user/status/1/video/1"

    def test_photo_url_still_filtered(self) -> None:
        """Verify /photo/ URLs are still filtered and not used as link cards."""
        client = BlueskyClient()
        tweet = Tweet(
            id="1",
            text="Photo",
            urls=[{
                "url": "https://t.co/img1",
                "expanded_url": "https://twitter.com/user/status/1/photo/1",
                "display_url": "pic.twitter.com/img1",
            }],
        )
        assert client._build_link_card(tweet) is None
