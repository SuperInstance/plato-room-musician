"""
Score arrangement: turns mapped tiles into a composed score.

- Deadband: only tiles with significant change from previous note are kept.
- Chord detection: simultaneous activity across rooms = harmony.
- Rest detection: gaps in a room's timeline become explicit rests.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class NoteEvent:
    """A canonical musical event derived from a PLATO tile."""

    room: str
    channel: int
    pitch: int
    velocity: int
    onset_beats: float
    duration_beats: float
    patch: int
    agent: str
    category: str
    tile_id: str = ""

    def __post_init__(self) -> None:
        if not (0 <= self.channel <= 15):
            raise ValueError(
                f"MIDI channel must be 0-15, got {self.channel}"
            )
        if not (0 <= self.velocity <= 127):
            raise ValueError(
                f"velocity must be 0-127, got {self.velocity}"
            )
        if not (0 <= self.pitch <= 127):
            raise ValueError(
                f"pitch must be 0-127, got {self.pitch}"
            )
        if self.duration_beats < 0:
            raise ValueError(
                f"duration_beats must be non-negative, got {self.duration_beats}"
            )

    @property
    def end_beats(self) -> float:
        return self.onset_beats + self.duration_beats

    def __repr__(self) -> str:
        return (
            f"NoteEvent({self.room} ch={self.channel} pitch={self.pitch} "
            f"vel={self.velocity} onset={self.onset_beats:.2f} "
            f"dur={self.duration_beats:.2f})"
        )

    def as_dict(self) -> dict:
        return {
            "room": self.room,
            "channel": self.channel,
            "pitch": self.pitch,
            "velocity": self.velocity,
            "onset_beats": self.onset_beats,
            "duration_beats": self.duration_beats,
            "patch": self.patch,
            "agent": self.agent,
            "category": self.category,
            "tile_id": self.tile_id,
        }


class PlatoScore:
    """Arranges room musicians into a temporal score with chords and rests."""

    def __init__(
        self,
        events: Sequence[NoteEvent],
        deadband_semitones: int = 2,
        deadband_velocity: int = 10,
        chord_window_beats: float = 0.5,
        rest_threshold_beats: float = 2.0,
    ):
        self._events = list(events)
        self.deadband_semitones = deadband_semitones
        self.deadband_velocity = deadband_velocity
        self.chord_window_beats = chord_window_beats
        self.rest_threshold_beats = rest_threshold_beats
        self._normalized = False

    # ── Builders ──

    @classmethod
    def from_mapped_tiles(
        cls,
        mapped_tiles: Sequence[dict],
        deadband_semitones: int = 2,
        deadband_velocity: int = 10,
        chord_window_beats: float = 0.5,
        rest_threshold_beats: float = 2.0,
    ) -> "PlatoScore":
        """Build a score from the output of TileMapper.map_tile()."""
        events = []
        for m in mapped_tiles:
            events.append(
                NoteEvent(
                    room=m["room"],
                    channel=m["channel"],
                    pitch=m["pitch"],
                    velocity=m["velocity"],
                    onset_beats=m["onset_beats"],
                    duration_beats=m["duration_beats"],
                    patch=m["patch"],
                    agent=m["agent"],
                    category=m["category"],
                    tile_id=m.get("tile_id", ""),
                )
            )
        return cls(
            events,
            deadband_semitones=deadband_semitones,
            deadband_velocity=deadband_velocity,
            chord_window_beats=chord_window_beats,
            rest_threshold_beats=rest_threshold_beats,
        )

    # ── Normalization ──

    def normalize_time(self) -> "PlatoScore":
        """Shift all events so the first onset is at beat 0."""
        if self._normalized or not self._events:
            return self
        min_onset = min(e.onset_beats for e in self._events)
        for e in self._events:
            object.__setattr__(e, 'onset_beats', e.onset_beats - min_onset)
        self._normalized = True
        return self

    # ── Deadband filtering ──

    def apply_deadband(self) -> "PlatoScore":
        """Keep only tiles that represent significant changes per room."""
        by_room: dict[str, list[NoteEvent]] = {}
        for e in self._events:
            by_room.setdefault(e.room, []).append(e)

        filtered: list[NoteEvent] = []
        for room, evs in by_room.items():
            evs.sort(key=lambda x: x.onset_beats)
            last: NoteEvent | None = None
            for ev in evs:
                if last is None:
                    filtered.append(ev)
                    last = ev
                    continue
                dp = abs(ev.pitch - last.pitch)
                dv = abs(ev.velocity - last.velocity)
                if dp > self.deadband_semitones or dv > self.deadband_velocity:
                    filtered.append(ev)
                    last = ev
        self._events = sorted(filtered, key=lambda e: e.onset_beats)
        return self

    # ── Chord detection ──

    def find_chords(self) -> list[dict]:
        """Detect time windows where multiple rooms sound together."""
        self.normalize_time()
        events = sorted(self._events, key=lambda e: e.onset_beats)
        if not events:
            return []

        chords: list[dict] = []
        i = 0
        while i < len(events):
            window_start = events[i].onset_beats
            window_end = window_start + self.chord_window_beats
            group = [events[i]]
            j = i + 1
            while j < len(events) and events[j].onset_beats <= window_end:
                group.append(events[j])
                j += 1
            if len(group) >= 2:
                unique_rooms = {e.room for e in group}
                if len(unique_rooms) >= 2:
                    chords.append({
                        "onset_beats": window_start,
                        "duration_beats": max(e.end_beats for e in group) - window_start,
                        "rooms": sorted(unique_rooms),
                        "notes": [e.as_dict() for e in group],
                        "type": self._classify_chord(group),
                    })
            i = j if j > i + 1 else i + 1
        return chords

    @staticmethod
    def _classify_chord(group: Sequence[NoteEvent]) -> str:
        """Very simple chord-type classifier based on pitch classes."""
        pcs = sorted({e.pitch % 12 for e in group})
        if len(pcs) < 2:
            return "unison"
        intervals = [pcs[j] - pcs[i] for i in range(len(pcs)) for j in range(i + 1, len(pcs))]
        intervals = [iv % 12 for iv in intervals]
        if 3 in intervals or 4 in intervals:
            if 7 in intervals:
                return "triad"
            return "dyad-third"
        if 7 in intervals:
            return "dyad-fifth"
        if 10 in intervals or 11 in intervals:
            return "seventh-color"
        return "cluster"

    # ── Rest detection ──

    def find_rests(self) -> list[dict]:
        """Find gaps per room longer than the rest threshold."""
        self.normalize_time()
        by_room: dict[str, list[NoteEvent]] = {}
        for e in self._events:
            by_room.setdefault(e.room, []).append(e)

        rests: list[dict] = []
        for room, evs in by_room.items():
            evs.sort(key=lambda e: e.onset_beats)
            prev_end = 0.0
            for ev in evs:
                gap = ev.onset_beats - prev_end
                if gap >= self.rest_threshold_beats:
                    rests.append({
                        "room": room,
                        "start_beats": prev_end,
                        "end_beats": ev.onset_beats,
                        "duration_beats": gap,
                    })
                prev_end = max(prev_end, ev.end_beats)
        rests.sort(key=lambda r: r["start_beats"])
        return rests

    # ── Accessors ──

    @property
    def events(self) -> list[NoteEvent]:
        return list(self._events)

    @property
    def duration_beats(self) -> float:
        if not self._events:
            return 0.0
        return max(e.end_beats for e in self._events)

    def summary(self) -> dict:
        self.normalize_time()
        chords = self.find_chords()
        rests = self.find_rests()
        rooms = {e.room for e in self._events}
        return {
            "rooms": sorted(rooms),
            "total_events": len(self._events),
            "duration_beats": round(self.duration_beats, 2),
            "chords": len(chords),
            "rests": len(rests),
            "chord_types": sorted({c["type"] for c in chords}),
        }
