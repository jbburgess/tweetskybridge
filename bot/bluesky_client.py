from __future__ import annotations

import logging

from atproto import Client, models

from bot import config
from bot.media import download_image, download_video, fetch_og_metadata, get_image_dimensions, get_video_dimensions, select_best_variant
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

        # Video/GIF takes priority — send_video handles upload + post in one call
        video_data, video_alt, video_w, video_h = self._prepare_video(tweet)
        if video_data is not None:
            try:
                video_ar = (
                    models.AppBskyEmbedDefs.AspectRatio(width=video_w, height=video_h)
                    if video_w and video_h else None
                )
                self._client.send_video(text=tb, video=video_data, video_alt=video_alt, video_aspect_ratio=video_ar)
                log.info("Posted video to Bluesky: %s", text[:60])
                return
            except Exception:
                log.warning("Bluesky rejected video for tweet %s, falling back to link card", tweet.id)

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
            w = item.width
            h = item.height
            if not (w and h):
                w, h = get_image_dimensions(data)
            ar = models.AppBskyEmbedDefs.AspectRatio(width=w, height=h) if w and h else None
            images.append(models.AppBskyEmbedImages.Image(
                alt=item.alt_text,
                image=blob,
                aspect_ratio=ar,
            ))

        if not images:
            return None

        return models.AppBskyEmbedImages.Main(images=images)  # type: ignore[call-arg]

    def _prepare_video(self, tweet: Tweet) -> tuple[bytes | None, str, int, int]:
        """Download the first video/GIF variant for a tweet.

        Returns ``(video_bytes, alt_text, width, height)`` on success or
        ``(None, "", 0, 0)`` if the tweet has no downloadable video.
        Width and height come from the Twitter API media object and are used
        to set the aspect ratio on the Bluesky post without extra API calls.
        """
        videos = [m for m in tweet.media
                  if m.type in ("video", "animated_gif") and m.variants]
        if not videos:
            return None, "", 0, 0

        item = videos[0]  # Bluesky supports one video per post
        variant = select_best_variant(item.variants)
        if not variant:
            log.warning("No MP4 variant found for video media")
            return None, "", 0, 0

        try:
            data = download_video(variant["url"])
        except Exception:
            log.warning("Failed to download video %s", variant.get("url", "?"))
            return None, "", 0, 0

        # Use Twitter API dimensions if present; fall back to parsing the MP4
        # bytes directly (Twitter API returns null for width/height on video).
        w, h = (item.width, item.height) if (item.width and item.height) else get_video_dimensions(data)
        return data, item.alt_text, w, h

    def _build_link_card(self, tweet: Tweet) -> models.AppBskyEmbedExternal.Main | None:
        """Build an external link card embed for the first non-media URL.

        Also used as a fallback when video upload fails — the /video/ URL on
        twitter.com / x.com is kept so the card links to the original video.
        """
        # Only create a card if there are no photo embeds
        if any(m.type == "photo" and m.url for m in tweet.media):
            return None

        # Find the first real URL (skip /photo/ media links but keep /video/
        # links so they can serve as a fallback card).
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
