from __future__ import annotations

import logging
from datetime import datetime, timezone

from dotenv import load_dotenv

from bot import config
from bot.bluesky_client import BlueskyClient, BlueskyPostRef, PostedThread
from bot.state import (
    load_pin_audit_date,
    load_pinned_post,
    load_post_map,
    save_pin_audit_date,
    save_pinned_post,
    save_post_map,
)
from bot.twitter_client import TwitterClient

log = logging.getLogger(__name__)


def _today_utc() -> str:
    """Return today's date (UTC) as an ISO ``YYYY-MM-DD`` string."""
    return datetime.now(timezone.utc).date().isoformat()


def _thread_from_record(record: dict) -> PostedThread:
    """Rebuild a ``PostedThread`` from a persisted post-map record."""
    return PostedThread(
        root=BlueskyPostRef(**record["root"]),
        tip=BlueskyPostRef(**record["tip"]),
    )


def reconcile_pinned_post(
    twitter: TwitterClient,
    bluesky: BlueskyClient,
    threads: dict[str, PostedThread],
    pinned_state: dict | None,
) -> dict | None:
    """Mirror the account's Twitter pinned tweet to the Bluesky pinned post.

    Resolves the current pinned tweet through *threads* (the tweet → post
    mapping).  Fully mirrors Twitter: pins the mapped post, replaces it when
    the pin changes, and unpins when Twitter has no pinned tweet.  A pinned
    tweet with no known Bluesky post (e.g. aged out of the mapping) is skipped
    with a warning, leaving the current pin unchanged.  Returns the pinned-post
    state to persist (unchanged when no write was needed).
    """
    pinned_tweet_id = twitter.fetch_pinned_tweet_id()

    if pinned_tweet_id is None:
        desired_ref: BlueskyPostRef | None = None
        desired_state: dict | None = None
    else:
        thread = threads.get(pinned_tweet_id)
        if thread is None:
            log.warning(
                "Pinned tweet %s is not mapped to a Bluesky post; leaving pin unchanged",
                pinned_tweet_id,
            )
            return pinned_state
        desired_ref = thread.root
        desired_state = {
            "tweet_id": pinned_tweet_id,
            "uri": desired_ref.uri,
            "cid": desired_ref.cid,
        }

    # Compare against the stored pin to avoid redundant profile writes.
    current_uri = pinned_state.get("uri") if pinned_state else None
    desired_uri = desired_state.get("uri") if desired_state else None
    if current_uri == desired_uri:
        return pinned_state

    bluesky.set_pinned_post(desired_ref)
    return desired_state


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
    tweets = twitter.fetch_recent_tweets(max_results=config.cfg.TWITTER_MAX_RESULTS)

    # Combined lookup of tweet ID → PostedThread, seeded from the persisted
    # mapping and extended with posts made during this run. This lets replies
    # and quotes reference posts the bot made in earlier runs, not just the
    # current batch.
    threads: dict[str, PostedThread] = {
        tid: _thread_from_record(rec)
        for tid, rec in post_map.items()
        if rec is not None
    }

    # Pre-build a set of tweet IDs that have a reply in the current fetch batch.  This lets
    # edit-detection identify thread-root edits even when the downstream reply hasn't been
    # mirrored yet (i.e. both tweets appear in the same run for the first time).
    current_batch_reply_targets: set[str] = {
        t.reply_to_tweet_id for t in tweets if t.reply_to_tweet_id
    }

    new_count = 0
    for tweet in tweets:
        if tweet.id in post_map:
            continue

        # Detect edits: check if any prior version of this tweet was already mirrored
        replaced_id: str | None = None
        if config.cfg.EDIT_SYNC_ENABLED and len(tweet.edit_history_tweet_ids) > 1:
            for prev_id in tweet.edit_history_tweet_ids[:-1]:  # all IDs except the current one
                if prev_id in post_map:
                    replaced_id = prev_id
                    break

        if replaced_id is not None:
            # Check for downstream replies before deciding what to do.
            # 1. Historical: any previously-mirrored tweet recorded as a reply to the original.
            # 2. Current batch: any tweet in this run's fetch that replies to the original.
            has_downstream_replies = (
                any(
                    isinstance(rec, dict) and rec.get("reply_to") == replaced_id
                    for rec in post_map.values()
                )
                or replaced_id in current_batch_reply_targets
            )

            if has_downstream_replies:
                # Deleting the original Bluesky post would orphan the existing reply chain.
                # Leave the original intact and mark the edit as seen so it is never retried.
                log.warning(
                    "Tweet %s is an edit of %s but the original has downstream replies on Bluesky; "
                    "skipping edit to preserve thread continuity",
                    tweet.id, replaced_id,
                )
                post_map[tweet.id] = None  # mark seen; prevents re-processing on future runs
                continue

            log.info(
                "Tweet %s is an edit of previously-mirrored tweet %s — deleting original Bluesky post",
                tweet.id, replaced_id,
            )
            original_rec = post_map.get(replaced_id)
            if original_rec is not None:
                if original_rec.get("root") and original_rec["root"].get("uri"):
                    try:
                        bluesky.delete_post(original_rec["root"]["uri"])
                    except Exception:
                        log.exception(
                            "Failed to delete original Bluesky post for replaced tweet %s; "
                            "proceeding to mirror edit anyway",
                            replaced_id,
                        )
                else:
                    log.warning(
                        "Original tweet %s has no mapped Bluesky URI; skipping deletion",
                        replaced_id,
                    )
            del post_map[replaced_id]
            threads.pop(replaced_id, None)

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
            "reply_to": tweet.reply_to_tweet_id,  # None for standalone posts; used for edit detection
        }
        new_count += 1

    save_post_map(post_map)
    log.info("Done — %d new post(s)", new_count)

    if config.cfg.PIN_SYNC_ENABLED:
        today = _today_utc()
        if load_pin_audit_date() != today:
            log.info("Running daily pinned-post reconcile")
            try:
                pinned_state = reconcile_pinned_post(
                    twitter, bluesky, threads, load_pinned_post(),
                )
                save_pinned_post(pinned_state)
                save_pin_audit_date(today)
            except Exception:
                log.exception("Pinned-post reconcile failed")


if __name__ == "__main__":
    main()