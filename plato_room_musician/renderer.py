"""
Renderers: MIDI file, Tensor-MIDI, and Visual Music Score (VMS).

All formats encode the same underlying score — the fleet singing.
"""
from __future__ import annotations
import json
import math
from dataclasses import dataclass
from typing import Sequence

import mido

from plato_room_musician.score import NoteEvent, PlatoScore


# ── Tensor-MIDI 4-byte event ──

@dataclass(frozen=True, slots=True)
class TensorMIDIEvent:
    """4-byte Tensor-MIDI event.

    Matches the spec from Tensor-MIDI Deep Synthesis:
        cos_int8 : phase direction X (saturated)
        sin_int8 : phase direction Y (saturated)
        beat_k   : beat counter 0-255 (wraps)
        state_byte: agent state as INT8
    """
    cos_int8: int
    sin_int8: int
    beat_k: int
    state_byte: int

    def to_bytes(self) -> bytes:
        return bytes([
            self.cos_int8 & 0xFF,
            self.sin_int8 & 0xFF,
            self.beat_k & 0xFF,
            self.state_byte & 0xFF,
        ])

    def to_dict(self) -> dict:
        return {
            "cos_int8": self.cos_int8,
            "sin_int8": self.sin_int8,
            "beat_k": self.beat_k,
            "state_byte": self.state_byte,
        }

    @classmethod
    def from_note_event(cls, note: NoteEvent, beat_resolution: int = 24) -> "TensorMIDIEvent":
        """Encode a NoteEvent into a TensorMIDIEvent.

        Phase direction derives from pitch circle:
            X = cos(2π * pitch/12)
            Y = sin(2π * pitch/12)
        Beat counter quantizes onset to ticks.
        State byte encodes (channel << 4) | (velocity >> 3).
        """
        angle = 2.0 * math.pi * (note.pitch % 12) / 12.0
        cos_f = math.cos(angle) * 127.0
        sin_f = math.sin(angle) * 127.0

        # INT8 saturation (clamp, don't wrap)
        cos_i = max(-128, min(127, int(cos_f)))
        sin_i = max(-128, min(127, int(sin_f)))

        beat_k = int(note.onset_beats * beat_resolution) % 256

        # State byte: high nibble = channel, low nibble = velocity/8
        state = ((note.channel & 0x0F) << 4) | ((note.velocity >> 3) & 0x0F)

        return cls(cos_int8=cos_i, sin_int8=sin_i, beat_k=beat_k, state_byte=state)


# ── Standard MIDI file renderer ──

class MidiRenderer:
    """Render a PlatoScore to a Type-1 MIDI file using ``mido``."""

    def __init__(self, tempo_bpm: float = 120.0, ticks_per_beat: int = 480):
        self.tempo_bpm = tempo_bpm
        self.ticks_per_beat = ticks_per_beat

    def render(self, score: PlatoScore, output_path: str | None = None) -> mido.MidiFile:
        score.normalize_time()
        mid = mido.MidiFile(type=1, ticks_per_beat=self.ticks_per_beat)

        # Track 0: tempo + time signature
        meta = mido.MidiTrack()
        meta.append(mido.MetaMessage("track_name", name="PLATO Fleet Score", time=0))
        meta.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(self.tempo_bpm), time=0))
        meta.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
        meta.append(mido.MetaMessage("end_of_track", time=0))
        mid.tracks.append(meta)

        # One track per channel (up to 16)
        channel_tracks: dict[int, mido.MidiTrack] = {}
        channel_patches: dict[int, int] = {}

        events = sorted(score.events, key=lambda e: e.onset_beats)
        if not events:
            if output_path:
                mid.save(output_path)
            return mid

        # Group events by channel
        by_channel: dict[int, list[NoteEvent]] = {}
        for ev in events:
            by_channel.setdefault(ev.channel, []).append(ev)

        for ch, evs in sorted(by_channel.items()):
            track = mido.MidiTrack()
            track.append(mido.MetaMessage("track_name", name=f"Room CH{ch}", time=0))

            # Program change for first patch
            first_patch = evs[0].patch
            track.append(mido.Message("program_change", channel=ch, program=first_patch, time=0))
            channel_patches[ch] = first_patch

            abs_ticks_prev = 0
            pending_off: list[tuple[int, int]] = []  # (abs_ticks, pitch)

            for ev in evs:
                # Switch patch if changed
                if ev.patch != channel_patches.get(ch):
                    track.append(mido.Message("program_change", channel=ch, program=ev.patch, time=0))
                    channel_patches[ch] = ev.patch

                onset_ticks = int(ev.onset_beats * self.ticks_per_beat)
                duration_ticks = int(ev.duration_beats * self.ticks_per_beat)
                delta = onset_ticks - abs_ticks_prev
                delta = max(0, delta)

                track.append(mido.Message(
                    "note_on", channel=ch, note=ev.pitch, velocity=ev.velocity, time=delta
                ))
                pending_off.append((onset_ticks + duration_ticks, ev.pitch))
                abs_ticks_prev = onset_ticks

            # Sort note-offs and append as note_on velocity=0
            pending_off.sort(key=lambda x: x[0])
            for off_ticks, pitch in pending_off:
                delta = off_ticks - abs_ticks_prev
                delta = max(0, delta)
                track.append(mido.Message(
                    "note_on", channel=ch, note=pitch, velocity=0, time=delta
                ))
                abs_ticks_prev = off_ticks

            track.append(mido.MetaMessage("end_of_track", time=0))
            mid.tracks.append(track)

        if output_path:
            mid.save(output_path)
        return mid


# ── Tensor-MIDI renderer ──

class TensorMidiRenderer:
    """Render a PlatoScore to Tensor-MIDI events and optionally a binary stream."""

    def __init__(self, beat_resolution: int = 24):
        self.beat_resolution = beat_resolution

    def render(self, score: PlatoScore) -> list[TensorMIDIEvent]:
        score.normalize_time()
        return [
            TensorMIDIEvent.from_note_event(ev, self.beat_resolution)
            for ev in score.events
        ]

    def render_to_bytes(self, score: PlatoScore) -> bytes:
        return b"".join(ev.to_bytes() for ev in self.render(score))

    def render_to_json(self, score: PlatoScore) -> str:
        return json.dumps([ev.to_dict() for ev in self.render(score)], indent=2)


# ── Visual Music Score renderer ──

class VMSRenderer:
    """Render a PlatoScore to Visual Music Score (VMS) JSON.

    VMS is a 2D+time representation for visualising the fleet's song.
    Each note becomes a glyph with position, colour, and size.
    """

    def __init__(self, width: int = 1920, height: int = 1080):
        self.width = width
        self.height = height

    def _pitch_to_y(self, pitch: int) -> float:
        """Map MIDI pitch 0-127 to canvas Y (bottom=low, top=high)."""
        return self.height - (pitch / 127.0) * self.height

    def _channel_to_color(self, channel: int) -> str:
        """Assign a colour per channel."""
        hues = [
            "#e6194b", "#3cb44b", "#ffe119", "#4363d8",
            "#f58231", "#911eb4", "#42d4f4", "#f032e6",
            "#bfef45", "#fabed4", "#469990", "#dcbeff",
            "#9A6324", "#fffac8", "#800000", "#aaffc3",
        ]
        return hues[channel % len(hues)]

    def render(self, score: PlatoScore) -> dict:
        score.normalize_time()
        events = score.events
        duration = score.duration_beats or 1.0

        glyphs = []
        for ev in events:
            x = (ev.onset_beats / duration) * self.width
            y = self._pitch_to_y(ev.pitch)
            w = max(2.0, (ev.duration_beats / duration) * self.width)
            h = max(2.0, ev.velocity / 2.0)
            glyphs.append({
                "type": "note",
                "x": round(x, 2),
                "y": round(y, 2),
                "width": round(w, 2),
                "height": round(h, 2),
                "color": self._channel_to_color(ev.channel),
                "pitch": ev.pitch,
                "velocity": ev.velocity,
                "channel": ev.channel,
                "room": ev.room,
                "agent": ev.agent,
                "onset_beats": round(ev.onset_beats, 3),
                "duration_beats": round(ev.duration_beats, 3),
            })

        # Add chord annotations
        for chord in score.find_chords():
            x = (chord["onset_beats"] / duration) * self.width
            glyphs.append({
                "type": "chord",
                "x": round(x, 2),
                "y": 20,
                "width": round(max(4.0, (chord["duration_beats"] / duration) * self.width), 2),
                "height": 16,
                "color": "#ffffff",
                "chord_type": chord["type"],
                "rooms": chord["rooms"],
            })

        # Add rest annotations
        for rest in score.find_rests():
            x = (rest["start_beats"] / duration) * self.width
            glyphs.append({
                "type": "rest",
                "x": round(x, 2),
                "y": self.height - 20,
                "width": round(max(2.0, (rest["duration_beats"] / duration) * self.width), 2),
                "height": 8,
                "color": "#555555",
                "room": rest["room"],
                "duration_beats": round(rest["duration_beats"], 3),
            })

        return {
            "version": "v1",
            "title": "PLATO Fleet Singing",
            "width": self.width,
            "height": self.height,
            "duration_beats": round(duration, 3),
            "glyphs": glyphs,
        }

    def render_to_json(self, score: PlatoScore) -> str:
        return json.dumps(self.render(score), indent=2)
