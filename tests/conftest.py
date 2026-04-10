from __future__ import annotations

import pytest

from bot.twitter_client import MediaItem, Tweet


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
def tweet_with_link_and_no_media() -> Tweet:
    """A tweet with a URL but no images — should produce a link card."""
    return Tweet(
        id="103",
        text="Read more: https://t.co/link1",
        urls=[{
            "url": "https://t.co/link1",
            "expanded_url": "https://example.com/news",
            "display_url": "example.com/news",
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


@pytest.fixture()
def tweet_with_video() -> Tweet:
    """A tweet with a video attachment and variants."""
    return Tweet(
        id="106",
        text="Check this out! https://t.co/vid1",
        media=[
            MediaItem(
                url="https://pbs.twimg.com/ext_tw_video_thumb/preview.jpg",
                type="video",
                alt_text="Goal highlight",
                variants=[
                    {"content_type": "application/x-mpegURL", "url": "https://video.twimg.com/v/playlist.m3u8"},
                    {"content_type": "video/mp4", "bit_rate": 832000, "url": "https://video.twimg.com/v/vid_832.mp4"},
                    {"content_type": "video/mp4", "bit_rate": 2176000, "url": "https://video.twimg.com/v/vid_2176.mp4"},
                ],
            ),
        ],
        urls=[{
            "url": "https://t.co/vid1",
            "expanded_url": "https://twitter.com/user/status/106/video/1",
            "display_url": "pic.twitter.com/vid1",
        }],
    )


@pytest.fixture()
def tweet_with_gif() -> Tweet:
    """A tweet with an animated GIF attachment."""
    return Tweet(
        id="107",
        text="Reaction https://t.co/gif1",
        media=[
            MediaItem(
                url="https://pbs.twimg.com/tweet_video_thumb/preview.jpg",
                type="animated_gif",
                alt_text="",
                variants=[
                    {"content_type": "video/mp4", "bit_rate": 0, "url": "https://video.twimg.com/g/gif.mp4"},
                ],
            ),
        ],
        urls=[{
            "url": "https://t.co/gif1",
            "expanded_url": "https://x.com/user/status/107/video/1",
            "display_url": "pic.twitter.com/gif1",
        }],
    )
