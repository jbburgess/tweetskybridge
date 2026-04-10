from __future__ import annotations

import logging
import os
import sys

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Required environment variables
# ---------------------------------------------------------------------------
TWITTER_BEARER_TOKEN: str = ""
TWITTER_HANDLE: str = ""
BLUESKY_HANDLE: str = ""
BLUESKY_PASSWORD: str = ""

# ---------------------------------------------------------------------------
# Optional
# ---------------------------------------------------------------------------
BLUESKY_SESSION: str = ""

# File used to persist seen tweet IDs (committed back to the repo by CI)
STATE_FILE: str = "seen_ids.json"

# Maximum number of seen IDs to keep (prevents unbounded growth)
MAX_SEEN_IDS: int = 100

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


def load() -> None:
    """Populate module-level config from environment variables.

    Raises ``SystemExit`` if any required variable is missing.
    """
    global TWITTER_BEARER_TOKEN, TWITTER_HANDLE
    global BLUESKY_HANDLE, BLUESKY_PASSWORD, BLUESKY_SESSION

    missing: list[str] = []
    for name in ("TWITTER_BEARER_TOKEN", "TWITTER_HANDLE",
                 "BLUESKY_HANDLE", "BLUESKY_PASSWORD"):
        value = os.environ.get(name, "")
        if not value:
            missing.append(name)
        else:
            globals()[name] = value

    if missing:
        log.error("Missing required environment variables: %s", ", ".join(missing))
        sys.exit(1)

    BLUESKY_SESSION = os.environ.get("BLUESKY_SESSION", "")
