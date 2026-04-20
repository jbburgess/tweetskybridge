from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from atproto_client.exceptions import BadRequestError, InvokeTimeoutError, RequestException
from atproto_client.models.blob_ref import BlobRef

from bot import config
from bot.bluesky_client import BlueskyClient, BlueskyPostRef
from bot.models import MediaItem, Tweet

pytestmark = pytest.mark.unit

_FAKE_BLOB = BlobRef(
    mime_type="image/jpeg",
    size=100,
    ref="bafyreie5cvv4h45feadgeuwhbcutmh6t7ceseocckahdoe6uat64zmz454",
)


@pytest.fixture(autouse=True)
def _set_config() -> None:
    config.cfg.BLUESKY_HANDLE = "test.bsky.social"
    config.cfg.BLUESKY_PASSWORD = "testpass"
    config.cfg.BLUESKY_SESSION = ""


class TestLogin:
    def test_password_login(self) -> None:
        client = BlueskyClient()
        with patch.object(client._client, "login") as mock_login:
            client.login()
            mock_login.assert_called_once_with("test.bsky.social", "testpass")
        assert client._logged_in

    def test_session_login(self) -> None:
        config.cfg.BLUESKY_SESSION = "session-string"
        client = BlueskyClient()
        with patch.object(client._client, "login") as mock_login:
            client.login()
            mock_login.assert_called_once_with(session_string="session-string")
        assert client._logged_in

    def test_session_fallback_to_password(self) -> None:
        config.cfg.BLUESKY_SESSION = "bad-session"
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

    def test_retries_on_transient_503(self) -> None:
        client = BlueskyClient()
        resp_503 = SimpleNamespace(
            success=False, status_code=503, content=None, headers={},
        )
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RequestException(resp_503)
            # second attempt succeeds

        with (
            patch.object(client._client, "login", side_effect=side_effect),
            patch("bot.bluesky_client.time.sleep") as mock_sleep,
        ):
            client.login()
        assert client._logged_in
        assert call_count == 2
        mock_sleep.assert_called_once_with(5)

    def test_raises_after_max_retries(self) -> None:
        client = BlueskyClient()
        resp_503 = SimpleNamespace(
            success=False, status_code=503, content=None, headers={},
        )

        with (
            patch.object(
                client._client, "login",
                side_effect=RequestException(resp_503),
            ),
            patch("bot.bluesky_client.time.sleep"),
            pytest.raises(RequestException),
        ):
            client.login()

    def test_no_retry_on_client_error(self) -> None:
        client = BlueskyClient()
        resp_401 = SimpleNamespace(
            success=False, status_code=401, content=None, headers={},
        )

        with (
            patch.object(
                client._client, "login",
                side_effect=RequestException(resp_401),
            ),
            patch("bot.bluesky_client.time.sleep") as mock_sleep,
            pytest.raises(RequestException),
        ):
            client.login()
        mock_sleep.assert_not_called()

    def test_retries_on_timeout(self) -> None:
        client = BlueskyClient()
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise InvokeTimeoutError()
            # second attempt succeeds

        with (
            patch.object(client._client, "login", side_effect=side_effect),
            patch("bot.bluesky_client.time.sleep") as mock_sleep,
        ):
            client.login()
        assert client._logged_in
        assert call_count == 2
        mock_sleep.assert_called_once_with(5)

    def test_timeout_raises_after_max_retries(self) -> None:
        client = BlueskyClient()

        with (
            patch.object(
                client._client, "login",
                side_effect=InvokeTimeoutError(),
            ),
            patch("bot.bluesky_client.time.sleep"),
            pytest.raises(InvokeTimeoutError),
        ):
            client.login()

    def test_retries_on_bad_request(self) -> None:
        client = BlueskyClient()
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise BadRequestError()
            # second attempt succeeds

        with (
            patch.object(client._client, "login", side_effect=side_effect),
            patch("bot.bluesky_client.time.sleep") as mock_sleep,
        ):
            client.login()
        assert client._logged_in
        assert call_count == 2
        mock_sleep.assert_called_once_with(5)

    def test_bad_request_raises_after_max_retries(self) -> None:
        client = BlueskyClient()

        with (
            patch.object(
                client._client, "login",
                side_effect=BadRequestError(),
            ),
            patch("bot.bluesky_client.time.sleep"),
            pytest.raises(BadRequestError),
        ):
            client.login()


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


    @patch("bot.bluesky_client.get_image_dimensions", return_value=(1280, 720))
    @patch("bot.bluesky_client.download_image", return_value=b"\xff\xd8fake-jpg")
    def test_single_image_gets_aspect_ratio(self, mock_dl: MagicMock, mock_dims: MagicMock) -> None:
        client = BlueskyClient()
        blob_resp = SimpleNamespace(blob=_FAKE_BLOB)
        client._client.upload_blob = MagicMock(return_value=blob_resp)

        tweet = Tweet(
            id="1",
            text="photo",
            media=[MediaItem(url="https://pbs.twimg.com/1.jpg", type="photo", alt_text="test")],
        )

        embed = client._build_image_embed(tweet)

        assert embed is not None
        assert embed.images[0].aspect_ratio is not None
        assert embed.images[0].aspect_ratio.width == 1280
        assert embed.images[0].aspect_ratio.height == 720

    @patch("bot.bluesky_client.get_image_dimensions", return_value=(0, 0))
    @patch("bot.bluesky_client.download_image", return_value=b"\xff\xd8fake-jpg")
    def test_image_without_known_dimensions_has_no_aspect_ratio(self, mock_dl: MagicMock, mock_dims: MagicMock) -> None:
        client = BlueskyClient()
        blob_resp = SimpleNamespace(blob=_FAKE_BLOB)
        client._client.upload_blob = MagicMock(return_value=blob_resp)

        tweet = Tweet(
            id="1",
            text="photo",
            media=[MediaItem(url="https://pbs.twimg.com/1.jpg", type="photo", alt_text="test")],
        )

        embed = client._build_image_embed(tweet)

        assert embed is not None
        assert embed.images[0].aspect_ratio is None


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


class TestBuildQuoteEmbedCard:
    def test_builds_card_with_username_and_description(self) -> None:
        client = BlueskyClient()
        quoted = Tweet(
            id="999",
            text="3 goals for @SJEarthquakes!",
        )
        tweet = Tweet(
            id="1000",
            text="bringing home",
            urls=[{
                "url": "https://t.co/abc",
                "expanded_url": "https://twitter.com/MLS/status/999",
                "display_url": "twitter.com/MLS/status/999",
            }],
            quoted_tweet=quoted,
        )

        card = client._build_quote_embed_card(tweet)

        assert card is not None
        assert card.external.uri == "https://twitter.com/MLS/status/999"
        assert card.external.title == "@MLS"
        assert card.external.description == "3 goals for @SJEarthquakes!"
        assert card.external.thumb is None

    @patch("bot.bluesky_client.download_image", return_value=b"\xff\xd8fake-jpg")
    def test_builds_card_with_thumbnail_from_quoted_media(self, mock_dl: MagicMock) -> None:
        client = BlueskyClient()
        blob_resp = SimpleNamespace(blob=_FAKE_BLOB)
        client._client.upload_blob = MagicMock(return_value=blob_resp)

        quoted = Tweet(
            id="999",
            text="Big win tonight!",
            media=[MediaItem(url="https://pbs.twimg.com/media/quoted.jpg", type="photo")],
        )
        tweet = Tweet(
            id="1000",
            text="amazing",
            urls=[{
                "url": "https://t.co/abc",
                "expanded_url": "https://twitter.com/MLS/status/999",
                "display_url": "twitter.com/MLS/status/999",
            }],
            quoted_tweet=quoted,
        )

        card = client._build_quote_embed_card(tweet)

        assert card is not None
        assert card.external.thumb is not None
        mock_dl.assert_called_once_with("https://pbs.twimg.com/media/quoted.jpg")

    def test_returns_none_when_no_matching_url(self) -> None:
        """If the quoted tweet's status URL isn't in tweet.urls, return None."""
        client = BlueskyClient()
        quoted = Tweet(id="999", text="something")
        tweet = Tweet(
            id="1000",
            text="quoting",
            urls=[],
            quoted_tweet=quoted,
        )

        assert client._build_quote_embed_card(tweet) is None

    def test_link_card_delegates_to_quote_embed_card(self) -> None:
        """_build_link_card routes to _build_quote_embed_card for quote tweets."""
        client = BlueskyClient()
        quoted = Tweet(id="999", text="quoted text")
        tweet = Tweet(
            id="1000",
            text="quoting",
            urls=[{
                "url": "https://t.co/abc",
                "expanded_url": "https://twitter.com/MLS/status/999",
                "display_url": "twitter.com/MLS/status/999",
            }],
            quoted_tweet=quoted,
        )

        card = client._build_link_card(tweet)

        assert card is not None
        assert card.external.uri == "https://twitter.com/MLS/status/999"
        assert card.external.title == "@MLS"


class TestPost:
    @patch("bot.bluesky_client.download_image", return_value=b"\xff\xd8jpg")
    @patch.object(BlueskyClient, "login")
    def test_auto_login_if_not_logged_in(self, mock_login: MagicMock, mock_dl: MagicMock) -> None:
        client = BlueskyClient()
        client._client.send_post = MagicMock(return_value=SimpleNamespace(uri="at://did/post/1", cid="cid1"))
        blob_resp = SimpleNamespace(blob=_FAKE_BLOB)
        client._client.upload_blob = MagicMock(return_value=blob_resp)

        tweet = Tweet(id="1", text="auto login test")

        client.post(tweet)

        mock_login.assert_called_once()
        client._client.send_post.assert_called_once()

    @patch.object(BlueskyClient, "login")
    def test_post_returns_bluesky_post_ref(self, mock_login: MagicMock) -> None:
        client = BlueskyClient()
        client._logged_in = True
        client._client.send_post = MagicMock(
            return_value=SimpleNamespace(uri="at://did/post/42", cid="bafycid42")
        )

        result = client.post(Tweet(id="1", text="hello"))

        assert isinstance(result, BlueskyPostRef)
        assert result.uri == "at://did/post/42"
        assert result.cid == "bafycid42"

    @patch.object(BlueskyClient, "login")
    def test_reply_passes_reply_to_send_post(self, mock_login: MagicMock) -> None:
        client = BlueskyClient()
        client._logged_in = True
        client._client.send_post = MagicMock(
            return_value=SimpleNamespace(uri="at://did/post/2", cid="bafycid2")
        )

        parent = BlueskyPostRef(uri="at://did/post/1", cid="bafycid1")
        client.post(Tweet(id="2", text="reply"), parent_ref=parent)

        _, kwargs = client._client.send_post.call_args
        reply = kwargs.get("reply_to")
        assert reply is not None
        assert reply.parent.uri == "at://did/post/1"
        assert reply.root.uri == "at://did/post/1"  # root defaults to parent for 2-tweet threads

    @patch.object(BlueskyClient, "login")
    def test_reply_uses_explicit_root_ref(self, mock_login: MagicMock) -> None:
        client = BlueskyClient()
        client._logged_in = True
        client._client.send_post = MagicMock(
            return_value=SimpleNamespace(uri="at://did/post/3", cid="bafycid3")
        )

        parent = BlueskyPostRef(uri="at://did/post/2", cid="bafycid2")
        root = BlueskyPostRef(uri="at://did/post/1", cid="bafycid1")
        client.post(Tweet(id="3", text="reply to reply"), parent_ref=parent, root_ref=root)

        _, kwargs = client._client.send_post.call_args
        reply = kwargs.get("reply_to")
        assert reply.parent.uri == "at://did/post/2"
        assert reply.root.uri == "at://did/post/1"

    @patch.object(BlueskyClient, "login")
    def test_standalone_post_has_no_reply_ref(self, mock_login: MagicMock) -> None:
        client = BlueskyClient()
        client._logged_in = True
        client._client.send_post = MagicMock(
            return_value=SimpleNamespace(uri="at://did/post/1", cid="bafycid1")
        )

        client.post(Tweet(id="1", text="standalone"))

        _, kwargs = client._client.send_post.call_args
        assert kwargs.get("reply_to") is None


class TestPrepareVideo:
    def test_no_video_returns_none(self) -> None:
        client = BlueskyClient()
        tweet = Tweet(id="1", text="no video")
        data, alt, w, h = client._prepare_video(tweet)
        assert data is None
        assert alt == ""
        assert w == 0
        assert h == 0

    def test_photo_only_returns_none(self) -> None:
        client = BlueskyClient()
        tweet = Tweet(
            id="1",
            text="photo only",
            media=[MediaItem(url="https://pbs.twimg.com/1.jpg", type="photo")],
        )
        data, alt, w, h = client._prepare_video(tweet)
        assert data is None

    def test_video_without_variants_returns_none(self) -> None:
        client = BlueskyClient()
        tweet = Tweet(
            id="1",
            text="video no variants",
            media=[MediaItem(url="https://pbs.twimg.com/thumb.jpg", type="video")],
        )
        data, alt, w, h = client._prepare_video(tweet)
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
        with patch("bot.bluesky_client.get_video_dimensions", return_value=(0, 0)):
            data, alt, w, h = client._prepare_video(tweet)
        assert data == b"\x00\x00video-bytes"
        assert alt == "Goal highlight"
        assert w == 0
        assert h == 0
        mock_dl.assert_called_once_with("https://video.twimg.com/v/hi.mp4")

    @patch("bot.bluesky_client.download_video", return_value=b"\x00\x00video-bytes")
    @patch("bot.bluesky_client.select_best_variant", return_value={
        "content_type": "video/mp4",
        "bit_rate": 2176000,
        "url": "https://video.twimg.com/v/hi.mp4",
    })
    def test_falls_back_to_byte_parsing_when_api_has_no_dimensions(
        self, mock_variant: MagicMock, mock_dl: MagicMock
    ) -> None:
        client = BlueskyClient()
        tweet = Tweet(
            id="1",
            text="video tweet",
            media=[MediaItem(
                url="https://pbs.twimg.com/thumb.jpg",
                type="video",
                # No width/height from Twitter API (the common case for video)
                variants=[{"content_type": "video/mp4", "bit_rate": 2176000, "url": "https://video.twimg.com/v/hi.mp4"}],
            )],
        )
        with patch("bot.bluesky_client.get_video_dimensions", return_value=(1080, 1920)) as mock_gvd:
            data, alt, w, h = client._prepare_video(tweet)
            mock_gvd.assert_called_once_with(b"\x00\x00video-bytes")
        assert w == 1080
        assert h == 1920

    @patch("bot.bluesky_client.download_video", return_value=b"\x00\x00video-bytes")
    @patch("bot.bluesky_client.select_best_variant", return_value={
        "content_type": "video/mp4",
        "bit_rate": 2176000,
        "url": "https://video.twimg.com/v/hi.mp4",
    })
    def test_returns_video_dimensions_from_media_item(self, mock_variant: MagicMock, mock_dl: MagicMock) -> None:
        client = BlueskyClient()
        tweet = Tweet(
            id="1",
            text="video tweet",
            media=[MediaItem(
                url="https://pbs.twimg.com/thumb.jpg",
                type="video",
                alt_text="Goal highlight",
                width=1920,
                height=1080,
                variants=[
                    {"content_type": "video/mp4", "bit_rate": 2176000, "url": "https://video.twimg.com/v/hi.mp4"},
                ],
            )],
        )
        data, alt, w, h = client._prepare_video(tweet)
        assert data == b"\x00\x00video-bytes"
        assert w == 1920
        assert h == 1080

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
        data, alt, w, h = client._prepare_video(tweet)
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
        data, alt, w, h = client._prepare_video(tweet)
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
        data, alt, w, h = client._prepare_video(tweet)
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
        assert call_kwargs.kwargs.get("video_aspect_ratio") is None
        client._client.send_post.assert_not_called()

    @patch("bot.bluesky_client.download_video", return_value=b"\x00video")
    @patch("bot.bluesky_client.select_best_variant", return_value={
        "content_type": "video/mp4",
        "url": "https://video.twimg.com/v/hi.mp4",
    })
    @patch.object(BlueskyClient, "login")
    def test_video_with_dimensions_gets_aspect_ratio(
        self, mock_login: MagicMock, mock_variant: MagicMock, mock_dl: MagicMock
    ) -> None:
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
                width=1920,
                height=1080,
                variants=[{"content_type": "video/mp4", "url": "https://video.twimg.com/v/hi.mp4"}],
            )],
        )

        client.post(tweet)

        call_kwargs = client._client.send_video.call_args
        ar = call_kwargs.kwargs.get("video_aspect_ratio")
        assert ar is not None
        assert ar.width == 1920
        assert ar.height == 1080

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


class TestMultiPartPost:
    """Tests for the (k/n) thread-splitting behaviour on long tweets."""

    # 62 words × 5 chars + 61 spaces = 371 graphemes — reliably over the 300 limit.
    _LONG_TEXT = " ".join(["hello"] * 62)

    def _make_client(self) -> BlueskyClient:
        client = BlueskyClient()
        client._logged_in = True
        call_count = 0

        def fake_send_post(tb, *, embed=None, reply_to=None):
            nonlocal call_count
            call_count += 1
            return SimpleNamespace(uri=f"at://did/post/{call_count}", cid=f"cid{call_count}")

        client._client.send_post = MagicMock(side_effect=fake_send_post)
        client._prepare_video = MagicMock(return_value=(None, "", 0, 0))
        client._build_image_embed = MagicMock(return_value=None)
        client._build_link_card = MagicMock(return_value=None)
        return client

    def test_long_tweet_sends_multiple_posts(self) -> None:
        client = self._make_client()
        tweet = Tweet(id="1", text=self._LONG_TEXT)
        client.post(tweet)
        assert client._client.send_post.call_count >= 2

    def test_returns_last_ref(self) -> None:
        client = self._make_client()
        tweet = Tweet(id="1", text=self._LONG_TEXT)
        result = client.post(tweet)
        n = client._client.send_post.call_count
        assert result.uri == f"at://did/post/{n}"
        assert result.cid == f"cid{n}"

    def test_first_chunk_has_no_reply(self) -> None:
        client = self._make_client()
        tweet = Tweet(id="1", text=self._LONG_TEXT)
        client.post(tweet)
        _, first_kwargs = client._client.send_post.call_args_list[0]
        assert first_kwargs.get("reply_to") is None

    def test_second_chunk_replies_to_first(self) -> None:
        client = self._make_client()
        tweet = Tweet(id="1", text=self._LONG_TEXT)
        client.post(tweet)
        _, second_kwargs = client._client.send_post.call_args_list[1]
        reply = second_kwargs.get("reply_to")
        assert reply is not None
        assert reply.parent.uri == "at://did/post/1"
        assert reply.root.uri == "at://did/post/1"

    def test_embed_only_on_first_chunk(self) -> None:
        client = self._make_client()
        fake_embed = object()
        client._build_image_embed = MagicMock(return_value=fake_embed)
        tweet = Tweet(id="1", text=self._LONG_TEXT)
        client.post(tweet)
        calls = client._client.send_post.call_args_list
        _, first_kwargs = calls[0]
        assert first_kwargs.get("embed") is fake_embed
        for call in calls[1:]:
            _, kwargs = call
            assert kwargs.get("embed") is None

    def test_short_tweet_single_post_no_suffix(self) -> None:
        """Single-post tweets are unaffected — no (1/1) suffix added."""
        client = self._make_client()
        tweet = Tweet(id="1", text="Short tweet")
        client.post(tweet)
        assert client._client.send_post.call_count == 1
        args, _ = client._client.send_post.call_args
        tb = args[0]
        assert "(1/1)" not in tb.build_text()

    @patch.object(BlueskyClient, "login")
    def test_first_chunk_inherits_caller_parent_ref(self, mock_login: MagicMock) -> None:
        """When the source tweet is a reply, the first split chunk replies to the caller's parent."""
        client = BlueskyClient()
        client._logged_in = True
        call_count = 0

        def fake_send_post(tb, *, embed=None, reply_to=None):
            nonlocal call_count
            call_count += 1
            return SimpleNamespace(uri=f"at://did/post/{call_count}", cid=f"cid{call_count}")

        client._client.send_post = MagicMock(side_effect=fake_send_post)

        parent = BlueskyPostRef(uri="at://did/post/0", cid="cid0")
        tweet = Tweet(id="2", text=self._LONG_TEXT)
        client.post(tweet, parent_ref=parent)

        _, first_kwargs = client._client.send_post.call_args_list[0]
        reply = first_kwargs.get("reply_to")
        assert reply is not None
        assert reply.parent.uri == "at://did/post/0"


class TestHasMixedMedia:
    def test_photo_and_video(self) -> None:
        tweet = Tweet(
            id="1",
            text="mixed",
            media=[
                MediaItem(url="https://pbs.twimg.com/1.jpg", type="photo"),
                MediaItem(
                    url="https://pbs.twimg.com/thumb.jpg",
                    type="video",
                    variants=[{"content_type": "video/mp4", "url": "https://video.twimg.com/v.mp4"}],
                ),
            ],
        )
        assert BlueskyClient._has_mixed_media(tweet) is True

    def test_photo_and_animated_gif(self) -> None:
        tweet = Tweet(
            id="1",
            text="mixed gif",
            media=[
                MediaItem(url="https://pbs.twimg.com/1.jpg", type="photo"),
                MediaItem(
                    url="https://pbs.twimg.com/thumb.jpg",
                    type="animated_gif",
                    variants=[{"content_type": "video/mp4", "url": "https://video.twimg.com/g.mp4"}],
                ),
            ],
        )
        assert BlueskyClient._has_mixed_media(tweet) is True

    def test_photo_only(self) -> None:
        tweet = Tweet(
            id="1",
            text="photos",
            media=[MediaItem(url="https://pbs.twimg.com/1.jpg", type="photo")],
        )
        assert BlueskyClient._has_mixed_media(tweet) is False

    def test_video_only(self) -> None:
        tweet = Tweet(
            id="1",
            text="video",
            media=[MediaItem(
                url="https://pbs.twimg.com/thumb.jpg",
                type="video",
                variants=[{"content_type": "video/mp4", "url": "https://video.twimg.com/v.mp4"}],
            )],
        )
        assert BlueskyClient._has_mixed_media(tweet) is False

    def test_no_media(self) -> None:
        tweet = Tweet(id="1", text="text only")
        assert BlueskyClient._has_mixed_media(tweet) is False

    def test_video_without_variants_not_mixed(self) -> None:
        """A video with no downloadable variants doesn't count."""
        tweet = Tweet(
            id="1",
            text="mixed?",
            media=[
                MediaItem(url="https://pbs.twimg.com/1.jpg", type="photo"),
                MediaItem(url="https://pbs.twimg.com/thumb.jpg", type="video", variants=[]),
            ],
        )
        assert BlueskyClient._has_mixed_media(tweet) is False


class TestMixedMediaPost:
    """Tests for mixed-media tweets: images on main post, videos as replies."""

    @patch("bot.bluesky_client.download_video", return_value=b"\x00video")
    @patch("bot.bluesky_client.select_best_variant", return_value={
        "content_type": "video/mp4",
        "url": "https://video.twimg.com/v/hi.mp4",
    })
    @patch("bot.bluesky_client.download_image", return_value=b"\xff\xd8fake-jpg")
    @patch.object(BlueskyClient, "login")
    def test_images_on_main_post_video_as_reply(
        self, mock_login: MagicMock, mock_dl_img: MagicMock,
        mock_variant: MagicMock, mock_dl_vid: MagicMock,
    ) -> None:
        client = BlueskyClient()
        client._logged_in = True
        blob_resp = SimpleNamespace(blob=_FAKE_BLOB)
        client._client.upload_blob = MagicMock(return_value=blob_resp)

        post_count = 0

        def fake_send_post(tb, *, embed=None, reply_to=None):
            nonlocal post_count
            post_count += 1
            return SimpleNamespace(uri=f"at://did/post/{post_count}", cid=f"cid{post_count}")

        client._client.send_post = MagicMock(side_effect=fake_send_post)

        video_count = 0

        def fake_send_video(*, text, video, video_alt, video_aspect_ratio=None, reply_to=None):
            nonlocal video_count
            video_count += 1
            return SimpleNamespace(uri=f"at://did/video/{video_count}", cid=f"vidcid{video_count}")

        client._client.send_video = MagicMock(side_effect=fake_send_video)

        tweet = Tweet(
            id="1",
            text="Photos and video",
            media=[
                MediaItem(url="https://pbs.twimg.com/1.jpg", type="photo", alt_text="pic"),
                MediaItem(
                    url="https://pbs.twimg.com/thumb.jpg",
                    type="video",
                    alt_text="clip",
                    variants=[{"content_type": "video/mp4", "url": "https://video.twimg.com/v/hi.mp4"}],
                ),
            ],
        )

        result = client.post(tweet)

        # Main post used send_post with an image embed
        client._client.send_post.assert_called_once()
        _, post_kwargs = client._client.send_post.call_args
        assert post_kwargs["embed"] is not None  # image embed
        assert post_kwargs["reply_to"] is None  # standalone

        # Video posted as reply
        client._client.send_video.assert_called_once()
        vid_kwargs = client._client.send_video.call_args.kwargs
        assert vid_kwargs["video"] == b"\x00video"
        assert vid_kwargs["video_alt"] == "clip"
        assert vid_kwargs["text"] == ""
        assert vid_kwargs["reply_to"] is not None
        assert vid_kwargs["reply_to"].parent.uri == "at://did/post/1"

        # Return value is the video reply ref
        assert result.uri == "at://did/video/1"

    @patch("bot.bluesky_client.download_video", return_value=b"\x00video")
    @patch("bot.bluesky_client.select_best_variant", return_value={
        "content_type": "video/mp4",
        "url": "https://video.twimg.com/v/hi.mp4",
    })
    @patch("bot.bluesky_client.download_image", return_value=b"\xff\xd8fake-jpg")
    @patch.object(BlueskyClient, "login")
    def test_multiple_videos_chained_as_replies(
        self, mock_login: MagicMock, mock_dl_img: MagicMock,
        mock_variant: MagicMock, mock_dl_vid: MagicMock,
    ) -> None:
        client = BlueskyClient()
        client._logged_in = True
        blob_resp = SimpleNamespace(blob=_FAKE_BLOB)
        client._client.upload_blob = MagicMock(return_value=blob_resp)

        post_count = 0

        def fake_send_post(tb, *, embed=None, reply_to=None):
            nonlocal post_count
            post_count += 1
            return SimpleNamespace(uri=f"at://did/post/{post_count}", cid=f"cid{post_count}")

        client._client.send_post = MagicMock(side_effect=fake_send_post)

        video_count = 0

        def fake_send_video(*, text, video, video_alt, video_aspect_ratio=None, reply_to=None):
            nonlocal video_count
            video_count += 1
            return SimpleNamespace(uri=f"at://did/video/{video_count}", cid=f"vidcid{video_count}")

        client._client.send_video = MagicMock(side_effect=fake_send_video)

        tweet = Tweet(
            id="1",
            text="Multi video",
            media=[
                MediaItem(url="https://pbs.twimg.com/1.jpg", type="photo"),
                MediaItem(
                    url="https://pbs.twimg.com/thumb1.jpg",
                    type="video",
                    variants=[{"content_type": "video/mp4", "url": "https://video.twimg.com/v/1.mp4"}],
                ),
                MediaItem(
                    url="https://pbs.twimg.com/thumb2.jpg",
                    type="video",
                    variants=[{"content_type": "video/mp4", "url": "https://video.twimg.com/v/2.mp4"}],
                ),
            ],
        )

        result = client.post(tweet)

        assert client._client.send_video.call_count == 2

        # First video reply chains off the main post
        first_vid = client._client.send_video.call_args_list[0].kwargs
        assert first_vid["reply_to"].parent.uri == "at://did/post/1"
        assert first_vid["reply_to"].root.uri == "at://did/post/1"

        # Second video reply chains off the first video reply
        second_vid = client._client.send_video.call_args_list[1].kwargs
        assert second_vid["reply_to"].parent.uri == "at://did/video/1"
        assert second_vid["reply_to"].root.uri == "at://did/post/1"

        # Return value is the last video reply
        assert result.uri == "at://did/video/2"

    @patch("bot.bluesky_client.download_video", side_effect=Exception("timeout"))
    @patch("bot.bluesky_client.select_best_variant", return_value={
        "content_type": "video/mp4",
        "url": "https://video.twimg.com/v/hi.mp4",
    })
    @patch("bot.bluesky_client.download_image", return_value=b"\xff\xd8fake-jpg")
    @patch.object(BlueskyClient, "login")
    def test_video_download_failure_still_posts_images(
        self, mock_login: MagicMock, mock_dl_img: MagicMock,
        mock_variant: MagicMock, mock_dl_vid: MagicMock,
    ) -> None:
        client = BlueskyClient()
        client._logged_in = True
        blob_resp = SimpleNamespace(blob=_FAKE_BLOB)
        client._client.upload_blob = MagicMock(return_value=blob_resp)
        client._client.send_post = MagicMock(
            return_value=SimpleNamespace(uri="at://did/post/1", cid="cid1")
        )
        client._client.send_video = MagicMock()

        tweet = Tweet(
            id="1",
            text="Mixed but video fails",
            media=[
                MediaItem(url="https://pbs.twimg.com/1.jpg", type="photo"),
                MediaItem(
                    url="https://pbs.twimg.com/thumb.jpg",
                    type="video",
                    variants=[{"content_type": "video/mp4", "url": "https://video.twimg.com/v/hi.mp4"}],
                ),
            ],
        )

        result = client.post(tweet)

        # Main post still succeeded with images
        client._client.send_post.assert_called_once()
        # Video reply was never attempted (download failed in _prepare_single_video)
        client._client.send_video.assert_not_called()
        # Returned the main post ref
        assert result.uri == "at://did/post/1"

    @patch("bot.bluesky_client.download_video", return_value=b"\x00video")
    @patch("bot.bluesky_client.select_best_variant", return_value={
        "content_type": "video/mp4",
        "url": "https://video.twimg.com/v/hi.mp4",
    })
    @patch("bot.bluesky_client.download_image", return_value=b"\xff\xd8fake-jpg")
    @patch.object(BlueskyClient, "login")
    def test_send_video_rejection_continues(
        self, mock_login: MagicMock, mock_dl_img: MagicMock,
        mock_variant: MagicMock, mock_dl_vid: MagicMock,
    ) -> None:
        """When send_video fails for a mixed-media reply, it is skipped gracefully."""
        client = BlueskyClient()
        client._logged_in = True
        blob_resp = SimpleNamespace(blob=_FAKE_BLOB)
        client._client.upload_blob = MagicMock(return_value=blob_resp)
        client._client.send_post = MagicMock(
            return_value=SimpleNamespace(uri="at://did/post/1", cid="cid1")
        )
        client._client.send_video = MagicMock(side_effect=Exception("rejected"))

        tweet = Tweet(
            id="1",
            text="Mixed media",
            media=[
                MediaItem(url="https://pbs.twimg.com/1.jpg", type="photo"),
                MediaItem(
                    url="https://pbs.twimg.com/thumb.jpg",
                    type="video",
                    variants=[{"content_type": "video/mp4", "url": "https://video.twimg.com/v/hi.mp4"}],
                ),
            ],
        )

        result = client.post(tweet)

        # Main post succeeded
        client._client.send_post.assert_called_once()
        # Video reply was attempted but failed
        client._client.send_video.assert_called_once()
        # Returned the main post ref (video failed)
        assert result.uri == "at://did/post/1"

    @patch("bot.bluesky_client.download_video", return_value=b"\x00video")
    @patch("bot.bluesky_client.select_best_variant", return_value={
        "content_type": "video/mp4",
        "url": "https://video.twimg.com/v/hi.mp4",
    })
    @patch("bot.bluesky_client.download_image", return_value=b"\xff\xd8fake-jpg")
    @patch.object(BlueskyClient, "login")
    def test_video_only_tweet_unchanged(
        self, mock_login: MagicMock, mock_dl_img: MagicMock,
        mock_variant: MagicMock, mock_dl_vid: MagicMock,
    ) -> None:
        """A video-only tweet (no photos) still uses send_video on the main post."""
        client = BlueskyClient()
        client._logged_in = True
        client._client.send_post = MagicMock()
        client._client.send_video = MagicMock(
            return_value=SimpleNamespace(uri="at://did/video/1", cid="vidcid1")
        )

        tweet = Tweet(
            id="1",
            text="Video only",
            media=[MediaItem(
                url="https://pbs.twimg.com/thumb.jpg",
                type="video",
                variants=[{"content_type": "video/mp4", "url": "https://video.twimg.com/v/hi.mp4"}],
            )],
        )

        result = client.post(tweet)

        # Used send_video directly, not send_post
        client._client.send_video.assert_called_once()
        client._client.send_post.assert_not_called()
        assert result.uri == "at://did/video/1"

    @patch("bot.bluesky_client.download_video", return_value=b"\x00video")
    @patch("bot.bluesky_client.select_best_variant", return_value={
        "content_type": "video/mp4",
        "url": "https://video.twimg.com/v/hi.mp4",
    })
    @patch.object(BlueskyClient, "login")
    def test_multi_video_only_posts_remaining_as_replies(
        self, mock_login: MagicMock, mock_variant: MagicMock, mock_dl_vid: MagicMock,
    ) -> None:
        """A tweet with multiple videos (no photos) posts the first on the main
        post and the rest as threaded replies."""
        client = BlueskyClient()
        client._logged_in = True
        client._client.send_post = MagicMock()

        video_count = 0

        def fake_send_video(*, text, video, video_alt, video_aspect_ratio=None, reply_to=None):
            nonlocal video_count
            video_count += 1
            return SimpleNamespace(uri=f"at://did/video/{video_count}", cid=f"vidcid{video_count}")

        client._client.send_video = MagicMock(side_effect=fake_send_video)

        tweet = Tweet(
            id="1",
            text="Four goal clips",
            media=[
                MediaItem(
                    url="https://pbs.twimg.com/thumb1.jpg",
                    type="video",
                    alt_text="goal 1",
                    variants=[{"content_type": "video/mp4", "url": "https://video.twimg.com/v/1.mp4"}],
                ),
                MediaItem(
                    url="https://pbs.twimg.com/thumb2.jpg",
                    type="video",
                    alt_text="goal 2",
                    variants=[{"content_type": "video/mp4", "url": "https://video.twimg.com/v/2.mp4"}],
                ),
                MediaItem(
                    url="https://pbs.twimg.com/thumb3.jpg",
                    type="video",
                    alt_text="goal 3",
                    variants=[{"content_type": "video/mp4", "url": "https://video.twimg.com/v/3.mp4"}],
                ),
                MediaItem(
                    url="https://pbs.twimg.com/thumb4.jpg",
                    type="video",
                    alt_text="goal 4",
                    variants=[{"content_type": "video/mp4", "url": "https://video.twimg.com/v/4.mp4"}],
                ),
            ],
        )

        result = client.post(tweet)

        # First video on main post + 3 video replies = 4 send_video calls
        assert client._client.send_video.call_count == 4
        client._client.send_post.assert_not_called()

        # Main post has no reply_to (standalone)
        main_kwargs = client._client.send_video.call_args_list[0].kwargs
        assert main_kwargs["reply_to"] is None

        # Second video reply chains off the main post
        second_kwargs = client._client.send_video.call_args_list[1].kwargs
        assert second_kwargs["reply_to"].parent.uri == "at://did/video/1"
        assert second_kwargs["reply_to"].root.uri == "at://did/video/1"
        assert second_kwargs["text"] == ""

        # Third video reply chains off the second
        third_kwargs = client._client.send_video.call_args_list[2].kwargs
        assert third_kwargs["reply_to"].parent.uri == "at://did/video/2"
        assert third_kwargs["reply_to"].root.uri == "at://did/video/1"

        # Fourth video reply chains off the third
        fourth_kwargs = client._client.send_video.call_args_list[3].kwargs
        assert fourth_kwargs["reply_to"].parent.uri == "at://did/video/3"
        assert fourth_kwargs["reply_to"].root.uri == "at://did/video/1"

        # Return value is the last video reply
        assert result.uri == "at://did/video/4"


class TestPrepareSingleVideo:
    @patch("bot.bluesky_client.download_video", return_value=b"\x00\x00video-bytes")
    @patch("bot.bluesky_client.select_best_variant", return_value={
        "content_type": "video/mp4",
        "bit_rate": 2176000,
        "url": "https://video.twimg.com/v/hi.mp4",
    })
    def test_returns_data_for_single_item(self, mock_variant: MagicMock, mock_dl: MagicMock) -> None:
        item = MediaItem(
            url="https://pbs.twimg.com/thumb.jpg",
            type="video",
            alt_text="Goal",
            width=1920,
            height=1080,
            variants=[{"content_type": "video/mp4", "bit_rate": 2176000, "url": "https://video.twimg.com/v/hi.mp4"}],
        )
        data, alt, w, h = BlueskyClient._prepare_single_video(item)
        assert data == b"\x00\x00video-bytes"
        assert alt == "Goal"
        assert w == 1920
        assert h == 1080

    @patch("bot.bluesky_client.select_best_variant", return_value=None)
    def test_no_mp4_variant_returns_none(self, mock_variant: MagicMock) -> None:
        item = MediaItem(
            url="https://pbs.twimg.com/thumb.jpg",
            type="video",
            variants=[{"content_type": "application/x-mpegURL", "url": "https://video.twimg.com/v/playlist.m3u8"}],
        )
        data, alt, w, h = BlueskyClient._prepare_single_video(item)
        assert data is None

    @patch("bot.bluesky_client.download_video", side_effect=Exception("fail"))
    @patch("bot.bluesky_client.select_best_variant", return_value={
        "content_type": "video/mp4",
        "url": "https://video.twimg.com/v/hi.mp4",
    })
    def test_download_failure_returns_none(self, mock_variant: MagicMock, mock_dl: MagicMock) -> None:
        item = MediaItem(
            url="https://pbs.twimg.com/thumb.jpg",
            type="video",
            variants=[{"content_type": "video/mp4", "url": "https://video.twimg.com/v/hi.mp4"}],
        )
        data, alt, w, h = BlueskyClient._prepare_single_video(item)
        assert data is None
