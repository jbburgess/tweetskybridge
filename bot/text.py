from __future__ import annotations

import logging
import unicodedata

from atproto import client_utils

from bot import config
from bot.twitter_client import Tweet

log = logging.getLogger(__name__)


def _grapheme_len(text: str) -> int:
    """Return the number of extended grapheme clusters in *text*.

    This is a simplified count: each code point that is not a combining
    character or zero-width joiner counts as one grapheme.  For the vast
    majority of tweet text this is accurate.
    """
    count = 0
    for ch in text:
        cat = unicodedata.category(ch)
        if not cat.startswith("M") and ch not in ("\u200d",):
            count += 1
    return count


def resolve_urls(tweet: Tweet) -> str:
    """Replace t.co short URLs in tweet text with their expanded form.

    Also strips media-only URLs that Twitter appends at the end of the text
    (these point to the tweet's own media and add no value in the repost).
    """
    text = tweet.text

    # Collect media URLs to strip (Twitter appends e.g. https://t.co/xyz for
    # attached images — these aren't real links the user typed).
    media_expanded: set[str] = set()
    for m in tweet.media:
        # Twitter's entity URL for the media attachment
        media_expanded.add(m.url)

    for u in tweet.urls:
        short = u.get("url", "")
        expanded = u.get("expanded_url", "")
        if not short or not expanded:
            continue

        # If this URL entity points to the tweet's own media, remove it rather
        # than expanding, since the media will be attached as an embed.
        if expanded.startswith("https://twitter.com/") and ("/photo/" in expanded or "/video/" in expanded):
            text = text.replace(short, "").strip()
            continue
        if expanded.startswith("https://x.com/") and ("/photo/" in expanded or "/video/" in expanded):
            text = text.replace(short, "").strip()
            continue

        text = text.replace(short, expanded)

    return text.strip()


def truncate(text: str, limit: int = config.BLUESKY_GRAPHEME_LIMIT) -> str:
    """Truncate *text* to *limit* graphemes, appending '…' if shortened."""
    if _grapheme_len(text) <= limit:
        return text

    result: list[str] = []
    count = 0
    for ch in text:
        cat = unicodedata.category(ch)
        is_grapheme = not cat.startswith("M") and ch != "\u200d"
        if is_grapheme:
            if count >= limit - 1:  # reserve 1 for ellipsis
                break
            count += 1
        result.append(ch)

    return "".join(result).rstrip() + "…"


def build_text_builder(text: str, tweet: Tweet) -> client_utils.TextBuilder:
    """Build an atproto ``TextBuilder`` with link facets for URLs in *text*.

    Non-URL facets (mentions, hashtags) are left as plain text because we
    cannot reliably resolve Twitter handles to Bluesky DIDs.
    """
    tb = client_utils.TextBuilder()

    # Find URL spans in the *resolved* text and convert them to facets.
    # We iterate through the URL entities and look for the expanded URL in the
    # resolved text.
    remaining = text
    for u in tweet.urls:
        expanded = u.get("expanded_url", "")
        if not expanded or expanded not in remaining:
            continue

        # Skip media-only URLs that were already stripped
        if ("/photo/" in expanded and
                (expanded.startswith("https://twitter.com/") or
                 expanded.startswith("https://x.com/"))):
            continue

        idx = remaining.index(expanded)
        if idx > 0:
            tb.text(remaining[:idx])
        tb.link(expanded, expanded)
        remaining = remaining[idx + len(expanded):]

    if remaining:
        tb.text(remaining)

    return tb
