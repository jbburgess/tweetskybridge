from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import tweepy

from bot import config
from bot.twitter_client import TwitterClient

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _set_config() -> None:
    config.TWITTER_BEARER_TOKEN = "test-bearer-token"
    config.TWITTER_HANDLE = "testuser"


def _make_tweepy_user(user_id: int = 12345, username: str = "testuser") -> SimpleNamespace:
    return SimpleNamespace(id=user_id, username=username)


def _make_tweepy_tweet(
    tweet_id: int = 1,
    text: str = "hello",
    attachments: dict | None = None,
    entities: dict | None = None,
    in_reply_to_user_id: int | None = None,
    referenced_tweets: list | None = None,
    conversation_id: int | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=tweet_id,
        text=text,
        attachments=attachments,
        entities=entities,
        in_reply_to_user_id=in_reply_to_user_id,
        referenced_tweets=referenced_tweets,
        conversation_id=conversation_id or tweet_id,
    )


def _make_tweepy_media(
    media_key: str = "mk_1",
    url: str = "https://pbs.twimg.com/media/photo.jpg",
    preview_image_url: str | None = None,
    media_type: str = "photo",
    alt_text: str = "",
    variants: list | None = None,
) -> SimpleNamespace:
    m = SimpleNamespace(
        media_key=media_key,
        url=url,
        preview_image_url=preview_image_url,
        type=media_type,
        alt_text=alt_text,
        variants=variants,
    )
    return m


class TestResolveUserId:
    @patch("bot.twitter_client.save_twitter_user_id")
    @patch("bot.twitter_client.load_twitter_user_id", return_value="99999")
    def test_uses_cached_id(self, mock_load: MagicMock, mock_save: MagicMock) -> None:
        client = TwitterClient.__new__(TwitterClient)
        client._client = MagicMock()

        result = client._resolve_user_id()

        assert result == "99999"
        client._client.get_user.assert_not_called()
        mock_save.assert_not_called()

    @patch("bot.twitter_client.save_twitter_user_id")
    @patch("bot.twitter_client.load_twitter_user_id", return_value=None)
    def test_fetches_and_caches_when_not_cached(
        self, mock_load: MagicMock, mock_save: MagicMock
    ) -> None:
        client = TwitterClient.__new__(TwitterClient)
        client._client = MagicMock()

        user = _make_tweepy_user(user_id=42)
        client._client.get_user.return_value = SimpleNamespace(data=user)

        result = client._resolve_user_id()

        assert result == "42"
        mock_save.assert_called_once_with("42")

    @patch("bot.twitter_client.save_twitter_user_id")
    @patch("bot.twitter_client.load_twitter_user_id", return_value=None)
    def test_raises_on_user_not_found(
        self, mock_load: MagicMock, mock_save: MagicMock
    ) -> None:
        client = TwitterClient.__new__(TwitterClient)
        client._client = MagicMock()
        client._client.get_user.return_value = SimpleNamespace(data=None)

        with pytest.raises(RuntimeError, match="not found"):
            client._resolve_user_id()


class TestFetchRecentTweets:
    @patch("bot.twitter_client.save_twitter_user_id")
    @patch("bot.twitter_client.load_twitter_user_id", return_value="12345")
    def test_returns_tweets_with_media(
        self, mock_load: MagicMock, mock_save: MagicMock
    ) -> None:
        client = TwitterClient.__new__(TwitterClient)
        client._client = MagicMock()

        media_obj = _make_tweepy_media(
            media_key="mk_1",
            url="https://pbs.twimg.com/media/photo.jpg",
            alt_text="alt",
        )
        tweet_obj = _make_tweepy_tweet(
            tweet_id=100,
            text="Game day!",
            attachments={"media_keys": ["mk_1"]},
            entities={"urls": [{"url": "https://t.co/x", "expanded_url": "https://example.com", "display_url": "example.com"}]},
        )

        client._client.get_users_tweets.return_value = SimpleNamespace(
            data=[tweet_obj],
            includes={"media": [media_obj]},
        )

        tweets = client.fetch_recent_tweets()

        assert len(tweets) == 1
        assert tweets[0].id == "100"
        assert tweets[0].text == "Game day!"
        assert len(tweets[0].media) == 1
        assert tweets[0].media[0].url == "https://pbs.twimg.com/media/photo.jpg"
        assert tweets[0].media[0].alt_text == "alt"
        assert tweets[0].media[0].type == "photo"
        assert len(tweets[0].urls) == 1
        assert tweets[0].urls[0]["expanded_url"] == "https://example.com"

    @patch("bot.twitter_client.save_twitter_user_id")
    @patch("bot.twitter_client.load_twitter_user_id", return_value="12345")
    def test_rate_limit_returns_empty(
        self, mock_load: MagicMock, mock_save: MagicMock
    ) -> None:
        client = TwitterClient.__new__(TwitterClient)
        client._client = MagicMock()
        client._client.get_users_tweets.side_effect = tweepy.TooManyRequests(
            MagicMock()
        )

        result = client.fetch_recent_tweets()

        assert result == []

    @patch("bot.twitter_client.save_twitter_user_id")
    @patch("bot.twitter_client.load_twitter_user_id", return_value="12345")
    def test_no_data_returns_empty(
        self, mock_load: MagicMock, mock_save: MagicMock
    ) -> None:
        client = TwitterClient.__new__(TwitterClient)
        client._client = MagicMock()
        client._client.get_users_tweets.return_value = SimpleNamespace(
            data=None, includes=None
        )

        result = client.fetch_recent_tweets()

        assert result == []

    @patch("bot.twitter_client.save_twitter_user_id")
    @patch("bot.twitter_client.load_twitter_user_id", return_value="12345")
    def test_tweet_without_media_or_entities(
        self, mock_load: MagicMock, mock_save: MagicMock
    ) -> None:
        client = TwitterClient.__new__(TwitterClient)
        client._client = MagicMock()

        tweet_obj = _make_tweepy_tweet(tweet_id=200, text="plain tweet")

        client._client.get_users_tweets.return_value = SimpleNamespace(
            data=[tweet_obj],
            includes=None,
        )

        tweets = client.fetch_recent_tweets()

        assert len(tweets) == 1
        assert tweets[0].media == []
        assert tweets[0].urls == []

    @patch("bot.twitter_client.save_twitter_user_id")
    @patch("bot.twitter_client.load_twitter_user_id", return_value="12345")
    def test_missing_media_key_skipped(
        self, mock_load: MagicMock, mock_save: MagicMock
    ) -> None:
        client = TwitterClient.__new__(TwitterClient)
        client._client = MagicMock()

        tweet_obj = _make_tweepy_tweet(
            tweet_id=300,
            text="photo tweet",
            attachments={"media_keys": ["mk_missing"]},
        )

        client._client.get_users_tweets.return_value = SimpleNamespace(
            data=[tweet_obj],
            includes={"media": []},
        )

        tweets = client.fetch_recent_tweets()

        assert len(tweets) == 1
        assert tweets[0].media == []

    @patch("bot.twitter_client.save_twitter_user_id")
    @patch("bot.twitter_client.load_twitter_user_id", return_value="12345")
    def test_returns_chronological_order(
        self, mock_load: MagicMock, mock_save: MagicMock
    ) -> None:
        client = TwitterClient.__new__(TwitterClient)
        client._client = MagicMock()

        # Twitter API returns newest first: 300, 200, 100
        tweet_objs = [
            _make_tweepy_tweet(tweet_id=300, text="third"),
            _make_tweepy_tweet(tweet_id=200, text="second"),
            _make_tweepy_tweet(tweet_id=100, text="first"),
        ]

        client._client.get_users_tweets.return_value = SimpleNamespace(
            data=tweet_objs,
            includes=None,
        )

        tweets = client.fetch_recent_tweets()

        assert [t.id for t in tweets] == ["100", "200", "300"]

    @patch("bot.twitter_client.save_twitter_user_id")
    @patch("bot.twitter_client.load_twitter_user_id", return_value="12345")
    def test_returns_video_with_variants(
        self, mock_load: MagicMock, mock_save: MagicMock
    ) -> None:
        client = TwitterClient.__new__(TwitterClient)
        client._client = MagicMock()

        video_variants = [
            {"content_type": "application/x-mpegURL", "url": "https://video.twimg.com/v/playlist.m3u8"},
            {"content_type": "video/mp4", "bit_rate": 832000, "url": "https://video.twimg.com/v/lo.mp4"},
            {"content_type": "video/mp4", "bit_rate": 2176000, "url": "https://video.twimg.com/v/hi.mp4"},
        ]
        media_obj = _make_tweepy_media(
            media_key="mk_v",
            url=None,
            preview_image_url="https://pbs.twimg.com/ext_tw_video_thumb/preview.jpg",
            media_type="video",
            alt_text="Goal clip",
            variants=video_variants,
        )
        tweet_obj = _make_tweepy_tweet(
            tweet_id=500,
            text="What a goal!",
            attachments={"media_keys": ["mk_v"]},
        )

        client._client.get_users_tweets.return_value = SimpleNamespace(
            data=[tweet_obj],
            includes={"media": [media_obj]},
        )

        tweets = client.fetch_recent_tweets()

        assert len(tweets) == 1
        assert len(tweets[0].media) == 1
        m = tweets[0].media[0]
        assert m.type == "video"
        assert m.url == "https://pbs.twimg.com/ext_tw_video_thumb/preview.jpg"
        assert m.alt_text == "Goal clip"
        assert len(m.variants) == 3
        assert m.variants[2]["bit_rate"] == 2176000

    @patch("bot.twitter_client.save_twitter_user_id")
    @patch("bot.twitter_client.load_twitter_user_id", return_value="12345")
    def test_returns_gif_with_single_variant(
        self, mock_load: MagicMock, mock_save: MagicMock
    ) -> None:
        client = TwitterClient.__new__(TwitterClient)
        client._client = MagicMock()

        gif_variants = [
            {"content_type": "video/mp4", "bit_rate": 0, "url": "https://video.twimg.com/g/gif.mp4"},
        ]
        media_obj = _make_tweepy_media(
            media_key="mk_g",
            url=None,
            preview_image_url="https://pbs.twimg.com/tweet_video_thumb/thumb.jpg",
            media_type="animated_gif",
            variants=gif_variants,
        )
        tweet_obj = _make_tweepy_tweet(
            tweet_id=600,
            text="Reaction",
            attachments={"media_keys": ["mk_g"]},
        )

        client._client.get_users_tweets.return_value = SimpleNamespace(
            data=[tweet_obj],
            includes={"media": [media_obj]},
        )

        tweets = client.fetch_recent_tweets()

        assert len(tweets) == 1
        m = tweets[0].media[0]
        assert m.type == "animated_gif"
        assert len(m.variants) == 1
        assert m.variants[0]["content_type"] == "video/mp4"

    @patch("bot.twitter_client.save_twitter_user_id")
    @patch("bot.twitter_client.load_twitter_user_id", return_value="12345")
    def test_photo_has_no_variants(
        self, mock_load: MagicMock, mock_save: MagicMock
    ) -> None:
        client = TwitterClient.__new__(TwitterClient)
        client._client = MagicMock()

        media_obj = _make_tweepy_media(media_key="mk_p", media_type="photo")
        tweet_obj = _make_tweepy_tweet(
            tweet_id=700,
            text="Photo",
            attachments={"media_keys": ["mk_p"]},
        )

        client._client.get_users_tweets.return_value = SimpleNamespace(
            data=[tweet_obj],
            includes={"media": [media_obj]},
        )

        tweets = client.fetch_recent_tweets()

        assert tweets[0].media[0].variants == []

    @patch("bot.twitter_client.save_twitter_user_id")
    @patch("bot.twitter_client.load_twitter_user_id", return_value="12345")
    def test_standalone_tweet_has_no_reply_fields(self, mock_load: MagicMock, mock_save: MagicMock) -> None:
        client = TwitterClient.__new__(TwitterClient)
        client._client = MagicMock()

        tweet_obj = _make_tweepy_tweet(tweet_id=100, text="standalone")

        client._client.get_users_tweets.return_value = SimpleNamespace(
            data=[tweet_obj], includes=None
        )

        tweets = client.fetch_recent_tweets()

        assert tweets[0].reply_to_tweet_id is None
        assert tweets[0].conversation_id == "100"
        assert tweets[0].quoted_tweet is None

    @patch("bot.twitter_client.save_twitter_user_id")
    @patch("bot.twitter_client.load_twitter_user_id", return_value="12345")
    def test_self_reply_sets_reply_to_tweet_id(self, mock_load: MagicMock, mock_save: MagicMock) -> None:
        """A tweet that's a reply to the same account is a thread continuation."""
        client = TwitterClient.__new__(TwitterClient)
        client._client = MagicMock()

        # Parent tweet
        parent = _make_tweepy_tweet(tweet_id=100, text="Part 1", conversation_id=100)
        # Child tweet replying to parent by the same user (id 12345)
        child = _make_tweepy_tweet(
            tweet_id=200,
            text="Part 2",
            in_reply_to_user_id=12345,
            referenced_tweets=[
                SimpleNamespace(id=100, type="replied_to"),
            ],
            conversation_id=100,
        )

        client._client.get_users_tweets.return_value = SimpleNamespace(
            data=[child, parent],  # Twitter returns newest-first
            includes=None,
        )

        tweets = client.fetch_recent_tweets()

        # Should be in chronological order after reverse()
        assert tweets[0].id == "100"
        assert tweets[0].reply_to_tweet_id is None
        assert tweets[1].id == "200"
        assert tweets[1].reply_to_tweet_id == "100"
        assert tweets[1].conversation_id == "100"

    @patch("bot.twitter_client.save_twitter_user_id")
    @patch("bot.twitter_client.load_twitter_user_id", return_value="12345")
    def test_reply_to_other_user_not_flagged(self, mock_load: MagicMock, mock_save: MagicMock) -> None:
        """A reply to a different account is not treated as a self-reply thread."""
        client = TwitterClient.__new__(TwitterClient)
        client._client = MagicMock()

        tweet_obj = _make_tweepy_tweet(
            tweet_id=300,
            text="@other thanks!",
            in_reply_to_user_id=99999,  # different user
            referenced_tweets=[
                SimpleNamespace(id=150, type="replied_to"),
            ],
            conversation_id=150,
        )

        client._client.get_users_tweets.return_value = SimpleNamespace(
            data=[tweet_obj], includes=None
        )

        tweets = client.fetch_recent_tweets()

        assert tweets[0].reply_to_tweet_id is None

    @patch("bot.twitter_client.save_twitter_user_id")
    @patch("bot.twitter_client.load_twitter_user_id", return_value="12345")
    def test_quoted_tweet_is_hydrated(self, mock_load: MagicMock, mock_save: MagicMock) -> None:
        """A quote tweet populates quoted_tweet with the referenced tweet's data."""
        client = TwitterClient.__new__(TwitterClient)
        client._client = MagicMock()

        quoted_media = _make_tweepy_media(
            media_key="mk_q1",
            url="https://pbs.twimg.com/media/quoted.jpg",
            media_type="photo",
        )
        quoted_obj = SimpleNamespace(
            id=999,
            text="3 goals for @SJEarthquakes!",
            attachments={"media_keys": ["mk_q1"]},
            entities={"urls": []},
        )
        main_tweet = _make_tweepy_tweet(
            tweet_id=1000,
            text="bringing home https://t.co/abc",
            entities={"urls": [{"url": "https://t.co/abc", "expanded_url": "https://twitter.com/MLS/status/999", "display_url": "twitter.com/MLS/status/999"}]},
            referenced_tweets=[SimpleNamespace(id=999, type="quoted")],
        )

        client._client.get_users_tweets.return_value = SimpleNamespace(
            data=[main_tweet],
            includes={"media": [quoted_media], "tweets": [quoted_obj]},
        )

        tweets = client.fetch_recent_tweets()

        assert len(tweets) == 1
        qt = tweets[0].quoted_tweet
        assert qt is not None
        assert qt.id == "999"
        assert qt.text == "3 goals for @SJEarthquakes!"
        assert len(qt.media) == 1
        assert qt.media[0].url == "https://pbs.twimg.com/media/quoted.jpg"
        assert qt.media[0].type == "photo"

    @patch("bot.twitter_client.save_twitter_user_id")
    @patch("bot.twitter_client.load_twitter_user_id", return_value="12345")
    def test_quoted_tweet_missing_from_includes(self, mock_load: MagicMock, mock_save: MagicMock) -> None:
        """If the referenced tweet object is absent from includes, quoted_tweet is None."""
        client = TwitterClient.__new__(TwitterClient)
        client._client = MagicMock()

        main_tweet = _make_tweepy_tweet(
            tweet_id=1001,
            text="quoting https://t.co/xyz",
            referenced_tweets=[SimpleNamespace(id=888, type="quoted")],
        )

        client._client.get_users_tweets.return_value = SimpleNamespace(
            data=[main_tweet],
            includes={"tweets": []},  # referenced tweet not present
        )

        tweets = client.fetch_recent_tweets()

        assert tweets[0].quoted_tweet is None
