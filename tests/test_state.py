from __future__ import annotations

import json
from pathlib import Path

import pytest

from bot import config
from bot.state import (
    load_pin_audit_date,
    load_pinned_post,
    load_post_map,
    load_seen,
    load_twitter_user_id,
    save_pin_audit_date,
    save_pinned_post,
    save_post_map,
    save_twitter_user_id,
)

pytestmark = pytest.mark.unit


def _ref(uri: str, cid: str) -> dict:
    return {"uri": uri, "cid": cid}


def _record(root_uri: str, tip_uri: str | None = None) -> dict:
    tip_uri = tip_uri or root_uri
    return {"root": _ref(root_uri, "c-" + root_uri), "tip": _ref(tip_uri, "c-" + tip_uri)}


class TestLoadSeen:
    def test_new_format(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        state.write_text(json.dumps({"posts": {"1": None, "2": _record("at://2"), "3": None}}))
        config.cfg.STATE_FILE = str(state)

        result = load_seen()
        assert result == {"1", "2", "3"}

    def test_legacy_seen_ids_key(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        state.write_text(json.dumps({"seen_ids": ["1", "2", "3"]}))
        config.cfg.STATE_FILE = str(state)

        result = load_seen()
        assert result == {"1", "2", "3"}

    def test_legacy_list_format(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        state.write_text(json.dumps(["10", "20"]))
        config.cfg.STATE_FILE = str(state)

        result = load_seen()
        assert result == {"10", "20"}

    def test_missing_file(self, tmp_path: Path) -> None:
        config.cfg.STATE_FILE = str(tmp_path / "missing.json")
        assert load_seen() == set()

    def test_corrupt_json(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        state.write_text("{bad json")
        config.cfg.STATE_FILE = str(state)

        assert load_seen() == set()

    def test_empty_posts_key(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        state.write_text(json.dumps({"posts": {}}))
        config.cfg.STATE_FILE = str(state)

        assert load_seen() == set()


class TestLoadPostMap:
    def test_new_format(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        rec = _record("at://did/post/2")
        state.write_text(json.dumps({"posts": {"1": None, "2": rec}}))
        config.cfg.STATE_FILE = str(state)

        result = load_post_map()
        assert result == {"1": None, "2": rec}

    def test_legacy_seen_ids_migrates_to_unmapped(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        state.write_text(json.dumps({"seen_ids": ["1", "2"]}))
        config.cfg.STATE_FILE = str(state)

        assert load_post_map() == {"1": None, "2": None}

    def test_legacy_list_migrates_to_unmapped(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        state.write_text(json.dumps(["10", "20"]))
        config.cfg.STATE_FILE = str(state)

        assert load_post_map() == {"10": None, "20": None}

    def test_missing_file(self, tmp_path: Path) -> None:
        config.cfg.STATE_FILE = str(tmp_path / "missing.json")
        assert load_post_map() == {}


class TestSavePostMap:
    def test_basic_save(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        config.cfg.STATE_FILE = str(state)

        rec = _record("at://did/post/2")
        save_post_map({"1": None, "2": rec})

        data = json.loads(state.read_text())
        assert data["posts"] == {"1": None, "2": rec}

    def test_roundtrip(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        config.cfg.STATE_FILE = str(state)

        mapping = {"1": _record("at://did/post/1"), "2": None}
        save_post_map(mapping)
        assert load_post_map() == mapping

    def test_caps_at_max(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        config.cfg.STATE_FILE = str(state)
        original_max = config.cfg.MAX_SEEN_IDS
        config.cfg.MAX_SEEN_IDS = 5

        try:
            mapping = {str(i): None for i in range(1, 21)}
            save_post_map(mapping)

            data = json.loads(state.read_text())
            assert len(data["posts"]) == 5
            # Should keep the 5 highest numeric IDs
            assert sorted(data["posts"], key=int, reverse=True) == ["20", "19", "18", "17", "16"]
        finally:
            config.cfg.MAX_SEEN_IDS = original_max

    def test_preserves_twitter_user_id(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        state.write_text(json.dumps({
            "posts": {"1": None},
            "twitter_user_id": "99999",
        }))
        config.cfg.STATE_FILE = str(state)

        save_post_map({"1": None, "2": None})

        data = json.loads(state.read_text())
        assert data["twitter_user_id"] == "99999"
        assert set(data["posts"]) == {"1", "2"}

    def test_migrates_legacy_list(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        state.write_text(json.dumps(["1", "2"]))
        config.cfg.STATE_FILE = str(state)

        save_post_map({"1": None, "2": None, "3": _record("at://did/post/3")})

        data = json.loads(state.read_text())
        assert "seen_ids" not in data
        assert set(data["posts"]) == {"1", "2", "3"}

    def test_drops_legacy_seen_ids_key(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        state.write_text(json.dumps({"seen_ids": ["1", "2"], "twitter_user_id": "5"}))
        config.cfg.STATE_FILE = str(state)

        save_post_map({"1": None, "2": None})

        data = json.loads(state.read_text())
        assert "seen_ids" not in data
        assert data["twitter_user_id"] == "5"

    def test_creates_file_if_missing(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        config.cfg.STATE_FILE = str(state)

        save_post_map({"1": None})

        assert state.exists()
        data = json.loads(state.read_text())
        assert data["posts"] == {"1": None}


class TestTwitterUserIdCache:
    def test_roundtrip(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        state.write_text(json.dumps({"posts": {}}))
        config.cfg.STATE_FILE = str(state)

        save_twitter_user_id("12345")
        assert load_twitter_user_id() == "12345"

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        config.cfg.STATE_FILE = str(tmp_path / "missing.json")
        assert load_twitter_user_id() is None

    def test_legacy_format_returns_none(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        state.write_text(json.dumps(["1", "2"]))
        config.cfg.STATE_FILE = str(state)

        assert load_twitter_user_id() is None

    def test_save_preserves_posts(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        state.write_text(json.dumps({"posts": {"10": None, "20": None}}))
        config.cfg.STATE_FILE = str(state)

        save_twitter_user_id("99999")

        data = json.loads(state.read_text())
        assert data["twitter_user_id"] == "99999"
        assert set(data["posts"]) == {"10", "20"}

    def test_save_with_legacy_format_migrates(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        state.write_text(json.dumps(["10", "20"]))
        config.cfg.STATE_FILE = str(state)

        save_twitter_user_id("99999")

        data = json.loads(state.read_text())
        assert data["twitter_user_id"] == "99999"
        assert set(data["posts"]) == {"10", "20"}


class TestPinAuditDate:
    def test_roundtrip(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        state.write_text(json.dumps({"posts": {}}))
        config.cfg.STATE_FILE = str(state)

        save_pin_audit_date("2026-07-18")
        assert load_pin_audit_date() == "2026-07-18"

    def test_missing_returns_none(self, tmp_path: Path) -> None:
        config.cfg.STATE_FILE = str(tmp_path / "missing.json")
        assert load_pin_audit_date() is None

    def test_save_preserves_posts(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        state.write_text(json.dumps({"posts": {"1": None}}))
        config.cfg.STATE_FILE = str(state)

        save_pin_audit_date("2026-07-18")

        data = json.loads(state.read_text())
        assert data["pin_audit_date"] == "2026-07-18"
        assert set(data["posts"]) == {"1"}


class TestPinnedPost:
    def test_roundtrip(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        state.write_text(json.dumps({"posts": {}}))
        config.cfg.STATE_FILE = str(state)

        record = {"tweet_id": "42", "uri": "at://did/post/42", "cid": "c42"}
        save_pinned_post(record)
        assert load_pinned_post() == record

    def test_missing_returns_none(self, tmp_path: Path) -> None:
        config.cfg.STATE_FILE = str(tmp_path / "missing.json")
        assert load_pinned_post() is None

    def test_save_none_clears(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        state.write_text(json.dumps({
            "posts": {},
            "pinned_post": {"tweet_id": "42", "uri": "at://x", "cid": "c"},
        }))
        config.cfg.STATE_FILE = str(state)

        save_pinned_post(None)
        assert load_pinned_post() is None

    def test_save_preserves_posts_and_user_id(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        state.write_text(json.dumps({
            "posts": {"1": None},
            "twitter_user_id": "99999",
        }))
        config.cfg.STATE_FILE = str(state)

        record = {"tweet_id": "1", "uri": "at://did/post/1", "cid": "c1"}
        save_pinned_post(record)

        data = json.loads(state.read_text())
        assert data["pinned_post"] == record
        assert data["twitter_user_id"] == "99999"
        assert set(data["posts"]) == {"1"}
