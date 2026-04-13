from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MediaItem:
    url: str
    type: str  # "photo", "video", "animated_gif"
    alt_text: str = ""
    variants: list[dict] = field(default_factory=list)  # video/GIF stream variants
    width: int = 0
    height: int = 0


@dataclass
class Tweet:
    id: str
    text: str
    media: list[MediaItem] = field(default_factory=list)
    urls: list[dict[str, str]] = field(default_factory=list)  # [{url, expanded_url, display_url}]
    reply_to_tweet_id: str | None = None  # Set for self-reply threads; Twitter ID of the parent tweet
    conversation_id: str | None = None    # Twitter ID of the thread root (equals id for standalone posts)
    quoted_tweet: Tweet | None = None     # Populated when this tweet quotes another tweet
