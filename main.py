from __future__ import annotations

import logging
import sys

from dotenv import load_dotenv

from bot import config
from bot.bluesky_client import BlueskyClient
from bot.state import load_seen, save_seen
from bot.twitter_client import TwitterClient

log = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )

    # Load .env for local development (no-op if file is absent)
    load_dotenv()

    config.load()

    twitter = TwitterClient()
    bluesky = BlueskyClient()
    bluesky.login()

    seen = load_seen()
    tweets = twitter.fetch_recent_tweets()

    new_count = 0
    for tweet in tweets:
        if tweet.id in seen:
            continue
        log.info("Reposting tweet %s: %s", tweet.id, tweet.text[:60])
        try:
            bluesky.post(tweet)
        except Exception:
            log.exception("Failed to post tweet %s to Bluesky", tweet.id)
            continue
        seen.add(tweet.id)
        new_count += 1

    save_seen(seen)
    log.info("Done — %d new post(s)", new_count)


if __name__ == "__main__":
    main()