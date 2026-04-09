from __future__ import annotations

import logging

import requests

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
