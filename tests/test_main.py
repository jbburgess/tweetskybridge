from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from bot.bluesky_client import BlueskyPostRef, PostedThread
from main import reconcile_pinned_post

pytestmark = pytest.mark.unit


def _thread(uri: str, cid: str = "c") -> PostedThread:
    ref = BlueskyPostRef(uri=uri, cid=cid)
    return PostedThread(root=ref, tip=ref)


class TestReconcilePinnedPost:
    def test_pins_mapped_tweet_when_none_pinned_before(self) -> None:
        twitter = MagicMock()
        twitter.fetch_pinned_tweet_id.return_value = "42"
        bluesky = MagicMock()
        threads = {"42": _thread("at://did/post/42", "cid42")}

        result = reconcile_pinned_post(twitter, bluesky, threads, None)

        bluesky.set_pinned_post.assert_called_once()
        ref = bluesky.set_pinned_post.call_args.args[0]
        assert ref.uri == "at://did/post/42"
        assert result == {"tweet_id": "42", "uri": "at://did/post/42", "cid": "cid42"}

    def test_noop_when_pin_unchanged(self) -> None:
        twitter = MagicMock()
        twitter.fetch_pinned_tweet_id.return_value = "42"
        bluesky = MagicMock()
        threads = {"42": _thread("at://did/post/42", "cid42")}
        state = {"tweet_id": "42", "uri": "at://did/post/42", "cid": "cid42"}

        result = reconcile_pinned_post(twitter, bluesky, threads, state)

        bluesky.set_pinned_post.assert_not_called()
        assert result == state

    def test_replaces_when_pin_changes(self) -> None:
        twitter = MagicMock()
        twitter.fetch_pinned_tweet_id.return_value = "99"
        bluesky = MagicMock()
        threads = {
            "42": _thread("at://did/post/42", "cid42"),
            "99": _thread("at://did/post/99", "cid99"),
        }
        state = {"tweet_id": "42", "uri": "at://did/post/42", "cid": "cid42"}

        result = reconcile_pinned_post(twitter, bluesky, threads, state)

        bluesky.set_pinned_post.assert_called_once()
        ref = bluesky.set_pinned_post.call_args.args[0]
        assert ref.uri == "at://did/post/99"
        assert result == {"tweet_id": "99", "uri": "at://did/post/99", "cid": "cid99"}

    def test_unpins_when_twitter_has_no_pin(self) -> None:
        twitter = MagicMock()
        twitter.fetch_pinned_tweet_id.return_value = None
        bluesky = MagicMock()
        state = {"tweet_id": "42", "uri": "at://did/post/42", "cid": "cid42"}

        result = reconcile_pinned_post(twitter, bluesky, {}, state)

        bluesky.set_pinned_post.assert_called_once_with(None)
        assert result is None

    def test_noop_when_already_unpinned(self) -> None:
        twitter = MagicMock()
        twitter.fetch_pinned_tweet_id.return_value = None
        bluesky = MagicMock()

        result = reconcile_pinned_post(twitter, bluesky, {}, None)

        bluesky.set_pinned_post.assert_not_called()
        assert result is None

    def test_skips_unmapped_pin_leaving_state_unchanged(self) -> None:
        twitter = MagicMock()
        twitter.fetch_pinned_tweet_id.return_value = "500"  # aged out of mapping
        bluesky = MagicMock()
        state = {"tweet_id": "42", "uri": "at://did/post/42", "cid": "cid42"}

        result = reconcile_pinned_post(twitter, bluesky, {}, state)

        bluesky.set_pinned_post.assert_not_called()
        assert result == state
