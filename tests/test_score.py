"""Tests for plato_room_musician.score — NoteEvent, PlatoScore, chords, rests."""
import pytest
from plato_room_musician.score import NoteEvent, PlatoScore


def _make_event(room="room-a", ch=0, pitch=60, vel=100, onset=0.0, dur=1.0,
                patch=0, agent="ag", category="session", tile_id="t1"):
    return NoteEvent(room=room, channel=ch, pitch=pitch, velocity=vel,
                     onset_beats=onset, duration_beats=dur, patch=patch,
                     agent=agent, category=category, tile_id=tile_id)


class TestNoteEvent:
    def test_end_beats(self):
        ev = _make_event(onset=2.0, dur=1.5)
        assert ev.end_beats == 3.5

    def test_as_dict_keys(self):
        ev = _make_event()
        d = ev.as_dict()
        assert "pitch" in d and "velocity" in d and "room" in d


class TestPlatoScoreConstruction:
    def test_from_mapped_tiles(self):
        mapped = [{
            "room": "session-test", "channel": 0, "pitch": 60, "velocity": 80,
            "onset_beats": 0.0, "duration_beats": 1.0, "patch": 0,
            "agent": "ag", "category": "session", "tile_id": "t1",
        }]
        score = PlatoScore.from_mapped_tiles(mapped)
        assert len(score.events) == 1
        assert score.events[0].pitch == 60


class TestChordDetection:
    def test_simultaneous_notes_are_chord(self):
        events = [
            _make_event(room="room-a", onset=0.0, pitch=60),
            _make_event(room="room-b", onset=0.1, pitch=64),
        ]
        score = PlatoScore(events, chord_window_beats=0.5)
        chords = score.find_chords()
        assert len(chords) >= 1
        assert "room-a" in chords[0]["rooms"]
        assert "room-b" in chords[0]["rooms"]

    def test_no_chord_for_single_note(self):
        events = [_make_event(room="room-a", onset=0.0)]
        score = PlatoScore(events)
        chords = score.find_chords()
        assert len(chords) == 0

    def test_chord_has_type(self):
        events = [
            _make_event(room="room-a", onset=0.0, pitch=60),
            _make_event(room="room-b", onset=0.1, pitch=64),
            _make_event(room="room-c", onset=0.2, pitch=67),
        ]
        score = PlatoScore(events, chord_window_beats=0.5)
        chords = score.find_chords()
        assert len(chords) >= 1
        assert "type" in chords[0]


class TestRestDetection:
    def test_gap_creates_rest(self):
        events = [
            _make_event(room="room-a", onset=0.0, dur=1.0),
            _make_event(room="room-a", onset=5.0, dur=1.0),
        ]
        score = PlatoScore(events, rest_threshold_beats=2.0)
        rests = score.find_rests()
        assert len(rests) >= 1
        assert rests[0]["duration_beats"] >= 2.0

    def test_no_rest_when_continuous(self):
        events = [
            _make_event(room="room-a", onset=0.0, dur=1.0),
            _make_event(room="room-a", onset=1.5, dur=1.0),
        ]
        score = PlatoScore(events, rest_threshold_beats=2.0)
        rests = score.find_rests()
        assert len(rests) == 0


class TestDeadband:
    def test_deadband_filters_redundant(self):
        events = [
            _make_event(room="room-a", onset=0.0, pitch=60, vel=80),
            _make_event(room="room-a", onset=1.0, pitch=60, vel=80),  # same
            _make_event(room="room-a", onset=2.0, pitch=72, vel=100),  # different
        ]
        score = PlatoScore(events, deadband_semitones=2, deadband_velocity=10)
        score.apply_deadband()
        assert len(score.events) == 2  # first + changed


class TestSummary:
    def test_summary_keys(self):
        events = [
            _make_event(room="room-a", onset=0.0, dur=2.0),
            _make_event(room="room-b", onset=0.5, dur=1.0),
        ]
        score = PlatoScore(events, chord_window_beats=1.0)
        s = score.summary()
        assert "rooms" in s
        assert "total_events" in s
        assert s["total_events"] == 2
