"""
Mapping layer: Room / Tile → MIDI musical parameters.

Implements the isomorphism:
    Room  = Musician  (MIDI channel)
    Tile  = Note      (pitch, velocity, onset, duration)
    Agent = Instrument patch
    Category = Scale / register
"""
from __future__ import annotations
import hashlib
from typing import Sequence

# ── Room category → musical register ──

CATEGORY_CONFIG = {
    "forgemaster": {
        "register": (36, 52),       # C2..E3 — industrial, low
        "patches": [30, 31, 32],    # distortion guitar, guitar harmonics, acoustic bass
        "scale": [0, 2, 3, 5, 7, 8, 10],  # minor blues / Phrygian
        "rhythmic_role": "root",
    },
    "session": {
        "register": (48, 67),       # C3..G4 — ambient pads, middle
        "patches": [91, 92, 93],    # pad warm, pad choir, pad bowed
        "scale": [0, 2, 4, 5, 7, 9, 11],  # major / Lydian
        "rhythmic_role": "halftime",
    },
    "fleet": {
        "register": (35, 50),       # B1..D3 — percussion, rhythmic
        "patches": [117, 118, 119], # melodic tom, synth drum, reverse cymbal
        "scale": [0, 2, 4, 7, 9],   # pentatonic (no wrong notes under pressure)
        "rhythmic_role": "triplet",
    },
    "knowledge": {
        "register": (72, 96),       # C5..C7 — bells, chimes, high
        "patches": [8, 9, 14],      # celesta, glockenspiel, tubular bells
        "scale": [0, 2, 4, 6, 7, 9, 11],  # whole-tone + Lydian (bright, floating)
        "rhythmic_role": "waltz",
    },
    "constraint": {
        "register": (24, 43),       # C1..G2 — bass, low, stable
        "patches": [32, 33, 34],    # acoustic bass, electric bass finger, electric bass pick
        "scale": [0, 2, 4, 5, 7, 9, 10],  # Mixolydian (grounded, open)
        "rhythmic_role": "compound",
    },
}

# Default fallback for unknown categories
DEFAULT_CONFIG = {
    "register": (60, 79),
    "patches": [0, 1, 2],
    "scale": [0, 2, 4, 5, 7, 9, 11],
    "rhythmic_role": "root",
}


def _category_from_name(room_name: str) -> str:
    """Extract category prefix from room name."""
    lower = room_name.lower()
    for prefix in ("forgemaster", "session", "fleet", "knowledge", "constraint"):
        if lower.startswith(prefix):
            return prefix
    # Also check for mid-string matches
    for prefix in ("forgemaster", "session", "fleet", "knowledge", "constraint"):
        if prefix in lower:
            return prefix
    return "session"


def _hash_to_range(s: str, lo: int, hi: int) -> int:
    """Deterministically hash a string to an integer in [lo, hi)."""
    digest = hashlib.sha256(s.encode()).hexdigest()
    val = int(digest[:8], 16)
    return lo + (val % (hi - lo))


def _pitch_from_tile(tile_hash: int, register: tuple[int, int], scale: Sequence[int]) -> int:
    """Map a tile hash to a pitch within the register using the scale."""
    span = register[1] - register[0]
    # Build chromatic span then filter to scale degrees
    root = register[0]
    # Pick a scale degree
    degree_idx = tile_hash % len(scale)
    degree = scale[degree_idx]
    # Pick octave offset
    octave_offset = ((tile_hash // len(scale)) % max(1, span // 12 + 1)) * 12
    pitch = root + octave_offset + degree
    return max(register[0], min(register[1] - 1, pitch))


class RoomMapper:
    """Maps a PLATO room to a MIDI channel and category config."""

    def __init__(self):
        self._channel_map: dict[str, int] = {}
        self._next_channel = 0

    def channel_for(self, room_name: str) -> int:
        """Hash room name to MIDI channel 0-15 (deterministic, collision-resistant)."""
        if room_name not in self._channel_map:
            # Deterministic hash → channel
            raw = int(hashlib.sha256(room_name.encode()).hexdigest()[:4], 16)
            ch = raw % 16
            # Collision resolution: if taken, find next free
            attempts = 0
            while ch in self._channel_map.values() and attempts < 16:
                ch = (ch + 1) % 16
                attempts += 1
            self._channel_map[room_name] = ch
        return self._channel_map[room_name]

    def config_for(self, room_name: str) -> dict:
        """Return the musical configuration for a room."""
        cat = _category_from_name(room_name)
        return CATEGORY_CONFIG.get(cat, DEFAULT_CONFIG)

    def patch_for(self, room_name: str, tile: dict) -> int:
        """Map room + source agent to instrument patch (program change)."""
        cfg = self.config_for(room_name)
        patches = cfg["patches"]
        agent = tile.get("agent", "")
        idx = int(hashlib.sha256(f"{room_name}:{agent}".encode()).hexdigest()[:4], 16)
        return patches[idx % len(patches)]


class TileMapper:
    """Maps an individual PLATO tile to note parameters."""

    def __init__(self, room_mapper: RoomMapper | None = None):
        self.room_mapper = room_mapper or RoomMapper()

    def _tile_hash(self, tile: dict) -> int:
        """Deterministic hash of tile identity."""
        payload = f"{tile.get('tile_id', '')}:{tile.get('timestamp', 0):.6f}"
        return int(hashlib.sha256(payload.encode()).hexdigest()[:8], 16)

    def map_tile(self, room_name: str, tile: dict, tempo_bpm: float = 120.0) -> dict:
        """Return a canonical NoteEvent dict from a tile."""
        cfg = self.room_mapper.config_for(room_name)
        ch = self.room_mapper.channel_for(room_name)
        tile_hash = self._tile_hash(tile)

        # Confidence → velocity (0-127)
        confidence = tile.get("confidence", 0.5)
        velocity = int(confidence * 127)
        velocity = max(1, min(127, velocity))

        # Timestamp → onset in beats
        ts = tile.get("timestamp", 0.0)
        # Normalize to first beat = 0
        onset_beats = ts  # caller will offset globally

        # Content length → duration in beats
        content = str(tile.get("answer", tile.get("question", "")))
        duration_beats = max(0.25, min(4.0, len(content) / 40.0))

        # Pitch from register + scale
        pitch = _pitch_from_tile(tile_hash, cfg["register"], cfg["scale"])

        # Patch
        patch = self.room_mapper.patch_for(room_name, tile)

        return {
            "room": room_name,
            "channel": ch,
            "pitch": pitch,
            "velocity": velocity,
            "onset_beats": onset_beats,
            "duration_beats": duration_beats,
            "patch": patch,
            "agent": tile.get("agent", "unknown"),
            "category": _category_from_name(room_name),
            "rhythmic_role": cfg["rhythmic_role"],
            "tile_id": tile.get("tile_id", ""),
            "raw_tile": tile,
        }
