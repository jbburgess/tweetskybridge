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
) -> SimpleNamespace:
    return SimpleNamespace(
        id=tweet_id,
        text=text,
        attachments=attachments,
        entities=entities,
    )


def _make_tweepy_media(
    media_key: str = "mk_1",
    url: str = "https://pbs.twimg.com/media/photo.jpg",
    preview_image_url: str | None = None,
    media_type: str = "photo",
    alt_text: str = "",
) -> SimpleNamespace:
    m = SimpleNamespace(
        media_key=media_key,
        url=url,
        preview_image_url=preview_image_url,
        type=media_type,
        alt_text=alt_text,
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
