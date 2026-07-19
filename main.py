from __future__ import annotations

import logging

from dotenv import load_dotenv

from bot import config
from bot.bluesky_client import BlueskyClient, BlueskyPostRef, PostedThread
from bot.state import load_post_map, save_post_map
from bot.twitter_client import TwitterClient

log = logging.getLogger(__name__)


def _thread_from_record(record: dict) -> PostedThread:
    """Rebuild a ``PostedThread`` from a persisted post-map record."""
    return PostedThread(
        root=BlueskyPostRef(**record["root"]),
        tip=BlueskyPostRef(**record["tip"]),
    )


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

    post_map = load_post_map()
    tweets = twitter.fetch_recent_tweets()

    # Combined lookup of tweet ID → PostedThread, seeded from the persisted
    # mapping and extended with posts made during this run. This lets replies
    # and quotes reference posts the bot made in earlier runs, not just the
    # current batch.
    threads: dict[str, PostedThread] = {
        tid: _thread_from_record(rec)
        for tid, rec in post_map.items()
        if rec is not None
    }

    new_count = 0
    for tweet in tweets:
        if tweet.id in post_map:
            continue
        log.info("Reposting tweet %s: %s", tweet.id, tweet.text[:60])

        parent_ref: BlueskyPostRef | None = None
        root_ref: BlueskyPostRef | None = None
        if tweet.reply_to_tweet_id:
            parent_thread = threads.get(tweet.reply_to_tweet_id)
            if parent_thread is None:
                log.warning(
                    "Parent tweet %s not mapped to a Bluesky post; posting tweet %s as standalone",
                    tweet.reply_to_tweet_id, tweet.id,
                )
            else:
                parent_ref = parent_thread.tip
                conv_thread = threads.get(tweet.conversation_id or tweet.reply_to_tweet_id)
                root_ref = conv_thread.root if conv_thread is not None else parent_thread.root

        # For self-quotes, embed the existing Bluesky post natively; if the
        # quoted tweet isn't mapped, post() falls back to a link card.
        quoted_ref: BlueskyPostRef | None = None
        if tweet.quoted_tweet is not None:
            quoted_thread = threads.get(tweet.quoted_tweet.id)
            if quoted_thread is not None:
                quoted_ref = quoted_thread.root

        try:
            thread = bluesky.post(
                tweet, parent_ref=parent_ref, root_ref=root_ref, quoted_ref=quoted_ref,
            )
        except Exception:
            log.exception("Failed to post tweet %s to Bluesky", tweet.id)
            break
        threads[tweet.id] = thread
        post_map[tweet.id] = {
            "root": {"uri": thread.root.uri, "cid": thread.root.cid},
            "tip": {"uri": thread.tip.uri, "cid": thread.tip.cid},
        }
        new_count += 1

    save_post_map(post_map)
    log.info("Done — %d new post(s)", new_count)


if __name__ == "__main__":
    main()