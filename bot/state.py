from __future__ import annotations

import json
import logging
from pathlib import Path

from bot import config

log = logging.getLogger(__name__)


def _read_state() -> dict:
    """Read the state file as a dict, normalising legacy formats.

    The current format maps tweet IDs to the Bluesky post(s) they produced::

        {"posts": {"<tweet_id>": {"root": {...}, "tip": {...}} | null}, ...}

    Older formats are migrated on read:

    * A bare list ``["id", ...]`` (the original ``seen_ids`` file).
    * A dict with a ``seen_ids`` list.

    In both cases the IDs become keys of ``posts`` with a ``None`` value,
    marking them as seen-but-unmapped (we don't know their Bluesky posts).
    """
    path = Path(config.cfg.STATE_FILE)
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

    if isinstance(data, list):
        return {"posts": {str(tid): None for tid in data}}

    if not isinstance(data, dict):
        return {}

    if "posts" not in data and "seen_ids" in data:
        data = dict(data)
        seen_ids = data.pop("seen_ids") or []
        data["posts"] = {str(tid): None for tid in seen_ids}

    return data


def _write_state(data: dict) -> None:
    """Write *data* to the state file as formatted JSON."""
    Path(config.cfg.STATE_FILE).write_text(json.dumps(data, indent=2) + "\n")


def load_post_map() -> dict[str, dict | None]:
    """Load the tweet ID → Bluesky post mapping from the state file.

    Each value is either ``None`` (seen but unmapped) or a dict with ``root``
    and ``tip`` entries, each holding a Bluesky post ``uri``/``cid`` pair.
    """
    return dict(_read_state().get("posts", {}))


def save_post_map(posts: dict[str, dict | None]) -> None:
    """Persist the tweet ID → Bluesky post mapping, capping at MAX_SEEN_IDS.

    The newest ``MAX_SEEN_IDS`` tweet IDs (by numeric value) are retained.
    """
    trimmed_keys = sorted(posts, key=int, reverse=True)[: config.cfg.MAX_SEEN_IDS]
    trimmed = {k: posts[k] for k in trimmed_keys}
    data = _read_state()
    data["posts"] = trimmed
    data.pop("seen_ids", None)  # drop any lingering legacy key
    _write_state(data)
    log.debug("Saved %d post mappings", len(trimmed))


def load_seen() -> set[str]:
    """Load the set of previously-seen tweet IDs (keys of the post map)."""
    return set(_read_state().get("posts", {}).keys())


def load_twitter_user_id() -> str | None:
    """Return the cached Twitter numeric user ID, or None."""
    return _read_state().get("twitter_user_id")


def save_twitter_user_id(user_id: str) -> None:
    """Cache the Twitter numeric user ID in the state file."""
    data = _read_state()
    data["twitter_user_id"] = user_id
    _write_state(data)


def load_pin_audit_date() -> str | None:
    """Return the ISO date (UTC) of the last pinned-post audit, or None."""
    return _read_state().get("pin_audit_date")


def save_pin_audit_date(date_str: str) -> None:
    """Record the ISO date (UTC) of the most recent pinned-post audit."""
    data = _read_state()
    data["pin_audit_date"] = date_str
    _write_state(data)


def load_pinned_post() -> dict | None:
    """Return the currently-pinned Bluesky post record, or None.

    The record holds the source ``tweet_id`` plus the Bluesky ``uri``/``cid``
    of the post the bot has pinned, used to avoid redundant profile writes.
    """
    return _read_state().get("pinned_post")


def save_pinned_post(record: dict | None) -> None:
    """Persist the currently-pinned Bluesky post record (or None when unpinned)."""
    data = _read_state()
    data["pinned_post"] = record
    _write_state(data)
