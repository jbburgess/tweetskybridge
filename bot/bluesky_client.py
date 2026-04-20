from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from atproto import Client, models
from atproto_client.exceptions import BadRequestError, InvokeTimeoutError, NetworkError, RequestException

from bot import config
from bot.media import download_image, download_video, fetch_og_metadata, get_image_dimensions, get_video_dimensions, select_best_variant
from bot.models import MediaItem, Tweet
from bot.text import build_text_builder, resolve_urls, split_text_for_thread
from bot.urls import is_twitter_photo_url, is_twitter_status_url

log = logging.getLogger(__name__)

# Retry settings for transient API errors (e.g. 503 NotEnoughResources)
_MAX_LOGIN_RETRIES = 3
_RETRY_BACKOFF_SECONDS = 5


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
        """Authenticate using a saved session string or handle/password.

        Retries on transient server errors (e.g. 503 NotEnoughResources)
        that can occur when the PDS is momentarily overloaded.
        """
        last_exc: Exception | None = None
        for attempt in range(1, _MAX_LOGIN_RETRIES + 1):
            try:
                self._try_login()
                return
            except InvokeTimeoutError as exc:
                last_exc = exc
                if attempt < _MAX_LOGIN_RETRIES:
                    log.warning(
                        "Login attempt %d/%d timed out, retrying in %ds",
                        attempt, _MAX_LOGIN_RETRIES, _RETRY_BACKOFF_SECONDS,
                    )
                    time.sleep(_RETRY_BACKOFF_SECONDS)
                else:
                    raise
            except NetworkError as exc:
                last_exc = exc
                resp = exc.response
                status = resp.status_code if resp is not None else None
                if status is not None and 500 <= status < 600 and attempt < _MAX_LOGIN_RETRIES:
                    log.warning(
                        "Login attempt %d/%d failed with network error (status %d), retrying in %ds",
                        attempt, _MAX_LOGIN_RETRIES, status, _RETRY_BACKOFF_SECONDS,
                    )
                    time.sleep(_RETRY_BACKOFF_SECONDS)
                else:
                    raise
            except BadRequestError as exc:
                last_exc = exc
                if attempt < _MAX_LOGIN_RETRIES:
                    log.warning(
                        "Login attempt %d/%d got 400 Bad Request (transient), retrying in %ds",
                        attempt, _MAX_LOGIN_RETRIES, _RETRY_BACKOFF_SECONDS,
                    )
                    time.sleep(_RETRY_BACKOFF_SECONDS)
                else:
                    raise
            except RequestException as exc:
                last_exc = exc
                resp = exc.response
                status = resp.status_code if resp is not None else None
                if status is not None and 500 <= status < 600 and attempt < _MAX_LOGIN_RETRIES:
                    log.warning(
                        "Login attempt %d/%d failed with status %d, retrying in %ds",
                        attempt, _MAX_LOGIN_RETRIES, status, _RETRY_BACKOFF_SECONDS,
                    )
                    time.sleep(_RETRY_BACKOFF_SECONDS)
                else:
                    raise
        assert last_exc is not None  # pragma: no cover
        raise last_exc  # pragma: no cover – only reachable if loop logic changes

    def _try_login(self) -> None:
        """Single login attempt via session string or handle/password."""
        if config.cfg.BLUESKY_SESSION:
            try:
                self._client.login(session_string=config.cfg.BLUESKY_SESSION)
                self._logged_in = True
                log.info("Logged in to Bluesky via session string")
                return
            except Exception:
                log.warning("Session string login failed, falling back to password")

        self._client.login(config.cfg.BLUESKY_HANDLE, config.cfg.BLUESKY_PASSWORD)
        self._logged_in = True
        log.info("Logged in to Bluesky as %s", config.cfg.BLUESKY_HANDLE)

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
        mixed = self._has_mixed_media(tweet)

        first_ref: BlueskyPostRef | None = None
        prev_ref: BlueskyPostRef | None = None
        video_on_main = False
        for k, part_text in enumerate(parts):
            tb = build_text_builder(part_text, tweet)

            # First chunk continues any caller-supplied thread; subsequent
            # chunks reply to the previous chunk within this split while
            # preserving any existing thread root. For standalone split
            # posts, fall back to the first chunk as the root.
            if k == 0:
                part_parent = parent_ref
                part_root = root_ref
            else:
                part_parent = prev_ref
                part_root = root_ref or first_ref

            reply = self._build_reply_ref(part_parent, part_root)

            # Attach media to the first chunk only.
            if k == 0:
                # For mixed-media tweets, prioritise the image gallery on the
                # main post and defer videos to threaded replies below.
                if mixed:
                    embed = self._build_image_embed(tweet) or self._build_link_card(tweet)
                else:
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
                            video_on_main = True
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

        # Post remaining videos as threaded replies.  For mixed-media tweets
        # (images + videos) all videos are deferred; for multi-video tweets
        # the first was already posted on the main post.
        video_items = [
            m for m in tweet.media
            if m.type in ("video", "animated_gif") and m.variants
        ]
        remaining = video_items[1:] if video_on_main else video_items if mixed else []
        for item in remaining:
                video_data, video_alt, video_w, video_h = self._prepare_single_video(item)
                if video_data is None:
                    continue
                try:
                    video_ar = (
                        models.AppBskyEmbedDefs.AspectRatio(width=video_w, height=video_h)
                        if video_w and video_h else None
                    )
                    reply = self._build_reply_ref(prev_ref, first_ref)
                    result = self._client.send_video(
                        text="", video=video_data, video_alt=video_alt,
                        video_aspect_ratio=video_ar, reply_to=reply,
                    )
                    log.info("Posted video reply to Bluesky for tweet %s", tweet.id)
                    ref = BlueskyPostRef(uri=str(result.uri), cid=str(result.cid))
                    prev_ref = ref
                except Exception:
                    log.warning("Failed to post video reply for tweet %s, skipping", tweet.id)

        return prev_ref

    # ------------------------------------------------------------------
    # Embeds
    # ------------------------------------------------------------------

    @staticmethod
    def _has_mixed_media(tweet: Tweet) -> bool:
        """Return ``True`` if *tweet* contains both photos and videos/GIFs."""
        has_photo = any(m.type == "photo" and m.url for m in tweet.media)
        has_video = any(
            m.type in ("video", "animated_gif") and m.variants
            for m in tweet.media
        )
        return has_photo and has_video

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

        return self._prepare_single_video(videos[0])

    @staticmethod
    def _prepare_single_video(item: "MediaItem") -> tuple[bytes | None, str, int, int]:
        """Download a single video/GIF *item*.

        Returns ``(video_bytes, alt_text, width, height)`` on success or
        ``(None, "", 0, 0)`` on failure.
        """
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
            if is_twitter_photo_url(expanded):
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
            if is_twitter_status_url(expanded, quoted.id):
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
