from __future__ import annotations

import logging

from atproto import Client, models

from bot import config
from bot.media import download_image, fetch_og_metadata
from bot.text import build_text_builder, resolve_urls, truncate
from bot.twitter_client import Tweet

log = logging.getLogger(__name__)


class BlueskyClient:
    """Wraps the atproto SDK for posting to Bluesky."""

    def __init__(self) -> None:
        self._client = Client()
        self._logged_in = False

    def login(self) -> None:
        """Authenticate using a saved session string or handle/password."""
        if config.BLUESKY_SESSION:
            try:
                self._client.login(session_string=config.BLUESKY_SESSION)
                self._logged_in = True
                log.info("Logged in to Bluesky via session string")
                return
            except Exception:
                log.warning("Session string login failed, falling back to password")

        self._client.login(config.BLUESKY_HANDLE, config.BLUESKY_PASSWORD)
        self._logged_in = True
        log.info("Logged in to Bluesky as %s", config.BLUESKY_HANDLE)

    def export_session(self) -> str:
        """Export the current session string for reuse on a future run."""
        return self._client.export_session_string()

    # ------------------------------------------------------------------
    # Posting
    # ------------------------------------------------------------------

    def post(self, tweet: Tweet) -> None:
        """Create a Bluesky post from a Tweet, including media and link cards."""
        if not self._logged_in:
            self.login()

        text = resolve_urls(tweet)
        text = truncate(text)
        tb = build_text_builder(text, tweet)

        # Determine embed (images take priority over link card)
        embed = self._build_image_embed(tweet) or self._build_link_card(tweet)

        self._client.send_post(tb, embed=embed)
        log.info("Posted to Bluesky: %s", text[:60])

    # ------------------------------------------------------------------
    # Embeds
    # ------------------------------------------------------------------

    def _build_image_embed(self, tweet: Tweet) -> models.AppBskyEmbedImages.Main | None:
        """Download tweet images and build an image embed (up to 4)."""
        photos = [m for m in tweet.media if m.type == "photo" and m.url]
        if not photos:
            return None

        images: list[models.AppBskyEmbedImages.Image] = []
        for item in photos[:4]:  # Bluesky limit
            try:
                data = download_image(item.url)
            except Exception:
                log.warning("Failed to download image %s, skipping", item.url)
                continue

            blob = self._client.upload_blob(data).blob
            images.append(models.AppBskyEmbedImages.Image(
                alt=item.alt_text,
                image=blob,
            ))

        if not images:
            return None

        return models.AppBskyEmbedImages.Main(images=images)  # type: ignore[call-arg]

    def _build_link_card(self, tweet: Tweet) -> models.AppBskyEmbedExternal.Main | None:
        """Build an external link card embed for the first non-media URL."""
        # Only create a card if there are no photo embeds
        if any(m.type == "photo" and m.url for m in tweet.media):
            return None

        # Find the first real URL (not a twitter media link)
        target_url = ""
        for u in tweet.urls:
            expanded = u.get("expanded_url", "")
            if not expanded:
                continue
            if ("/photo/" in expanded and
                    (expanded.startswith("https://twitter.com/") or
                     expanded.startswith("https://x.com/"))):
                continue
            target_url = expanded
            break

        if not target_url:
            return None

        og = fetch_og_metadata(target_url)
        if not og.get("title"):
            # No usable metadata — skip the card
            return None

        thumb = None
        if og.get("image"):
            try:
                img_bytes = download_image(og["image"])
                thumb = self._client.upload_blob(img_bytes).blob
            except Exception:
                log.warning("Failed to download OG image for %s", target_url)

        return models.AppBskyEmbedExternal.Main(
            external=models.AppBskyEmbedExternal.External(
                uri=target_url,
                title=og.get("title", ""),
                description=og.get("description", ""),
                thumb=thumb,
            )
        )
