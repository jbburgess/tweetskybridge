from __future__ import annotations

import json
from pathlib import Path

import pytest

from bot import config
from bot.state import load_seen, load_twitter_user_id, save_seen, save_twitter_user_id

pytestmark = pytest.mark.unit


class TestLoadSeen:
    def test_new_format(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        state.write_text(json.dumps({"seen_ids": ["1", "2", "3"]}))
        config.STATE_FILE = str(state)

        result = load_seen()
        assert result == {"1", "2", "3"}

    def test_legacy_format(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        state.write_text(json.dumps(["10", "20"]))
        config.STATE_FILE = str(state)

        result = load_seen()
        assert result == {"10", "20"}

    def test_missing_file(self, tmp_path: Path) -> None:
        config.STATE_FILE = str(tmp_path / "missing.json")
        assert load_seen() == set()

    def test_corrupt_json(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        state.write_text("{bad json")
        config.STATE_FILE = str(state)

        assert load_seen() == set()

    def test_empty_seen_ids_key(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        state.write_text(json.dumps({"seen_ids": []}))
        config.STATE_FILE = str(state)

        assert load_seen() == set()


class TestSaveSeen:
    def test_basic_save(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        config.STATE_FILE = str(state)

        save_seen({"1", "2", "3"})

        data = json.loads(state.read_text())
        assert set(data["seen_ids"]) == {"1", "2", "3"}

    def test_caps_at_max(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        config.STATE_FILE = str(state)
        original_max = config.MAX_SEEN_IDS
        config.MAX_SEEN_IDS = 5

        try:
            ids = {str(i) for i in range(1, 21)}
            save_seen(ids)

            data = json.loads(state.read_text())
            assert len(data["seen_ids"]) == 5
            # Should keep the 5 highest numeric IDs
            assert data["seen_ids"] == ["20", "19", "18", "17", "16"]
        finally:
            config.MAX_SEEN_IDS = original_max

    def test_preserves_extra_fields(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        state.write_text(json.dumps({
            "seen_ids": ["1"],
            "twitter_user_id": "99999",
        }))
        config.STATE_FILE = str(state)

        save_seen({"1", "2"})

        data = json.loads(state.read_text())
        assert data["twitter_user_id"] == "99999"
        assert set(data["seen_ids"]) == {"1", "2"}

    def test_migrates_legacy_format(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        state.write_text(json.dumps(["1", "2"]))
        config.STATE_FILE = str(state)

        save_seen({"1", "2", "3"})

        data = json.loads(state.read_text())
        assert "seen_ids" in data
        assert set(data["seen_ids"]) == {"1", "2", "3"}

    def test_creates_file_if_missing(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        config.STATE_FILE = str(state)

        save_seen({"1"})

        assert state.exists()
        data = json.loads(state.read_text())
        assert data["seen_ids"] == ["1"]


class TestTwitterUserIdCache:
    def test_roundtrip(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        state.write_text(json.dumps({"seen_ids": []}))
        config.STATE_FILE = str(state)

        save_twitter_user_id("12345")
        assert load_twitter_user_id() == "12345"

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        config.STATE_FILE = str(tmp_path / "missing.json")
        assert load_twitter_user_id() is None

    def test_legacy_format_returns_none(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        state.write_text(json.dumps(["1", "2"]))
        config.STATE_FILE = str(state)

        assert load_twitter_user_id() is None

    def test_save_preserves_seen_ids(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        state.write_text(json.dumps({"seen_ids": ["10", "20"]}))
        config.STATE_FILE = str(state)

        save_twitter_user_id("99999")

        data = json.loads(state.read_text())
        assert data["twitter_user_id"] == "99999"
        assert data["seen_ids"] == ["10", "20"]

    def test_save_with_legacy_format_migrates(self, tmp_path: Path) -> None:
        state = tmp_path / "state.json"
        state.write_text(json.dumps(["10", "20"]))
        config.STATE_FILE = str(state)

        save_twitter_user_id("99999")

        data = json.loads(state.read_text())
        assert data["twitter_user_id"] == "99999"
        assert data["seen_ids"] == ["10", "20"]
