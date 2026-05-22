# PLATO Room Musician — User Guide

## Table of Contents

1. [Overview](#overview)
2. [Installation](#installation)
3. [Fetching Room Data](#fetching-room-data)
4. [Mapping Rooms to Music](#mapping-rooms-to-music)
5. [Building a Score](#building-a-score)
6. [Deadband Filtering](#deadband-filtering)
7. [Chord and Rest Detection](#chord-and-rest-detection)
8. [Rendering to MIDI](#rendering-to-midi)
9. [Rendering to Tensor-MIDI](#rendering-to-tensor-midi)
10. [Rendering to Visual Music Score](#rendering-to-visual-music-score)
11. [Full Pipeline Example](#full-pipeline-example)
12. [Configuration Reference](#configuration-reference)
13. [Common Patterns](#common-patterns)
14. [Troubleshooting](#troubleshooting)

---

## Overview

PLATO Room Musician transcribes fleet activity into music. It connects to PLATO rooms (or generates synthetic data), maps room categories to instruments/scales/registers, arranges tiles into a temporal score, and renders the output as MIDI, Tensor-MIDI, or Visual Music Score (VMS) JSON.

The isomorphism: Room = Musician (MIDI channel), Tile = Note (pitch/velocity/onset/duration), Agent = Instrument patch, Category = Scale/register.

## Installation

```bash
git clone https://github.com/SuperInstance/plato-room-musician.git
cd plato-room-musician
pip install -e .
```

## Fetching Room Data

### Live PLATO Server

```python
from plato_room_musician import PlatoFetcher

fetcher = PlatoFetcher(host="http://147.224.38.131:8847", timeout=5.0)

# List all rooms
rooms = fetcher.get_rooms()
for name, meta in rooms.items():
    print(f"{name}: {meta}")

# Get tiles from one room
room = fetcher.get_room("forgemaster-cadence", limit=50)
tiles = room.get("tiles", [])
print(f"Got {len(tiles)} tiles")

# Fetch everything
all_tiles = fetcher.get_all_tiles()  # {room_name: [tiles]}
```

### Synthetic Data (Always Available)

```python
from plato_room_musician import SyntheticFetcher

fetcher = SyntheticFetcher(seed=42)

rooms = fetcher.get_rooms()
# 13 predefined rooms across 5 categories:
# forgemaster (2), session (4), fleet (3), knowledge (2), constraint (2)

all_tiles = fetcher.get_all_tiles()
for room_name, tiles in all_tiles.items():
    print(f"{room_name}: {len(tiles)} tiles")
```

### Auto-Fallback

```python
from plato_room_musician.fetcher import get_fetcher

# Tries live PLATO, falls back to synthetic
fetcher = get_fetcher()
all_tiles = fetcher.get_all_tiles()
```

## Mapping Rooms to Music

### RoomMapper

Maps room names to MIDI channels and category configs:

```python
from plato_room_musician import RoomMapper

rm = RoomMapper()

# Deterministic channel assignment (0-15, collision-resolved)
ch = rm.channel_for("forgemaster-anvil")     # e.g., 3
ch2 = rm.channel_for("session-ambient")      # e.g., 7

# Musical config for a room
config = rm.config_for("forgemaster-anvil")
# {
#   'register': (36, 52),          # C2–E3 pitch range
#   'patches': [30, 31, 32],       # distortion guitar, etc.
#   'scale': [0, 2, 3, 5, 7, 8, 10],  # minor blues
#   'rhythmic_role': 'root'
# }

# Patch assignment based on agent
patch = rm.patch_for("forgemaster-anvil", {"agent": "forge-agent"})
```

### Category Mappings

| Category | Register | Character | Scale | Rhythmic Role |
|----------|----------|-----------|-------|---------------|
| forgemaster | C2–E3 | Industrial, low | Minor blues/Phrygian | root |
| session | C3–G4 | Ambient pads | Major/Lydian | halftime |
| fleet | B1–D3 | Percussive | Pentatonic | triplet |
| knowledge | C5–C7 | Bells, chimes | Whole-tone/Lydian | waltz |
| constraint | C1–G2 | Bass, grounded | Mixolydian | compound |

### TileMapper

Maps individual tiles to note parameters:

```python
from plato_room_musician import TileMapper, RoomMapper

rm = RoomMapper()
tm = TileMapper(rm)

# Map one tile
tile = {
    "room": "forgemaster-cadence",
    "agent": "forge-agent",
    "timestamp": 1700000000.0,
    "confidence": 0.85,
    "question": "Q0: Harmonic convergence",
    "answer": "Constraint satisfaction: SAT for kernel K3",
    "tile_id": "forgemaster-cadence-0000",
}

note = tm.map_tile("forgemaster-cadence", tile, tempo_bpm=120.0)
# {
#   'room': 'forgemaster-cadence',
#   'channel': 3,
#   'pitch': 42,
#   'velocity': 108,        # confidence * 127
#   'onset_beats': 1700000000.0,  # raw timestamp (normalized later)
#   'duration_beats': 0.65, # content length / 40
#   'patch': 31,
#   'agent': 'forge-agent',
#   'category': 'forgemaster',
#   'rhythmic_role': 'root',
# }
```

**Mapping rules:**
- **Confidence → Velocity:** `int(confidence × 127)`, clamped to 1–127
- **Content length → Duration:** `len(answer) / 40` beats, clamped to 0.25–4.0
- **Tile hash → Pitch:** Deterministic hash selects scale degree within register
- **Agent → Patch:** Deterministic hash selects from category's patch list

## Building a Score

```python
from plato_room_musician import RoomMapper, TileMapper, PlatoScore

rm = RoomMapper()
tm = TileMapper(rm)

# Map all tiles
fetcher = SyntheticFetcher(seed=42)
all_tiles = fetcher.get_all_tiles()

mapped = []
for room_name, tiles in all_tiles.items():
    for tile in tiles:
        mapped.append(tm.map_tile(room_name, tile, tempo_bpm=120.0))

# Build score
score = PlatoScore.from_mapped_tiles(
    mapped,
    deadband_semitones=2,     # pitch change threshold
    deadband_velocity=10,     # velocity change threshold
    chord_window_beats=0.5,   # window for chord detection
    rest_threshold_beats=2.0, # minimum gap for a rest
)
```

### Score Properties

```python
# Duration in beats
print(f"Duration: {score.duration_beats:.1f} beats")

# All events
for ev in score.events[:10]:
    print(f"  {ev.room} ch={ev.channel} pitch={ev.pitch} "
          f"vel={ev.velocity} onset={ev.onset_beats:.2f}")

# Summary
print(score.summary())
# {'rooms': [...], 'total_events': N, 'duration_beats': T,
#  'chords': C, 'rests': R, 'chord_types': [...]}
```

## Deadband Filtering

Remove tiles that don't represent significant musical changes:

```python
score.apply_deadband()

# How it works per room:
# 1. Sort events by onset time
# 2. Keep first event
# 3. For each subsequent event, keep only if:
#    - pitch changed by > deadband_semitones, OR
#    - velocity changed by > deadband_velocity
before = len(score.events)
score.apply_deadband()
after = len(score.events)
print(f"Deadband filter: {before} → {after} events")
```

## Chord and Rest Detection

### Chords

Simultaneous activity across multiple rooms creates harmony:

```python
chords = score.find_chords()
for c in chords:
    print(f"Beat {c['onset_beats']:.1f}: {c['type']} "
          f"rooms={c['rooms']} ({len(c['notes'])} notes)")
```

**Chord types:**
- `triad` — contains third + fifth
- `dyad-third` — third without fifth
- `dyad-fifth` — fifth without third
- `seventh-color` — includes 7th
- `cluster` — dense chromatic collection
- `unison` — single pitch class

### Rests

Gaps in a room's activity become explicit rests:

```python
rests = score.find_rests()
for r in rests:
    print(f"Room '{r['room']}': silence from beat {r['start_beats']:.1f} "
          f"to {r['end_beats']:.1f} ({r['duration_beats']:.1f} beats)")
```

## Rendering to MIDI

```python
from plato_room_musician import MidiRenderer

renderer = MidiRenderer(tempo_bpm=120.0, ticks_per_beat=480)

# Render and save
renderer.render(score, output_path="fleet_singing.mid")
```

Output is a Type-1 MIDI file with:
- Track 0: tempo + time signature
- One track per channel (up to 16)
- Program changes per channel
- All note-on/note-off events with correct delta times

## Rendering to Tensor-MIDI

```python
from plato_room_musician import TensorMidiRenderer

renderer = TensorMidiRenderer(beat_resolution=24)

# List of TensorMIDIEvent objects
events = renderer.render(score)
for ev in events[:3]:
    print(f"cos={ev.cos_int8} sin={ev.sin_int8} beat={ev.beat_k} state=0x{ev.state_byte:02x}")

# Raw binary (4 bytes per event)
raw = renderer.render_to_bytes(score)
print(f"{len(raw)} bytes ({len(raw)//4} events)")

# JSON
json_str = renderer.render_to_json(score)
```

**TensorMIDIEvent 4-byte format:**

| Byte | Field | Encoding |
|------|-------|----------|
| 0 | `cos_int8` | `cos(2π × pitch%12 / 12) × 127` |
| 1 | `sin_int8` | `sin(2π × pitch%12 / 12) × 127` |
| 2 | `beat_k` | `int(onset × resolution) % 256` |
| 3 | `state_byte` | `(channel << 4) \| (velocity >> 3)` |

## Rendering to Visual Music Score

```python
from plato_room_musician import VMSRenderer

vms = VMSRenderer(width=1920, height=1080)
data = vms.render(score)

# Each glyph has: type, x, y, width, height, color, pitch, velocity, channel, room
for glyph in data['glyphs'][:5]:
    print(f"{glyph['type']}: room={glyph.get('room','?')} "
          f"pitch={glyph.get('pitch','?')} at ({glyph['x']:.0f}, {glyph['y']:.0f})")

# Save as JSON
json_str = vms.render_to_json(score)
with open("fleet_vms.json", "w") as f:
    f.write(json_str)
```

The VMS renders notes as colored rectangles on a 2D canvas:
- X axis = time (left to right)
- Y axis = pitch (bottom = low, top = high)
- Color = channel/room
- Width = duration
- Height = velocity

## Full Pipeline Example

```python
from plato_room_musician import (
    SyntheticFetcher, RoomMapper, TileMapper,
    PlatoScore, MidiRenderer, TensorMidiRenderer, VMSRenderer
)

# 1. Fetch data
fetcher = SyntheticFetcher(seed=42)
all_tiles = fetcher.get_all_tiles()

# 2. Map to music
rm = RoomMapper()
tm = TileMapper(rm)
mapped = []
for room_name, tiles in all_tiles.items():
    for tile in tiles:
        mapped.append(tm.map_tile(room_name, tile))

# 3. Build score
score = PlatoScore.from_mapped_tiles(mapped)
score.apply_deadband()

# 4. Render
print(score.summary())
MidiRenderer(120.0).render(score, "fleet.mid")
print(f"Tensor-MIDI: {len(TensorMidiRenderer().render(score))} events")
```

## Configuration Reference

### `PlatoFetcher(host, timeout)`

| Parameter | Default | Description |
|-----------|---------|-------------|
| `host` | `"http://147.224.38.131:8847"` | PLATO server URL |
| `timeout` | 5.0 | HTTP timeout in seconds |

### `SyntheticFetcher(seed)`

| Parameter | Default | Description |
|-----------|---------|-------------|
| `seed` | 42 | RNG seed for reproducibility |

### `PlatoScore.from_mapped_tiles(mapped_tiles, deadband_semitones=2, deadband_velocity=10, chord_window_beats=0.5, rest_threshold_beats=2.0)`

| Parameter | Default | Description |
|-----------|---------|-------------|
| `deadband_semitones` | 2 | Pitch change threshold for filtering |
| `deadband_velocity` | 10 | Velocity change threshold |
| `chord_window_beats` | 0.5 | Time window for chord detection |
| `rest_threshold_beats` | 2.0 | Minimum gap to register as rest |

### `MidiRenderer(tempo_bpm=120.0, ticks_per_beat=480)`

Standard MIDI file rendering.

### `TensorMidiRenderer(beat_resolution=24)`

Higher resolution = finer beat quantization (24 = 24 ticks per beat).

### `VMSRenderer(width=1920, height=1080)`

Canvas size for visual rendering.

## Common Patterns

### Use live PLATO data

```python
from plato_room_musician import PlatoFetcher, RoomMapper, TileMapper, PlatoScore, MidiRenderer

fetcher = PlatoFetcher("http://your-plato:8847")
all_tiles = fetcher.get_all_tiles()

rm, tm = RoomMapper(), TileMapper()
mapped = [tm.map_tile(room, tile) for room, tiles in all_tiles.items() for tile in tiles]

score = PlatoScore.from_mapped_tiles(mapped)
score.apply_deadband()
MidiRenderer(120.0).render(score, "live_fleet.mid")
```

### Export only specific rooms

```python
target_rooms = {"forgemaster-cadence", "fleet-coord"}
filtered = {k: v for k, v in all_tiles.items() if k in target_rooms}
# ... then map and score as usual
```

### Adjust deadband for denser/sparser output

```python
# Dense: keep almost everything
score = PlatoScore.from_mapped_tiles(mapped, deadband_semitones=0, deadband_velocity=0)

# Sparse: keep only big changes
score = PlatoScore.from_mapped_tiles(mapped, deadband_semitones=5, deadband_velocity=20)
```

## Troubleshooting

### `ConnectionError: PLATO unreachable`

The PLATO server is down or unreachable. Use `SyntheticFetcher` as a fallback:

```python
from plato_room_musician.fetcher import get_fetcher
fetcher = get_fetcher()  # auto-falls back to synthetic
```

### Too many/few events after deadband

Adjust `deadband_semitones` and `deadband_velocity`:
- Lower values → more events retained (denser texture)
- Higher values → fewer events (sparser, only major changes)

### All notes in one channel

If all your rooms hash to the same channel (unlikely but possible with many rooms), RoomMapper resolves collisions by incrementing. With 13 rooms and 16 channels, collisions are rare.

### Timestamps are huge numbers

Mapped tiles have raw Unix timestamps as `onset_beats`. Call `score.normalize_time()` (called automatically by renderers) to shift everything so the first note starts at beat 0.
