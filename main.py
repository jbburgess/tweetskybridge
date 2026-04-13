from __future__ import annotations

import logging

from dotenv import load_dotenv

from bot import config
from bot.bluesky_client import BlueskyClient, BlueskyPostRef
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

    posted_refs: dict[str, BlueskyPostRef] = {}
    new_count = 0
    for tweet in tweets:
        if tweet.id in seen:
            continue
        log.info("Reposting tweet %s: %s", tweet.id, tweet.text[:60])

        parent_ref: BlueskyPostRef | None = None
        root_ref: BlueskyPostRef | None = None
        if tweet.reply_to_tweet_id:
            parent_ref = posted_refs.get(tweet.reply_to_tweet_id)
            if parent_ref is None:
                log.warning(
                    "Parent tweet %s not yet posted to Bluesky; posting tweet %s as standalone",
                    tweet.reply_to_tweet_id, tweet.id,
                )
            else:
                root_ref = posted_refs.get(tweet.conversation_id or tweet.reply_to_tweet_id, parent_ref)

        try:
            ref = bluesky.post(tweet, parent_ref=parent_ref, root_ref=root_ref)
        except Exception:
            log.exception("Failed to post tweet %s to Bluesky", tweet.id)
            break
        posted_refs[tweet.id] = ref
        seen.add(tweet.id)
        new_count += 1

    save_seen(seen)
    log.info("Done — %d new post(s)", new_count)


if __name__ == "__main__":
    main()