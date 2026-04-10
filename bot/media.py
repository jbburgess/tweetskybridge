from __future__ import annotations

import io
import logging
import struct

import requests
from PIL import Image as PILImage

from bot import config

log = logging.getLogger(__name__)


def download_image(url: str) -> bytes:
    """Download an image from *url* and return the raw bytes.

    Raises ``ValueError`` if the response exceeds MAX_IMAGE_BYTES.
    Raises ``requests.HTTPError`` on non-2xx responses.
    """
    resp = requests.get(url, timeout=config.HTTP_TIMEOUT, stream=True)
    resp.raise_for_status()

    chunks: list[bytes] = []
    size = 0
    for chunk in resp.iter_content(chunk_size=64 * 1024):
        size += len(chunk)
        if size > config.MAX_IMAGE_BYTES:
            raise ValueError(
                f"Image at {url} exceeds {config.MAX_IMAGE_BYTES} byte limit"
            )
        chunks.append(chunk)

    log.debug("Downloaded %d bytes from %s", size, url)
    return b"".join(chunks)


def download_video(url: str) -> bytes:
    """Download a video from *url* and return the raw bytes.

    Uses a longer timeout and higher size limit than image downloads.
    Raises ``ValueError`` if the response exceeds MAX_VIDEO_BYTES.
    Raises ``requests.HTTPError`` on non-2xx responses.
    """
    resp = requests.get(url, timeout=config.VIDEO_TIMEOUT, stream=True)
    resp.raise_for_status()

    chunks: list[bytes] = []
    size = 0
    for chunk in resp.iter_content(chunk_size=256 * 1024):
        size += len(chunk)
        if size > config.MAX_VIDEO_BYTES:
            raise ValueError(
                f"Video at {url} exceeds {config.MAX_VIDEO_BYTES} byte limit"
            )
        chunks.append(chunk)

    log.debug("Downloaded video %d bytes from %s", size, url)
    return b"".join(chunks)


def get_video_dimensions(data: bytes) -> tuple[int, int]:
    """Extract width and height from an MP4 video's tkhd (track header) box.

    Scans for the first tkhd box with non-zero dimensions, which corresponds
    to the video track. The width and height are stored as 16.16 fixed-point
    values; only the integer part is returned. Returns ``(0, 0)`` if the
    dimensions cannot be determined.
    """
    marker = b"tkhd"
    pos = data.find(marker)
    while pos != -1:
        # The tkhd payload begins immediately after the 4-byte type field.
        payload_start = pos + 4
        if payload_start >= len(data):
            break
        version = data[payload_start]
        # Byte offset from payload_start to the 16.16 fixed-point width field:
        #   v0: version(1)+flags(3)+creation(4)+modification(4)+track_id(4)
        #       +reserved(4)+duration(4)+reserved(8)+layer(2)+alt_group(2)
        #       +volume(2)+reserved(2)+matrix(36) = 76
        #   v1: version(1)+flags(3)+creation(8)+modification(8)+track_id(4)
        #       +reserved(4)+duration(8)+reserved(8)+layer(2)+alt_group(2)
        #       +volume(2)+reserved(2)+matrix(36) = 88
        w_offset = payload_start + (76 if version == 0 else 88)
        if w_offset + 8 <= len(data):
            raw_w = struct.unpack_from(">I", data, w_offset)[0]
            raw_h = struct.unpack_from(">I", data, w_offset + 4)[0]
            w = raw_w >> 16  # upper 16 bits of 16.16 fixed-point
            h = raw_h >> 16
            if w > 0 and h > 0:
                return w, h
        pos = data.find(marker, pos + 1)
    return 0, 0


def get_image_dimensions(data: bytes) -> tuple[int, int]:
    """Return ``(width, height)`` of the image in *data*.

    Returns ``(0, 0)`` if the dimensions cannot be determined, so callers can
    guard with ``if w and h:`` without unwrapping an optional.
    """
    try:
        with PILImage.open(io.BytesIO(data)) as im:
            return im.size  # (width, height)
    except Exception:
        return 0, 0


def select_best_variant(variants: list[dict]) -> dict | None:
    """Pick the highest-bitrate MP4 variant from a Twitter media variants list.

    Returns ``None`` if no MP4 variant is found.
    """
    mp4s = [v for v in variants if v.get("content_type") == "video/mp4"]
    if not mp4s:
        return None
    return max(mp4s, key=lambda v: int(v.get("bit_rate") or 0))


def fetch_og_metadata(url: str) -> dict[str, str]:
    """Fetch Open Graph metadata from a URL for external embed cards.

    Returns a dict with keys ``title``, ``description``, and ``image`` (all
    strings, possibly empty).
    """
    from bs4 import BeautifulSoup

    meta: dict[str, str] = {"title": "", "description": "", "image": ""}
    try:
        resp = requests.get(
            url,
            timeout=config.HTTP_TIMEOUT,
            headers={"User-Agent": "bskybot/1.0 (link-card preview)"},
        )
        resp.raise_for_status()
    except requests.RequestException:
        log.warning("Failed to fetch OG metadata from %s", url)
        return meta

    soup = BeautifulSoup(resp.text, "html.parser")

    for prop, key in [("og:title", "title"), ("og:description", "description"),
                      ("og:image", "image")]:
        tag = soup.find("meta", property=prop)
        if tag and tag.get("content"):
            meta[key] = str(tag["content"])

    # Fallbacks
    if not meta["title"]:
        title_tag = soup.find("title")
        if title_tag and title_tag.string:
            meta["title"] = title_tag.string.strip()
    if not meta["description"]:
        desc_tag = soup.find("meta", attrs={"name": "description"})
        if desc_tag and desc_tag.get("content"):
            meta["description"] = str(desc_tag["content"])

    return meta
