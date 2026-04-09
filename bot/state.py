from __future__ import annotations

import json
import logging
from pathlib import Path

from bot import config

log = logging.getLogger(__name__)


def load_seen() -> set[str]:
    """Load the set of previously-seen tweet IDs from the state file."""
    path = Path(config.STATE_FILE)
    try:
        data = json.loads(path.read_text())
        if isinstance(data, dict):
            # New format: {"seen_ids": [...], "twitter_user_id": "..."}
            return set(data.get("seen_ids", []))
        # Legacy format: plain list of IDs
        return set(data)
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_seen(seen: set[str]) -> None:
    """Persist the set of seen tweet IDs, capping at MAX_SEEN_IDS."""
    path = Path(config.STATE_FILE)

    # Keep only the most recent IDs (highest numeric value = newest)
    trimmed = sorted(seen, key=int, reverse=True)[: config.MAX_SEEN_IDS]

    # Preserve any extra fields already in the state file
    try:
        existing = json.loads(path.read_text())
        if isinstance(existing, dict):
            existing["seen_ids"] = trimmed
            payload = existing
        else:
            payload = {"seen_ids": trimmed}
    except (FileNotFoundError, json.JSONDecodeError):
        payload = {"seen_ids": trimmed}

    path.write_text(json.dumps(payload, indent=2) + "\n")
    log.debug("Saved %d seen IDs", len(trimmed))


def load_twitter_user_id() -> str | None:
    """Return the cached Twitter numeric user ID, or None."""
    path = Path(config.STATE_FILE)
    try:
        data = json.loads(path.read_text())
        if isinstance(data, dict):
            return data.get("twitter_user_id")
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return None


def save_twitter_user_id(user_id: str) -> None:
    """Cache the Twitter numeric user ID in the state file."""
    path = Path(config.STATE_FILE)
    try:
        raw = json.loads(path.read_text())
        data: dict[str, object] = raw if isinstance(raw, dict) else {"seen_ids": raw}
    except (FileNotFoundError, json.JSONDecodeError):
        data = {"seen_ids": []}

    data["twitter_user_id"] = user_id
    path.write_text(json.dumps(data, indent=2) + "\n")
