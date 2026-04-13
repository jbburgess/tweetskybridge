from __future__ import annotations

import json
import logging
from pathlib import Path

from bot import config

log = logging.getLogger(__name__)


def _read_state() -> dict:
    """Read and return the state file as a dict, handling legacy formats."""
    path = Path(config.cfg.STATE_FILE)
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {"seen_ids": data}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_state(data: dict) -> None:
    """Write *data* to the state file as formatted JSON."""
    Path(config.cfg.STATE_FILE).write_text(json.dumps(data, indent=2) + "\n")


def load_seen() -> set[str]:
    """Load the set of previously-seen tweet IDs from the state file."""
    return set(_read_state().get("seen_ids", []))


def save_seen(seen: set[str]) -> None:
    """Persist the set of seen tweet IDs, capping at MAX_SEEN_IDS."""
    trimmed = sorted(seen, key=int, reverse=True)[: config.cfg.MAX_SEEN_IDS]
    data = _read_state()
    data["seen_ids"] = trimmed
    _write_state(data)
    log.debug("Saved %d seen IDs", len(trimmed))


def load_twitter_user_id() -> str | None:
    """Return the cached Twitter numeric user ID, or None."""
    return _read_state().get("twitter_user_id")


def save_twitter_user_id(user_id: str) -> None:
    """Cache the Twitter numeric user ID in the state file."""
    data = _read_state()
    data["twitter_user_id"] = user_id
    _write_state(data)
