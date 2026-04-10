from __future__ import annotations

import logging
from dataclasses import dataclass, field

import tweepy
from tweepy.client import Response

from bot import config
from bot.state import load_twitter_user_id, save_twitter_user_id

log = logging.getLogger(__name__)


@dataclass
class MediaItem:
    url: str
    type: str  # "photo", "video", "animated_gif"
    alt_text: str = ""
    variants: list[dict] = field(default_factory=list)  # video/GIF stream variants


@dataclass
class Tweet:
    id: str
    text: str
    media: list[MediaItem] = field(default_factory=list)
    urls: list[dict[str, str]] = field(default_factory=list)  # [{url, expanded_url, display_url}]


class TwitterClient:
    """Thin wrapper around tweepy for fetching tweets via Twitter API v2."""

    def __init__(self) -> None:
        self._client = tweepy.Client(bearer_token=config.TWITTER_BEARER_TOKEN)

    def _resolve_user_id(self) -> str:
        """Return the numeric user ID for TWITTER_HANDLE, using the cache when available."""
        cached = load_twitter_user_id()
        if cached:
            log.debug("Using cached Twitter user ID: %s", cached)
            return cached

        resp: Response = self._client.get_user(username=config.TWITTER_HANDLE)  # type: ignore[assignment]
        if resp.data is None:
            raise RuntimeError(f"Twitter user @{config.TWITTER_HANDLE} not found")
        user_id = str(resp.data.id)

        save_twitter_user_id(user_id)
        log.info("Resolved @%s → user ID %s (cached)", config.TWITTER_HANDLE, user_id)
        return user_id

    def fetch_recent_tweets(self, max_results: int = 5) -> list[Tweet]:
        """Fetch recent original tweets (no retweets/replies) with media metadata."""
        user_id = self._resolve_user_id()

        try:
            resp: Response = self._client.get_users_tweets(  # type: ignore[assignment]
                id=user_id,
                max_results=max_results,
                exclude=["retweets", "replies"],
                tweet_fields=["created_at", "entities"],
                expansions=["attachments.media_keys"],
                media_fields=["url", "preview_image_url", "type", "alt_text", "variants"],
            )
        except tweepy.TooManyRequests:
            log.warning("Hit Twitter rate limit, skipping this run")
            return []

        if resp.data is None:
            log.info("No tweets returned for @%s", config.TWITTER_HANDLE)
            return []

        # Build a lookup from media_key → media object
        media_lookup: dict[str, tweepy.Media] = {}
        if resp.includes and "media" in resp.includes:
            for m in resp.includes["media"]:
                media_lookup[m.media_key] = m

        tweets: list[Tweet] = []
        for t in resp.data:
            # Collect media items
            media_items: list[MediaItem] = []
            if t.attachments and "media_keys" in t.attachments:
                for key in t.attachments["media_keys"]:
                    m = media_lookup.get(key)
                    if m is None:
                        continue
                    media_url = m.url or m.preview_image_url or ""
                    media_type = m.type or "photo"

                    # Parse video/GIF variants
                    variants: list[dict] = []
                    if media_type in ("video", "animated_gif"):
                        for v in getattr(m, "variants", None) or []:
                            if isinstance(v, dict):
                                variants.append(v)
                            else:
                                variants.append({
                                    "content_type": getattr(v, "content_type", ""),
                                    "url": getattr(v, "url", ""),
                                    "bit_rate": getattr(v, "bit_rate", 0),
                                })

                    media_items.append(MediaItem(
                        url=media_url,
                        type=media_type,
                        alt_text=getattr(m, "alt_text", "") or "",
                        variants=variants,
                    ))

            # Collect URL entities
            url_entities: list[dict[str, str]] = []
            if t.entities and "urls" in t.entities:
                for u in t.entities["urls"]:
                    url_entities.append({
                        "url": u.get("url", ""),
                        "expanded_url": u.get("expanded_url", ""),
                        "display_url": u.get("display_url", ""),
                    })

            tweets.append(Tweet(
                id=str(t.id),
                text=t.text,
                media=media_items,
                urls=url_entities,
            ))

        log.info("Fetched %d tweets from @%s", len(tweets), config.TWITTER_HANDLE)
        # Twitter returns newest-first; reverse to chronological order
        tweets.reverse()
        return tweets
