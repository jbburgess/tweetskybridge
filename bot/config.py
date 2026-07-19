from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class Config:
    # Required
    TWITTER_BEARER_TOKEN: str = ""
    TWITTER_HANDLE: str = ""
    BLUESKY_HANDLE: str = ""
    BLUESKY_PASSWORD: str = ""

    # Optional
    BLUESKY_SESSION: str = ""

    # File used to persist seen tweet IDs (committed back to the repo by CI)
    STATE_FILE: str = "id_map.json"

    # Maximum number of seen IDs to keep (prevents unbounded growth)
    MAX_SEEN_IDS: int = 100

    # Maximum number of recent tweets to fetch per run
    TWITTER_MAX_RESULTS: int = 5

    # Maximum image download size in bytes (5 MB)
    MAX_IMAGE_BYTES: int = 5 * 1024 * 1024

    # Maximum video download size in bytes (50 MB — Bluesky limit)
    MAX_VIDEO_BYTES: int = 50 * 1024 * 1024

    # HTTP timeout for media / OG-metadata fetches (seconds)
    HTTP_TIMEOUT: int = 15

    # HTTP timeout for video downloads (seconds — videos are much larger)
    VIDEO_TIMEOUT: int = 60

    # Bluesky grapheme limit
    BLUESKY_GRAPHEME_LIMIT: int = 300

    # Whether to mirror the Twitter pinned tweet to the Bluesky pinned post
    PIN_SYNC_ENABLED: bool = True


cfg = Config()


def load() -> None:
    """Populate ``cfg`` from environment variables.

    Raises ``SystemExit`` if any required variable is missing.
    """
    missing: list[str] = []
    for name in ("TWITTER_BEARER_TOKEN", "TWITTER_HANDLE",
                 "BLUESKY_HANDLE", "BLUESKY_PASSWORD"):
        value = os.environ.get(name, "")
        if not value:
            missing.append(name)
        else:
            setattr(cfg, name, value)

    if missing:
        log.error("Missing required environment variables: %s", ", ".join(missing))
        sys.exit(1)

    cfg.BLUESKY_SESSION = os.environ.get("BLUESKY_SESSION", "")

    pin_sync = os.environ.get("PIN_SYNC_ENABLED")
    if pin_sync is not None:
        cfg.PIN_SYNC_ENABLED = pin_sync.strip().lower() in ("1", "true", "yes", "on")

    max_results = os.environ.get("TWITTER_MAX_RESULTS")
    if max_results is not None:
        cfg.TWITTER_MAX_RESULTS = int(max_results)
