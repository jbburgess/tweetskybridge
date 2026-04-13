from __future__ import annotations

_TWITTER_PREFIXES = ("https://twitter.com/", "https://x.com/")


def is_twitter_url(url: str) -> bool:
    """Check whether *url* points to twitter.com or x.com."""
    return any(url.startswith(p) for p in _TWITTER_PREFIXES)


def is_twitter_media_url(url: str) -> bool:
    """Check whether *url* is a twitter.com/x.com photo or video URL."""
    return is_twitter_url(url) and ("/photo/" in url or "/video/" in url)


def is_twitter_photo_url(url: str) -> bool:
    """Check whether *url* is a twitter.com/x.com photo URL."""
    return is_twitter_url(url) and "/photo/" in url


def is_twitter_status_url(url: str, tweet_id: str) -> bool:
    """Check whether *url* is a twitter.com/x.com status URL for *tweet_id*."""
    return is_twitter_url(url) and f"/status/{tweet_id}" in url
