from __future__ import annotations

import html
import logging
import unicodedata

from atproto import client_utils

from bot import config
from bot.models import Tweet
from bot.urls import is_twitter_media_url, is_twitter_photo_url, is_twitter_status_url

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
        if is_twitter_media_url(expanded):
            text = text.replace(short, "").strip()
            continue

        # Strip the quoted tweet's status URL — the link card embed handles it
        if tweet.quoted_tweet is not None and is_twitter_status_url(expanded, tweet.quoted_tweet.id):
            text = text.replace(short, "").strip()
            continue

        text = text.replace(short, expanded)

    return html.unescape(text.strip())


def truncate(text: str, limit: int = config.cfg.BLUESKY_GRAPHEME_LIMIT) -> str:
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


def _split_into_chunks(text: str, max_graphemes: int) -> list[str]:
    """Split *text* into chunks of at most *max_graphemes* graphemes each.

    Splits on space boundaries where possible.  Performs a hard grapheme cut
    for single tokens that exceed *max_graphemes* on their own (e.g. very long
    URLs with no surrounding spaces).
    """
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for word in text.split(" "):
        word_len = _grapheme_len(word)

        # Hard-cut any single token that is longer than the limit.
        while word_len > max_graphemes:
            if current:
                chunks.append(" ".join(current))
                current = []
                current_len = 0
            cut: list[str] = []
            count = 0
            rest_start = len(word)
            for i, ch in enumerate(word):
                cat = unicodedata.category(ch)
                is_grapheme = not cat.startswith("M") and ch != "\u200d"
                if is_grapheme:
                    if count >= max_graphemes:
                        rest_start = i
                        break
                    count += 1
                cut.append(ch)
            else:
                rest_start = len(word)
            chunks.append("".join(cut))
            word = word[rest_start:]
            word_len = _grapheme_len(word)

        if not word:
            continue

        sep = 1 if current else 0
        if current_len + sep + word_len > max_graphemes:
            chunks.append(" ".join(current))
            current = [word]
            current_len = word_len
        else:
            current.append(word)
            current_len += sep + word_len

    if current:
        chunks.append(" ".join(current))

    return chunks or [text]


def split_text_for_thread(
    text: str, limit: int = config.cfg.BLUESKY_GRAPHEME_LIMIT
) -> list[str]:
    """Split *text* into Bluesky-sized chunks for a reply thread.

    If *text* fits within *limit* graphemes, a single-element list is returned
    with no suffix added.  Otherwise each chunk is suffixed with `` (k/n)``
    (counted against the limit) so no chunk exceeds it.
    """
    if _grapheme_len(text) <= limit:
        return [text]

    # Determine the suffix budget iteratively; converges in ≤ 2 passes.
    # Start with 8 chars, which covers " (k/n)" for n up to 99.
    suffix_budget = 8
    for _ in range(3):
        raw_chunks = _split_into_chunks(text, limit - suffix_budget)
        n = len(raw_chunks)
        actual_budget = _grapheme_len(f" ({n}/{n})")
        if actual_budget == suffix_budget:
            break
        suffix_budget = actual_budget

    return [f"{chunk} ({k}/{n})" for k, chunk in enumerate(raw_chunks, 1)]


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
        if is_twitter_photo_url(expanded):
            continue

        idx = remaining.index(expanded)
        if idx > 0:
            tb.text(remaining[:idx])
        tb.link(expanded, expanded)
        remaining = remaining[idx + len(expanded):]

    if remaining:
        tb.text(remaining)

    return tb
