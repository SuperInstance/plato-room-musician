"""Tests for plato_room_musician.mapping — RoomMapper, TileMapper, CATEGORY_CONFIG."""
import pytest
from plato_room_musician.mapping import (
    RoomMapper,
    TileMapper,
    CATEGORY_CONFIG,
    DEFAULT_CONFIG,
    _hash_to_range,
    _category_from_name,
)


# ── RoomMapper.channel_for ──

class TestRoomMapperChannel:
    def test_channel_in_range(self):
        rm = RoomMapper()
        ch = rm.channel_for("forgemaster-cadence")
        assert 0 <= ch <= 15

    def test_deterministic_same_name(self):
        rm = RoomMapper()
        ch1 = rm.channel_for("session-ambient")
        ch2 = rm.channel_for("session-ambient")
        assert ch1 == ch2

    def test_different_names_different_channels(self):
        rm = RoomMapper()
        names = [f"room-{i:04d}" for i in range(16)]
        channels = [rm.channel_for(n) for n in names]
        # With collision resolution, all 16 rooms should get unique channels
        assert len(set(channels)) == 16

    def test_fewer_than_16_unique(self):
        rm = RoomMapper()
        channels = set()
        for i in range(8):
            channels.add(rm.channel_for(f"room-{i}"))
        assert len(channels) == 8


# ── RoomMapper.config_for ──

class TestRoomMapperConfig:
    def test_forgemaster_config(self):
        rm = RoomMapper()
        cfg = rm.config_for("forgemaster-cadence")
        assert cfg["register"] == (36, 52)
        assert cfg["scale"] == [0, 2, 3, 5, 7, 8, 10]  # minor blues

    def test_session_config(self):
        rm = RoomMapper()
        cfg = rm.config_for("session-deep-dive")
        assert cfg["register"] == (48, 67)
        assert cfg["scale"] == [0, 2, 4, 5, 7, 9, 11]  # major

    def test_fleet_config(self):
        rm = RoomMapper()
        cfg = rm.config_for("fleet-coord")
        assert cfg["register"] == (35, 50)
        assert cfg["scale"] == [0, 2, 4, 7, 9]  # pentatonic

    def test_knowledge_config(self):
        rm = RoomMapper()
        cfg = rm.config_for("knowledge-archive")
        assert cfg["register"] == (72, 96)
        # whole-tone + Lydian
        assert 6 in cfg["scale"]  # tritone for whole-tone flavor

    def test_constraint_config(self):
        rm = RoomMapper()
        cfg = rm.config_for("constraint-checker")
        assert cfg["register"] == (24, 43)
        assert cfg["scale"] == [0, 2, 4, 5, 7, 9, 10]  # Mixolydian

    def test_unknown_category_returns_session_default(self):
        rm = RoomMapper()
        cfg = rm.config_for("xyzzy-plugh")
        # Unknown rooms fall through to "session" via _category_from_name
        assert cfg["register"] == CATEGORY_CONFIG["session"]["register"]
        assert cfg["scale"] == CATEGORY_CONFIG["session"]["scale"]


# ── TileMapper.map_tile ──

class TestTileMapper:
    @pytest.fixture()
    def sample_tile(self):
        return {
            "tile_id": "test-tile-001",
            "timestamp": 10.0,
            "confidence": 0.8,
            "agent": "forge-agent",
            "answer": "A moderately long answer for duration mapping.",
            "question": "Q: test?",
        }

    def test_map_tile_has_required_keys(self, sample_tile):
        tm = TileMapper()
        result = tm.map_tile("forgemaster-cadence", sample_tile)
        required = {"pitch", "velocity", "onset_beats", "duration_beats", "channel", "patch",
                     "room", "agent", "category", "rhythmic_role", "tile_id"}
        assert required.issubset(result.keys())

    def test_velocity_from_confidence(self):
        tm = TileMapper()
        tile_low = {"tile_id": "lo", "timestamp": 0.0, "confidence": 0.0, "agent": "a"}
        tile_high = {"tile_id": "hi", "timestamp": 0.0, "confidence": 1.0, "agent": "a"}
        r_low = tm.map_tile("session-test", tile_low)
        r_high = tm.map_tile("session-test", tile_high)
        assert r_low["velocity"] == 1   # max(1, int(0.0 * 127))
        assert r_high["velocity"] == 127

    def test_pitch_within_register(self, sample_tile):
        tm = TileMapper()
        for room_name in ["forgemaster-cadence", "session-ambient", "knowledge-archive",
                          "fleet-coord", "constraint-checker"]:
            cfg = tm.room_mapper.config_for(room_name)
            result = tm.map_tile(room_name, sample_tile)
            lo, hi = cfg["register"]
            assert lo <= result["pitch"] < hi, f"pitch {result['pitch']} out of [{lo},{hi}) for {room_name}"

    def test_deterministic(self, sample_tile):
        tm = TileMapper()
        r1 = tm.map_tile("forgemaster-cadence", sample_tile)
        r2 = tm.map_tile("forgemaster-cadence", sample_tile)
        assert r1["pitch"] == r2["pitch"]
        assert r1["velocity"] == r2["velocity"]
        assert r1["duration_beats"] == r2["duration_beats"]

    def test_duration_bounded(self, sample_tile):
        tm = TileMapper()
        # Very short answer
        tile_short = {**sample_tile, "answer": "x"}
        r = tm.map_tile("session-test", tile_short)
        assert r["duration_beats"] >= 0.25
        # Very long answer
        tile_long = {**sample_tile, "answer": "x" * 1000}
        r = tm.map_tile("session-test", tile_long)
        assert r["duration_beats"] <= 4.0


# ── _hash_to_range ──

class TestHashToRange:
    def test_deterministic(self):
        v1 = _hash_to_range("hello", 0, 100)
        v2 = _hash_to_range("hello", 0, 100)
        assert v1 == v2

    def test_stays_in_range(self):
        for s in ["a", "b", "test", "longer string here", "🤖"]:
            val = _hash_to_range(s, 5, 10)
            assert 5 <= val < 10

    def test_different_strings_differ(self):
        vals = {_hash_to_range(f"s-{i}", 0, 1000) for i in range(20)}
        # Very unlikely all 20 hash to same value
        assert len(vals) > 1


# ── _category_from_name ──

class TestCategoryFromName:
    def test_prefix_match(self):
        assert _category_from_name("forgemaster-cadence") == "forgemaster"
        assert _category_from_name("session-deep") == "session"
        assert _category_from_name("fleet-nav") == "fleet"

    def test_midstring_match(self):
        assert _category_from_name("my-forgemaster-room") == "forgemaster"

    def test_no_match_defaults_session(self):
        assert _category_from_name("unknown-xyz") == "session"
