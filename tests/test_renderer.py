"""Tests for plato_room_musician.renderer — MidiRenderer, TensorMidiRenderer, VMSRenderer."""
import json
import pytest
import mido

from plato_room_musician.score import NoteEvent, PlatoScore
from plato_room_musician.renderer import MidiRenderer, TensorMidiRenderer, TensorMIDIEvent, VMSRenderer


def _make_score(n_events=4):
    events = [
        NoteEvent(
            room=f"room-{i % 2}",
            channel=i % 3,
            pitch=60 + i * 4,
            velocity=80 + i * 10,
            onset_beats=float(i),
            duration_beats=0.5,
            patch=i % 4,
            agent=f"agent-{i}",
            category="session",
            tile_id=f"t{i}",
        )
        for i in range(n_events)
    ]
    return PlatoScore(events)


class TestMidiRenderer:
    def test_renders_valid_midi(self):
        score = _make_score()
        renderer = MidiRenderer()
        mid = renderer.render(score)
        assert isinstance(mid, mido.MidiFile)
        # Track 0 = meta, rest = channel tracks
        assert len(mid.tracks) >= 2  # meta + at least one channel

    def test_save_and_load(self, tmp_path):
        score = _make_score()
        renderer = MidiRenderer()
        path = str(tmp_path / "test.mid")
        mid = renderer.render(score, output_path=path)
        loaded = mido.MidiFile(path)
        assert loaded.ticks_per_beat == mid.ticks_per_beat

    def test_empty_score_still_valid(self):
        score = PlatoScore([])
        renderer = MidiRenderer()
        mid = renderer.render(score)
        assert isinstance(mid, mido.MidiFile)
        # Only meta track
        assert len(mid.tracks) == 1

    def test_tempo_set(self):
        score = _make_score(1)
        renderer = MidiRenderer(tempo_bpm=140.0)
        mid = renderer.render(score)
        meta = mid.tracks[0]
        tempo_msgs = [m for m in meta if m.type == "set_tempo"]
        assert len(tempo_msgs) == 1
        assert abs(mido.tempo2bpm(tempo_msgs[0].tempo) - 140.0) < 1.0


class TestTensorMidiRenderer:
    def test_render_produces_events(self):
        score = _make_score(3)
        renderer = TensorMidiRenderer()
        events = renderer.render(score)
        assert len(events) == 3
        assert all(isinstance(e, TensorMIDIEvent) for e in events)

    def test_to_bytes_length(self):
        score = _make_score(2)
        renderer = TensorMidiRenderer()
        data = renderer.render_to_bytes(score)
        assert len(data) == 8  # 2 events × 4 bytes

    def test_render_to_json_valid(self):
        score = _make_score(2)
        renderer = TensorMidiRenderer()
        j = renderer.render_to_json(score)
        parsed = json.loads(j)
        assert len(parsed) == 2
        assert "cos_int8" in parsed[0]


class TestTensorMIDIEvent:
    def test_from_note_event_fields(self):
        note = NoteEvent("room-a", 0, 60, 100, 1.0, 1.0, 0, "ag", "session", "t1")
        ev = TensorMIDIEvent.from_note_event(note)
        assert -128 <= ev.cos_int8 <= 127
        assert -128 <= ev.sin_int8 <= 127
        assert 0 <= ev.beat_k <= 255
        assert 0 <= ev.state_byte <= 255

    def test_to_bytes_roundtrip(self):
        note = NoteEvent("room-a", 2, 64, 80, 0.5, 1.0, 5, "ag", "session", "t1")
        ev = TensorMIDIEvent.from_note_event(note)
        b = ev.to_bytes()
        assert len(b) == 4


class TestVMSRenderer:
    def test_render_structure(self):
        score = _make_score(3)
        renderer = VMSRenderer()
        result = renderer.render(score)
        assert "glyphs" in result
        assert "width" in result
        assert "height" in result
        assert result["version"] == "v1"

    def test_glyphs_have_notes(self):
        score = _make_score(3)
        renderer = VMSRenderer()
        result = renderer.render(score)
        notes = [g for g in result["glyphs"] if g["type"] == "note"]
        assert len(notes) == 3
