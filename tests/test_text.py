from __future__ import annotations

import pytest

from bot.text import _grapheme_len, build_text_builder, resolve_urls, truncate
from bot.twitter_client import MediaItem, Tweet

pytestmark = pytest.mark.unit


class TestResolveUrls:
    def test_expands_tco_url(self, tweet_with_tco_url: Tweet) -> None:
        result = resolve_urls(tweet_with_tco_url)
        assert "https://t.co/abc123" not in result
        assert "https://example.com/article" in result

    def test_strips_media_photo_url_twitter(self, tweet_with_media: Tweet) -> None:
        result = resolve_urls(tweet_with_media)
        assert "https://t.co/img1" not in result
        assert "twitter.com" not in result
        assert result == "Game day!"

    def test_strips_media_photo_url_xcom(self) -> None:
        tweet = Tweet(
            id="200",
            text="Look at this https://t.co/xyz",
            media=[MediaItem(url="https://pbs.twimg.com/media/p.jpg", type="photo")],
            urls=[{
                "url": "https://t.co/xyz",
                "expanded_url": "https://x.com/user/status/200/photo/1",
                "display_url": "pic.x.com/xyz",
            }],
        )
        result = resolve_urls(tweet)
        assert result == "Look at this"

    def test_no_urls_returns_text_unchanged(self, simple_tweet: Tweet) -> None:
        assert resolve_urls(simple_tweet) == "Hello world"

    def test_multiple_urls_expanded(self, tweet_with_multiple_urls: Tweet) -> None:
        result = resolve_urls(tweet_with_multiple_urls)
        assert "https://example.com/a" in result
        assert "https://example.com/b" in result
        assert "https://t.co/" not in result

    def test_empty_expanded_url_skipped(self) -> None:
        tweet = Tweet(
            id="201",
            text="text https://t.co/x",
            urls=[{"url": "https://t.co/x", "expanded_url": "", "display_url": ""}],
        )
        result = resolve_urls(tweet)
        assert result == "text https://t.co/x"


class TestGraphemeLen:
    def test_ascii(self) -> None:
        assert _grapheme_len("hello") == 5

    def test_emoji(self) -> None:
        # A single emoji is one grapheme
        assert _grapheme_len("\U0001f600") == 1

    def test_combining_characters(self) -> None:
        # 'e' + combining acute accent = 1 grapheme
        assert _grapheme_len("e\u0301") == 1

    def test_zwj_sequence(self) -> None:
        # Family emoji ZWJ sequence: person + ZWJ + person
        seq = "\U0001f468\u200d\U0001f469"
        # ZWJ doesn't count, so just the two base emoji
        assert _grapheme_len(seq) == 2

    def test_empty_string(self) -> None:
        assert _grapheme_len("") == 0


class TestTruncate:
    def test_under_limit_unchanged(self, simple_tweet: Tweet) -> None:
        assert truncate("Hello world") == "Hello world"

    def test_exactly_at_limit(self) -> None:
        text = "A" * 300
        assert truncate(text) == text

    def test_over_limit_truncated(self, long_tweet: Tweet) -> None:
        result = truncate(long_tweet.text)
        assert result.endswith("…")
        assert _grapheme_len(result) == 300

    def test_custom_limit(self) -> None:
        result = truncate("Hello world, this is a test", limit=10)
        assert result.endswith("…")
        assert _grapheme_len(result) <= 10

    def test_emoji_truncation(self) -> None:
        text = "\U0001f600" * 301
        result = truncate(text)
        assert result.endswith("…")
        assert _grapheme_len(result) == 300


class TestBuildTextBuilder:
    def test_plain_text_no_facets(self, simple_tweet: Tweet) -> None:
        tb = build_text_builder("Hello world", simple_tweet)
        # TextBuilder produces text; verify it matches
        assert tb.build_text() == "Hello world"

    def test_url_becomes_link_facet(self, tweet_with_tco_url: Tweet) -> None:
        resolved = resolve_urls(tweet_with_tco_url)
        tb = build_text_builder(resolved, tweet_with_tco_url)
        text = tb.build_text()
        assert "https://example.com/article" in text

        facets = tb.build_facets()
        assert facets is not None
        assert len(facets) == 1

    def test_multiple_urls_produce_multiple_facets(
        self, tweet_with_multiple_urls: Tweet
    ) -> None:
        resolved = resolve_urls(tweet_with_multiple_urls)
        tb = build_text_builder(resolved, tweet_with_multiple_urls)
        facets = tb.build_facets()
        assert facets is not None
        assert len(facets) == 2

    def test_media_urls_not_faceted(self, tweet_with_media: Tweet) -> None:
        resolved = resolve_urls(tweet_with_media)
        tb = build_text_builder(resolved, tweet_with_media)
        facets = tb.build_facets()
        # Media URL was stripped, so no facets
        assert facets is None or len(facets) == 0
