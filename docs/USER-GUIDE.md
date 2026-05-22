# User Guide — plato-room-musician

## Table of Contents

1. [Overview](#overview)
2. [Core concepts](#core-concepts)
3. [Fetching data](#fetching-data)
4. [Room and tile mapping](#room-and-tile-mapping)
5. [Score composition](#score-composition)
6. [Rendering to MIDI](#rendering-to-midi)
7. [Tensor-MIDI rendering](#tensor-midi-rendering)
8. [Visual Music Score](#visual-music-score)
9. [Input/output formats](#inputoutput-formats)
10. [Configuration reference](#configuration-reference)
11. [Use cases](#use-cases)
12. [Troubleshooting](#troubleshooting)

## Overview

plato-room-musician sonifies PLATO room activity as music. The pipeline:

1. **Fetch** tile data from PLATO (or generate synthetic data)
2. **Map** rooms → MIDI channels/instruments, tiles → notes
3. **Compose** a temporal score with chord/rest detection and deadband filtering
4. **Render** to MIDI file, Tensor-MIDI bytes, or Visual Music Score JSON

## Core concepts

### The isomorphism

| PLATO concept | Musical concept |
|--------------|----------------|
| Room | Musician (MIDI channel + instrument) |
| Tile | Note (pitch, velocity, onset, duration) |
| Agent | Instrument variant (program change) |
| Category | Scale, register, rhythmic role |
| Room activity burst | Musical phrase |
| Multi-room coordination | Chord/harmony |
| Fleet idle period | Rest |

### Pitch mapping

Pitch is derived deterministically from the tile's identity hash:

1. SHA-256 hash of `tile_id:timestamp`
2. Hash modulo scale length → scale degree
3. Hash divided by scale length modulo octave range → octave offset
4. `pitch = register_low + octave_offset + scale_degree`
5. Clamped to `[register_low, register_high)`

### Velocity mapping

`velocity = confidence × 127`, clamped to [1, 127].

### Duration mapping

`duration_beats = max(0.25, min(4.0, len(content) / 40.0))` — longer answers produce longer notes, capped at 4 beats.

## Fetching data

### Live PLATO

```python
from plato_room_musician import PlatoFetcher

fetcher = PlatoFetcher(
    host="http://147.224.38.131:8847",  # default
    timeout=5.0,
)

# List all rooms
rooms = fetcher.get_rooms()
# Returns: {"room-name": {"category": "...", ...}, ...}

# Get tiles for one room
room_data = fetcher.get_room("forgemaster-anvil", limit=50)
tiles = room_data["tiles"]  # list of tile dicts

# Get tiles for all rooms
all_tiles = fetcher.get_all_tiles()
# Returns: {"room-name": [tile_dicts], ...}
```

### Synthetic fallback

```python
from plato_room_musician import SyntheticFetcher

fetcher = SyntheticFetcher(seed=42)
rooms = fetcher.get_rooms()      # 13 synthetic rooms
all_tiles = fetcher.get_all_tiles()
```

Synthetic rooms include: `forgemaster-cadence`, `forgemaster-anvil`, `session-deep-dive`, `session-ambient`, `fleet-coord`, `fleet-nav`, `fleet-comms`, `knowledge-archive`, `knowledge-index`, `constraint-checker`, `constraint-bounds`, `synthesis-oracle`, `research-log`.

### Auto-detection

```python
from plato_room_musician.fetcher import get_fetcher

# Tries live PLATO first, falls back to synthetic
fetcher = get_fetcher()
```

### Tile data format

Each tile is a dict with these keys:

| Key | Type | Description |
|-----|------|-------------|
| `room` | `str` | Room name |
| `category` | `str` | Category prefix |
| `agent` | `str` | Agent that submitted the tile |
| `timestamp` | `float` | Unix timestamp |
| `confidence` | `float` | 0.0–1.0 |
| `question` | `str` | The question asked |
| `answer` | `str` | The answer given |
| `tile_id` | `str` | Unique tile identifier |

## Room and tile mapping

### RoomMapper

```python
from plato_room_musician import RoomMapper

rm = RoomMapper()

# Deterministic channel assignment (0-15)
ch = rm.channel_for("forgemaster-anvil")   # e.g. 7

# Category config
cfg = rm.config_for("forgemaster-anvil")
# {
#   "register": (36, 52),
#   "patches": [30, 31, 32],
#   "scale": [0, 2, 3, 5, 7, 8, 10],
#   "rhythmic_role": "root",
# }

# Instrument patch
patch = rm.patch_for("forgemaster-anvil", {"agent": "forge-agent"})
# Deterministic based on room + agent hash
```

### TileMapper

```python
from plato_room_musician import TileMapper

tm = TileMapper(room_mapper)

note = tm.map_tile("forgemaster-anvil", tile, tempo_bpm=120.0)
# Returns:
# {
#   "room": "forgemaster-anvil",
#   "channel": 7,
#   "pitch": 41,           # F#2 (in forgemaster register 36-52)
#   "velocity": 89,        # confidence * 127
#   "onset_beats": 345.2,  # from timestamp
#   "duration_beats": 1.5, # from content length
#   "patch": 31,           # guitar harmonics
#   "agent": "forge-agent",
#   "category": "forgemaster",
#   "rhythmic_role": "root",
#   "tile_id": "forgemaster-anvil-001a",
#   "raw_tile": {...},     # original tile dict
# }
```

### Custom category config

Override `CATEGORY_CONFIG` before creating mappers:

```python
from plato_room_musician.mapping import CATEGORY_CONFIG

CATEGORY_CONFIG["custom"] = {
    "register": (60, 79),
    "patches": [40, 41, 42],
    "scale": [0, 3, 5, 7, 10],  # minor pentatonic
    "rhythmic_role": "swing",
}
```

## Score composition

### Building a score

```python
from plato_room_musician import PlatoScore

# From mapped tiles
score = PlatoScore.from_mapped_tiles(
    mapped_tiles,
    deadband_semitones=2,
    deadband_velocity=10,
    chord_window_beats=0.5,
    rest_threshold_beats=2.0,
)
```

### Normalization

```python
score.normalize_time()  # Shift all onsets so first = beat 0
```

Always call this before rendering. It's idempotent.

### Deadband filtering

```python
score.apply_deadband()
```

Removes tiles where the pitch hasn't changed by more than `deadband_semitones` AND the velocity hasn't changed by more than `deadband_velocity` from the previous tile in the same room. This prevents auditory clutter from repetitive activity.

### Chord detection

```python
chords = score.find_chords()
# [
#   {
#     "onset_beats": 12.5,
#     "duration_beats": 0.8,
#     "rooms": ["forgemaster-anvil", "session-deep-dive"],
#     "notes": [...],
#     "type": "triad",  # chord classification
#   },
#   ...
# ]
```

Chord types: `triad`, `dyad-third`, `dyad-fifth`, `seventh-color`, `cluster`, `unison`.

### Rest detection

```python
rests = score.find_rests()
# [
#   {
#     "room": "fleet-comms",
#     "start_beats": 45.0,
#     "end_beats": 52.3,
#     "duration_beats": 7.3,
#   },
#   ...
# ]
```

### Summary

```python
print(score.summary())
# {
#   "rooms": ["constraint-bounds", "constraint-checker", ...],
#   "total_events": 234,
#   "duration_beats": 1847.25,
#   "chords": 12,
#   "rests": 8,
#   "chord_types": ["cluster", "dyad-fifth", "triad"],
# }
```

## Rendering to MIDI

### MidiRenderer

```python
from plato_room_musician import MidiRenderer

renderer = MidiRenderer(tempo_bpm=120.0, ticks_per_beat=480)
mid = renderer.render(score, output_path="fleet.mid")
```

Output is a Type-1 MIDI file with:
- Track 0: tempo, time signature, metadata
- One track per MIDI channel (up to 16)
- Program changes per agent/room
- Note-on/note-off events from the score

### Custom tempo

```python
renderer = MidiRenderer(tempo_bpm=140.0)  # faster playback
```

## Tensor-MIDI rendering

Tensor-MIDI encodes each note as 4 bytes for neural synthesis:

| Byte | Field | Encoding |
|------|-------|----------|
| 0 | `cos_int8` | cos(2π × pitch/12) × 127, INT8 saturated |
| 1 | `sin_int8` | sin(2π × pitch/12) × 127, INT8 saturated |
| 2 | `beat_k` | onset × beat_resolution, mod 256 |
| 3 | `state_byte` | (channel << 4) \| (velocity >> 3) |

```python
from plato_room_musician import TensorMidiRenderer

renderer = TensorMidiRenderer(beat_resolution=24)

# List of events
events = renderer.render(score)

# Raw bytes
raw = renderer.render_to_bytes(score)

# JSON
json_str = renderer.render_to_json(score)
```

### TensorMIDIEvent

```python
event = events[0]
print(event.cos_int8)     # -64
print(event.sin_int8)     # 95
print(event.beat_k)       # 142
print(event.state_byte)   # 113
print(event.to_bytes())   # b'\xc0\x5f\x8e\x71'
print(event.to_dict())    # {"cos_int8": -64, "sin_int8": 95, ...}
```

## Visual Music Score

VMS is a 2D+time JSON format for visualization:

```python
from plato_room_musician import VMSRenderer

vms = VMSRenderer(width=1920, height=1080)
data = vms.render(score)
```

Output structure:

```json
{
  "version": "v1",
  "title": "PLATO Fleet Singing",
  "width": 1920,
  "height": 1080,
  "duration_beats": 1847.25,
  "glyphs": [
    {
      "type": "note",
      "x": 234.5,
      "y": 612.0,
      "width": 5.2,
      "height": 44.5,
      "color": "#e6194b",
      "pitch": 41,
      "velocity": 89,
      "channel": 7,
      "room": "forgemaster-anvil",
      "agent": "forge-agent",
      "onset_beats": 12.5,
      "duration_beats": 1.5
    },
    {
      "type": "chord",
      "x": 345.2,
      "y": 20,
      "width": 8.1,
      "height": 16,
      "color": "#ffffff",
      "chord_type": "triad",
      "rooms": ["forgemaster-anvil", "session-deep-dive"]
    },
    {
      "type": "rest",
      "x": 500.0,
      "y": 1060,
      "width": 3.8,
      "height": 8,
      "color": "#555555",
      "room": "fleet-comms",
      "duration_beats": 7.3
    }
  ]
}
```

Note glyphs: positioned at (x=onset, y=pitch), sized by (width=duration, height=velocity).
Chord glyphs: horizontal bars at the top.
Rest glyphs: horizontal bars at the bottom.

Colors are deterministic per MIDI channel (16 distinct hues).

## Input/output formats

### Input

- **PLATO API**: HTTP JSON at `/rooms` and `/room/{name}`
- **Tile dict**: `{"room", "category", "agent", "timestamp", "confidence", "question", "answer", "tile_id"}`
- **Mapped note**: dict from `TileMapper.map_tile()`

### Output

- **MIDI**: Type-1 `.mid` file (via `MidiRenderer`)
- **Tensor-MIDI**: 4-byte events, raw bytes or JSON (via `TensorMidiRenderer`)
- **VMS**: JSON dict with glyph array (via `VMSRenderer`)
- **Score summary**: JSON-serializable dict

## Configuration reference

### PlatoFetcher

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `host` | `str` | `"http://147.224.38.131:8847"` | PLATO server URL |
| `timeout` | `float` | `5.0` | HTTP timeout in seconds |

### SyntheticFetcher

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `seed` | `int` | `42` | Random seed for reproducibility |

### PlatoScore

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `deadband_semitones` | `int` | `2` | Pitch change threshold |
| `deadband_velocity` | `int` | `10` | Velocity change threshold |
| `chord_window_beats` | `float` | `0.5` | Simultaneity window |
| `rest_threshold_beats` | `float` | `2.0` | Gap threshold for rests |

### MidiRenderer

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `tempo_bpm` | `float` | `120.0` | Playback tempo |
| `ticks_per_beat` | `int` | `480` | MIDI resolution |

### TensorMidiRenderer

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `beat_resolution` | `int` | `24` | Ticks per beat for beat_k |

### VMSRenderer

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `width` | `int` | `1920` | Canvas width in pixels |
| `height` | `int` | `1080` | Canvas height in pixels |

## Use cases

### 1. Generate a MIDI file from fleet activity

```python
from plato_room_musician import SyntheticFetcher, RoomMapper, TileMapper, PlatoScore, MidiRenderer

fetcher = SyntheticFetcher(seed=42)
mapper = TileMapper(RoomMapper())

mapped = []
for name in fetcher.get_rooms():
    for tile in fetcher.get_room(name)["tiles"]:
        mapped.append(mapper.map_tile(name, tile))

score = PlatoScore.from_mapped_tiles(mapped)
score.normalize_time().apply_deadband()

MidiRenderer(tempo_bpm=120).render(score, "fleet.mid")
```

### 2. Connect to live PLATO and stream

```python
from plato_room_musician import PlatoFetcher, RoomMapper, TileMapper, PlatoScore, MidiRenderer

fetcher = PlatoFetcher()
all_tiles = fetcher.get_all_tiles()

mapper = TileMapper(RoomMapper())
mapped = []
for room, tiles in all_tiles.items():
    for tile in tiles:
        mapped.append(mapper.map_tile(room, tile))

score = PlatoScore.from_mapped_tiles(mapped)
score.normalize_time().apply_deadband()
MidiRenderer().render(score, "live_fleet.mid")
```

### 3. Export Tensor-MIDI for neural synthesis

```python
from plato_room_musician import TensorMidiRenderer

renderer = TensorMidiRenderer(beat_resolution=48)
raw = renderer.render_to_bytes(score)
with open("fleet.tensor_midi", "wb") as f:
    f.write(raw)
```

### 4. Generate a Visual Music Score for a web dashboard

```python
from plato_room_musician import VMSRenderer
import json

vms = VMSRenderer(width=1920, height=1080)
data = vms.render(score)
with open("fleet_vms.json", "w") as f:
    json.dump(data, f, indent=2)
```

### 5. Analyze fleet coordination patterns

```python
score = PlatoScore.from_mapped_tiles(mapped)
score.normalize_time()

chords = score.find_chords()
print(f"Coordination events: {len(chords)}")
for c in chords:
    print(f"  Beat {c['onset_beats']:.1f}: {', '.join(c['rooms'])} ({c['type']})")

rests = score.find_rests()
print(f"Fleet idle periods: {len(rests)}")
for r in rests:
    print(f"  {r['room']}: {r['duration_beats']:.1f} beats silence")
```

### 6. Compare fleet activity across time periods

```python
# Period A
synth_a = SyntheticFetcher(seed=42)
tiles_a = synth_a.get_all_tiles()
score_a = PlatoScore.from_mapped_tiles([...]).normalize_time()

# Period B
synth_b = SyntheticFetcher(seed=99)
tiles_b = synth_b.get_all_tiles()
score_b = PlatoScore.from_mapped_tiles([...]).normalize_time()

print(f"Period A: {score_a.summary()}")
print(f"Period B: {score_b.summary()}")
```

### 7. Custom room categories

```python
from plato_room_musician.mapping import CATEGORY_CONFIG, _category_from_name, RoomMapper, TileMapper

# Add a new category
CATEGORY_CONFIG["neural"] = {
    "register": (84, 108),
    "patches": [98, 99, 100],  # crystal, atmosphere, brightness
    "scale": [0, 1, 3, 4, 6, 7, 9, 10],  # octatonic
    "rhythmic_role": "irregular",
}

# Room names containing "neural" will auto-match
mapper = TileMapper(RoomMapper())
note = mapper.map_tile("neural-synth-lab", tile)
```

## Troubleshooting

### "PLATO unreachable"

The PLATO server may be down or the URL wrong. Use `SyntheticFetcher` as fallback, or `get_fetcher()` which auto-falls back:

```python
from plato_room_musician.fetcher import get_fetcher
fetcher = get_fetcher()  # tries live, falls back to synthetic
```

### No notes generated

- Check that tiles have valid timestamps (not all zero)
- Check that tile dicts have `confidence` > 0
- Verify the room names match category prefixes

### All notes on one channel

With >16 rooms, MIDI channels must be reused (only 16 available). The mapper resolves collisions deterministically. This is expected behavior.

### MIDI file is silent in my player

- Verify the tempo is reasonable (not 0 or extreme values)
- Check that notes have velocity > 0
- Ensure the MIDI file isn't empty (check file size)

### Pitch range seems wrong

Each category has a fixed register. Check `CATEGORY_CONFIG` for the room's category. The pitch is always clamped to `[register_low, register_high)`.

### VMS JSON is too large

Reduce the number of events by tightening the deadband:

```python
score = PlatoScore.from_mapped_tiles(
    mapped,
    deadband_semitones=5,    # wider = fewer events
    deadband_velocity=20,
)
```

### Synthetic data sounds repetitive

The synthetic generator uses a fixed seed for reproducibility. Change the seed for different patterns:

```python
fetcher = SyntheticFetcher(seed=int(time.time()))
```
