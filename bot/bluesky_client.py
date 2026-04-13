from __future__ import annotations

import logging
from dataclasses import dataclass

from atproto import Client, models

from bot import config
from bot.media import download_image, download_video, fetch_og_metadata, get_image_dimensions, get_video_dimensions, select_best_variant
from bot.text import build_text_builder, resolve_urls, split_text_for_thread
from bot.twitter_client import Tweet

log = logging.getLogger(__name__)


@dataclass
class BlueskyPostRef:
    """URI + CID of a posted Bluesky record, used to chain reply threads."""

    uri: str
    cid: str


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

    @staticmethod
    def _build_reply_ref(
        parent_ref: BlueskyPostRef | None,
        root_ref: BlueskyPostRef | None = None,
    ) -> models.AppBskyFeedPost.ReplyRef | None:
        """Construct a Bluesky reply ref, or ``None`` for top-level posts."""
        if parent_ref is None:
            return None
        _parent = models.ComAtprotoRepoStrongRef.Main(uri=parent_ref.uri, cid=parent_ref.cid)
        _root = models.ComAtprotoRepoStrongRef.Main(
            uri=(root_ref or parent_ref).uri,
            cid=(root_ref or parent_ref).cid,
        )
        return models.AppBskyFeedPost.ReplyRef(parent=_parent, root=_root)

    def post(
        self,
        tweet: Tweet,
        *,
        parent_ref: BlueskyPostRef | None = None,
        root_ref: BlueskyPostRef | None = None,
    ) -> BlueskyPostRef:
        """Create a Bluesky post (or reply thread) from a Tweet.

        Long tweets are split into a chain of reply posts with ``(k/n)``
        suffixes.  Media is attached to the first post only.  Returns the
        URI+CID of the *last* posted record so callers can chain downstream
        replies.
        """
        if not self._logged_in:
            self.login()

        text = resolve_urls(tweet)
        parts = split_text_for_thread(text)
        n = len(parts)

        first_ref: BlueskyPostRef | None = None
        prev_ref: BlueskyPostRef | None = None
        for k, part_text in enumerate(parts):
            tb = build_text_builder(part_text, tweet)

            # First chunk continues any caller-supplied thread; subsequent
            # chunks reply to the previous chunk within this split.
            if k == 0:
                part_parent = parent_ref
                part_root = root_ref
            else:
                part_parent = prev_ref
                part_root = first_ref

            reply = self._build_reply_ref(part_parent, part_root)

            # Attach media to the first chunk only.
            if k == 0:
                # Video/GIF takes priority — send_video handles upload + post
                video_data, video_alt, video_w, video_h = self._prepare_video(tweet)
                if video_data is not None:
                    try:
                        video_ar = (
                            models.AppBskyEmbedDefs.AspectRatio(width=video_w, height=video_h)
                            if video_w and video_h else None
                        )
                        result = self._client.send_video(
                            text=tb, video=video_data, video_alt=video_alt,
                            video_aspect_ratio=video_ar, reply_to=reply,
                        )
                        label = f" part 1/{n}" if n > 1 else ""
                        log.info("Posted%s (video) to Bluesky: %s", label, part_text[:60])
                        ref = BlueskyPostRef(uri=str(result.uri), cid=str(result.cid))
                        first_ref = ref
                        prev_ref = ref
                        continue
                    except Exception:
                        log.warning("Bluesky rejected video for tweet %s, falling back to link card", tweet.id)

                embed = self._build_image_embed(tweet) or self._build_link_card(tweet)
            else:
                embed = None

            result = self._client.send_post(tb, embed=embed, reply_to=reply)
            label = f" part {k + 1}/{n}" if n > 1 else ""
            log.info("Posted%s to Bluesky: %s", label, part_text[:60])
            ref = BlueskyPostRef(uri=str(result.uri), cid=str(result.cid))
            if first_ref is None:
                first_ref = ref
            prev_ref = ref

        assert prev_ref is not None  # parts is always non-empty
        return prev_ref

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

        # For quote tweets, build the card directly from API data
        if tweet.quoted_tweet is not None:
            return self._build_quote_embed_card(tweet)

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

    def _build_quote_embed_card(self, tweet: Tweet) -> models.AppBskyEmbedExternal.Main | None:
        """Build an external link card for a quoted tweet using Twitter API data.

        Bypasses OG metadata scraping (which Twitter blocks) by using the
        quoted tweet text and media already fetched from the API.
        """
        quoted = tweet.quoted_tweet
        if quoted is None:
            return None

        # Find the twitter.com / x.com status URL for the quoted tweet
        target_url = ""
        for u in tweet.urls:
            expanded = u.get("expanded_url", "")
            if f"/status/{quoted.id}" in expanded and (
                expanded.startswith("https://twitter.com/") or
                expanded.startswith("https://x.com/")
            ):
                target_url = expanded
                break

        if not target_url:
            return None

        # Parse "@username" from URL: https://twitter.com/username/status/123 → "@username"
        try:
            title = "@" + target_url.split("/")[3]
        except IndexError:
            title = target_url

        description = quoted.text

        # Use the quoted tweet's first photo as the card thumbnail
        thumb = None
        photos = [m for m in quoted.media if m.type == "photo" and m.url]
        if photos:
            try:
                img_bytes = download_image(photos[0].url)
                thumb = self._client.upload_blob(img_bytes).blob
            except Exception:
                log.warning("Failed to download quoted tweet thumbnail for %s", target_url)

        return models.AppBskyEmbedExternal.Main(
            external=models.AppBskyEmbedExternal.External(
                uri=target_url,
                title=title,
                description=description,
                thumb=thumb,
            )
        )
