from __future__ import annotations

import pytest

from bot.models import MediaItem, Tweet


@pytest.fixture()
def simple_tweet() -> Tweet:
    """A tweet with plain text, no media or URLs."""
    return Tweet(id="100", text="Hello world")


@pytest.fixture()
def tweet_with_tco_url() -> Tweet:
    """A tweet containing a t.co URL that should be expanded."""
    return Tweet(
        id="101",
        text="Check out https://t.co/abc123",
        urls=[{
            "url": "https://t.co/abc123",
            "expanded_url": "https://example.com/article",
            "display_url": "example.com/article",
        }],
    )


@pytest.fixture()
def tweet_with_media() -> Tweet:
    """A tweet with two photo attachments and a trailing media URL."""
    return Tweet(
        id="102",
        text="Game day! https://t.co/img1",
        media=[
            MediaItem(url="https://pbs.twimg.com/media/photo1.jpg", type="photo", alt_text="Stadium shot"),
            MediaItem(url="https://pbs.twimg.com/media/photo2.jpg", type="photo", alt_text=""),
        ],
        urls=[{
            "url": "https://t.co/img1",
            "expanded_url": "https://twitter.com/user/status/102/photo/1",
            "display_url": "pic.twitter.com/img1",
        }],
    )


@pytest.fixture()
def tweet_with_multiple_urls() -> Tweet:
    """A tweet with two real URLs."""
    return Tweet(
        id="104",
        text="See https://t.co/a and https://t.co/b for details",
        urls=[
            {
                "url": "https://t.co/a",
                "expanded_url": "https://example.com/a",
                "display_url": "example.com/a",
            },
            {
                "url": "https://t.co/b",
                "expanded_url": "https://example.com/b",
                "display_url": "example.com/b",
            },
        ],
    )


@pytest.fixture()
def long_tweet() -> Tweet:
    """A tweet whose text exceeds 300 graphemes."""
    return Tweet(id="105", text="A" * 350)
