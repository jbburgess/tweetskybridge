from __future__ import annotations

import pytest

from bot.text import _grapheme_len, _HASHTAG_RE, _split_into_chunks, build_text_builder, resolve_urls, split_text_for_thread, truncate
from bot.models import MediaItem, Tweet

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

    def test_strips_video_url_twitter(self) -> None:
        tweet = Tweet(
            id="202",
            text="Watch this https://t.co/vid1",
            media=[MediaItem(
                url="https://pbs.twimg.com/thumb.jpg",
                type="video",
                variants=[{"content_type": "video/mp4", "url": "https://video.twimg.com/v.mp4"}],
            )],
            urls=[{
                "url": "https://t.co/vid1",
                "expanded_url": "https://twitter.com/user/status/202/video/1",
                "display_url": "pic.twitter.com/vid1",
            }],
        )
        result = resolve_urls(tweet)
        assert result == "Watch this"

    def test_strips_video_url_xcom(self) -> None:
        tweet = Tweet(
            id="203",
            text="GIF time https://t.co/gif1",
            media=[MediaItem(
                url="https://pbs.twimg.com/thumb.jpg",
                type="animated_gif",
                variants=[{"content_type": "video/mp4", "url": "https://video.twimg.com/g.mp4"}],
            )],
            urls=[{
                "url": "https://t.co/gif1",
                "expanded_url": "https://x.com/user/status/203/video/1",
                "display_url": "pic.x.com/gif1",
            }],
        )
        result = resolve_urls(tweet)
        assert result == "GIF time"

    def test_strips_quoted_tweet_url_twitter(self) -> None:
        quoted = Tweet(id="999", text="quoted text")
        tweet = Tweet(
            id="1000",
            text="bringing home https://t.co/abc",
            urls=[{
                "url": "https://t.co/abc",
                "expanded_url": "https://twitter.com/MLS/status/999",
                "display_url": "twitter.com/MLS/status/999",
            }],
            quoted_tweet=quoted,
        )
        result = resolve_urls(tweet)
        assert "https://t.co/abc" not in result
        assert "twitter.com" not in result
        assert result == "bringing home"

    def test_strips_quoted_tweet_url_xcom(self) -> None:
        quoted = Tweet(id="888", text="quoted text")
        tweet = Tweet(
            id="1001",
            text="wow https://t.co/xyz",
            urls=[{
                "url": "https://t.co/xyz",
                "expanded_url": "https://x.com/ExampleFC/status/888",
                "display_url": "x.com/ExampleFC/status/888",
            }],
            quoted_tweet=quoted,
        )
        result = resolve_urls(tweet)
        assert result == "wow"

    def test_non_quote_tweet_status_url_not_stripped(self) -> None:
        """A twitter.com/status URL that is NOT the quoted tweet is kept as a link."""
        tweet = Tweet(
            id="1002",
            text="check this out https://t.co/lnk",
            urls=[{
                "url": "https://t.co/lnk",
                "expanded_url": "https://twitter.com/MLS/status/777",
                "display_url": "twitter.com/MLS/status/777",
            }],
            quoted_tweet=None,
        )
        result = resolve_urls(tweet)
        assert "https://twitter.com/MLS/status/777" in result


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


class TestSplitIntoChunks:
    def test_short_text_is_single_chunk(self) -> None:
        chunks = _split_into_chunks("hello world", 100)
        assert chunks == ["hello world"]

    def test_splits_on_word_boundary(self) -> None:
        # "hello world" (11) + " foo" (4) = 15; limit 11 → two chunks
        chunks = _split_into_chunks("hello world foo", 11)
        assert chunks[0] == "hello world"
        assert chunks[1] == "foo"

    def test_exact_fit_single_chunk(self) -> None:
        chunks = _split_into_chunks("hello", 5)
        assert chunks == ["hello"]

    def test_each_chunk_within_limit(self) -> None:
        text = " ".join(["word"] * 20)  # 20*4 + 19 = 99 chars
        chunks = _split_into_chunks(text, 20)
        for chunk in chunks:
            assert _grapheme_len(chunk) <= 20

    def test_hard_cuts_overlong_token(self) -> None:
        long_word = "A" * 20
        chunks = _split_into_chunks(long_word, 10)
        assert chunks == ["A" * 10, "A" * 10]

    def test_hard_cut_then_normal_word(self) -> None:
        # 15-char token + a short word; limit = 10
        text = "AAAAAAAAAAAAAAA hello"
        chunks = _split_into_chunks(text, 10)
        assert all(_grapheme_len(c) <= 10 for c in chunks)
        assert "hello" in chunks


class TestSplitTextForThread:
    def test_short_text_returns_single_item_no_suffix(self) -> None:
        parts = split_text_for_thread("Hello world")
        assert parts == ["Hello world"]

    def test_exactly_at_limit_returns_single_item(self) -> None:
        text = "A" * 300
        parts = split_text_for_thread(text)
        assert len(parts) == 1
        assert parts[0] == text

    def test_over_limit_splits_with_suffix(self) -> None:
        # 62 words of 5 chars separated by spaces = 62*5 + 61 = 371 graphemes
        text = " ".join(["hello"] * 62)
        parts = split_text_for_thread(text)
        n = len(parts)
        assert n >= 2
        for k, part in enumerate(parts, 1):
            assert part.endswith(f" ({k}/{n})")

    def test_each_chunk_within_limit(self) -> None:
        text = " ".join(["word"] * 120)  # ~599 graphemes
        parts = split_text_for_thread(text)
        for part in parts:
            assert _grapheme_len(part) <= 300

    def test_suffix_format_first_and_last(self) -> None:
        text = " ".join(["hello"] * 62)
        parts = split_text_for_thread(text)
        n = len(parts)
        assert parts[0].endswith(f" (1/{n})")
        assert parts[-1].endswith(f" ({n}/{n})")

    def test_all_words_preserved(self) -> None:
        """Every word in the original text appears in exactly one chunk."""
        words = [f"word{i}" for i in range(80)]  # each 5-6 chars
        text = " ".join(words)
        parts = split_text_for_thread(text)
        # Strip suffix from each part and rejoin
        import re
        stripped_parts = [re.sub(r" \(\d+/\d+\)$", "", p) for p in parts]
        recovered = " ".join(stripped_parts)
        assert recovered == text


class TestHashtagRegex:
    def test_simple_hashtag(self) -> None:
        assert _HASHTAG_RE.findall("Hello #MLS") == ["MLS"]

    def test_multiple_hashtags(self) -> None:
        assert _HASHTAG_RE.findall("#ExampleFC and #MLS") == ["ExampleFC", "MLS"]

    def test_hashtag_with_unicode(self) -> None:
        assert _HASHTAG_RE.findall("#Göteborg") == ["Göteborg"]

    def test_no_match_inside_url(self) -> None:
        # '#' inside a URL-like token preceded by a word char should NOT match
        assert _HASHTAG_RE.findall("https://example.com/page#section") == []

    def test_no_match_html_entity(self) -> None:
        # &#x27; should not produce a hashtag
        assert _HASHTAG_RE.findall("It&#x27;s fine") == []

    def test_hashtag_at_start(self) -> None:
        assert _HASHTAG_RE.findall("#GameDay is here") == ["GameDay"]

    def test_hashtag_only(self) -> None:
        assert _HASHTAG_RE.findall("#ExampleFCvRival") == ["ExampleFCvRival"]


class TestBuildTextBuilderHashtags:
    def test_single_hashtag_produces_tag_facet(self) -> None:
        tweet = Tweet(id="300", text="Go ExampleFC! #ExampleFCvRival")
        tb = build_text_builder("Go ExampleFC! #ExampleFCvRival", tweet)
        assert tb.build_text() == "Go ExampleFC! #ExampleFCvRival"
        facets = tb.build_facets()
        assert facets is not None
        assert len(facets) == 1
        assert facets[0].features[0].tag == "ExampleFCvRival"

    def test_multiple_hashtags(self) -> None:
        tweet = Tweet(id="301", text="#ExampleFC let's go #MLS")
        tb = build_text_builder("#ExampleFC let's go #MLS", tweet)
        assert tb.build_text() == "#ExampleFC let's go #MLS"
        facets = tb.build_facets()
        assert facets is not None
        assert len(facets) == 2
        tags = [f.features[0].tag for f in facets]
        assert "ExampleFC" in tags
        assert "MLS" in tags

    def test_hashtag_and_url_together(self) -> None:
        tweet = Tweet(
            id="302",
            text="Check out #MLS https://t.co/abc",
            urls=[{
                "url": "https://t.co/abc",
                "expanded_url": "https://example.com/mls",
                "display_url": "example.com/mls",
            }],
        )
        resolved = resolve_urls(tweet)
        tb = build_text_builder(resolved, tweet)
        assert tb.build_text() == "Check out #MLS https://example.com/mls"
        facets = tb.build_facets()
        assert facets is not None
        # One tag facet + one link facet
        assert len(facets) == 2

    def test_no_hashtags_no_extra_facets(self, simple_tweet: Tweet) -> None:
        tb = build_text_builder("Hello world", simple_tweet)
        facets = tb.build_facets()
        assert facets is None or len(facets) == 0
