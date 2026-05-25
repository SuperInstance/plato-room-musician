# plato-room-musician

🎼 PLATO rooms → MIDI — room = musician, tile = note, fleet activity becomes a musical score.

Every PLATO room is a musician with its own instrument, register, and scale. Every tile submitted to that room is a note. When the fleet is active, the rooms play together — and the resulting music encodes the fleet's actual work rhythm, coordination patterns, and cognitive load.

## Why it exists

Fleet telemetry is usually dashboards, logs, and metrics. But fleet activity has an inherent temporal structure: agents submit tiles at varying rates, rooms fill in bursts and pauses, and the coordination patterns between rooms have musical analogs (harmony when rooms are active simultaneously, rests when the fleet is idle). plato-room-musician makes that structure audible. It's sonification that doubles as legitimate music because the mapping respects music theory — each room category uses an appropriate scale, register, and timbre.

## The math in plain English

**Room → Channel** — Each room gets a deterministic MIDI channel (0–15) via SHA-256 hashing. Collision resolution ensures uniqueness.

**Tile → Note** — Each tile's properties map to musical parameters:
- **Confidence → Velocity**: Higher confidence = louder note
- **Timestamp → Onset**: When the tile was submitted = when the note plays
- **Content length → Duration**: Longer answers = longer notes
- **Tile identity → Pitch**: SHA-256 hash of tile ID selects a scale degree within the room's register

**Category → Scale/Register** — Room names map to categories (forgemaster, session, fleet, knowledge, constraint), each with its own pitch range, scale, instrument patch, and rhythmic role.

**Chord detection** — When multiple rooms are active within a time window, they form chords. The score engine detects these and classifies them (triad, cluster, dyad).

**Deadband filtering** — Only tiles that represent significant changes (pitch > 2 semitones or velocity > 10 from the previous tile in that room) are kept. This prevents auditory clutter from repetitive activity.

## Quick start

```bash
pip install plato-room-musician
```

```python
from plato_room_musician import SyntheticFetcher, RoomMapper, TileMapper, PlatoScore, MidiRenderer

# Use synthetic data (works offline)
fetcher = SyntheticFetcher(seed=42)
rooms = fetcher.get_rooms()

# Map rooms and tiles
room_mapper = RoomMapper()
tile_mapper = TileMapper(room_mapper)

mapped = []
for room_name in rooms:
    tiles = fetcher.get_room(room_name)["tiles"]
    for tile in tiles:
        mapped.append(tile_mapper.map_tile(room_name, tile, tempo_bpm=120))

# Compose score
score = PlatoScore.from_mapped_tiles(mapped)
score.normalize_time().apply_deadband()
print(score.summary())

# Render to MIDI
renderer = MidiRenderer(tempo_bpm=120)
renderer.render(score, output_path="fleet_song.mid")
print("Written fleet_song.mid")
```

Output:
```
{'rooms': ['constraint-bounds', 'constraint-checker', 'fleet-comms', ...],
 'total_events': 234,
 'duration_beats': 1847.25,
 'chords': 12,
 'rests': 8,
 'chord_types': ['cluster', 'dyad-fifth', 'triad']}
Written fleet_song.mid
```

### With live PLATO data

```python
from plato_room_musician import PlatoFetcher

fetcher = PlatoFetcher(host="http://147.224.38.131:8847")
try:
    tiles = fetcher.get_all_tiles()
except ConnectionError:
    # Falls back to synthetic
    fetcher = SyntheticFetcher()
    tiles = fetcher.get_all_tiles()
```

## API overview

### Fetching data

```python
from plato_room_musician import PlatoFetcher, SyntheticFetcher

# Live PLATO
fetcher = PlatoFetcher(host="http://your-plato:8847", timeout=5.0)
rooms = fetcher.get_rooms()                    # {name: metadata}
room_data = fetcher.get_room("forgemaster-anvil", limit=50)
all_tiles = fetcher.get_all_tiles()            # {name: [tile_dicts]}

# Synthetic (offline)
synth = SyntheticFetcher(seed=42)
rooms = synth.get_rooms()
all_tiles = synth.get_all_tiles()
```

### Mapping

```python
from plato_room_musician import RoomMapper, TileMapper

room_mapper = RoomMapper()
tile_mapper = TileMapper(room_mapper)

# Room → channel + config
ch = room_mapper.channel_for("forgemaster-anvil")  # 0-15
cfg = room_mapper.config_for("forgemaster-anvil")  # register, patches, scale
patch = room_mapper.patch_for("forgemaster-anvil", {"agent": "cadence-caller"})

# Tile → note
note = tile_mapper.map_tile("forgemaster-anvil", tile_dict, tempo_bpm=120)
# Returns: {room, channel, pitch, velocity, onset_beats, duration_beats,
#           patch, agent, category, rhythmic_role, tile_id, raw_tile}
```

### Category configuration

| Category | Register | Scale | Patches | Role |
|----------|----------|-------|---------|------|
| forgemaster | C2–E3 (36–52) | Minor blues/Phrygian | Distortion guitar (30-32) | root |
| session | C3–G4 (48–67) | Major/Lydian | Warm pads (91-93) | halftime |
| fleet | B1–D3 (35–50) | Pentatonic | Synth drums (117-119) | triplet |
| knowledge | C5–C7 (72–96) | Whole-tone+Lydian | Bells/chimes (8,9,14) | waltz |
| constraint | C1–G2 (24–43) | Mixolydian | Bass (32-34) | compound |

### Score composition

```python
from plato_room_musician import PlatoScore

score = PlatoScore.from_mapped_tiles(
    mapped_tiles,
    deadband_semitones=2,     # pitch deadband
    deadband_velocity=10,     # velocity deadband
    chord_window_beats=0.5,   # simultaneity window
    rest_threshold_beats=2.0, # gap threshold for rests
)

score.normalize_time()  # shift so first onset = beat 0
score.apply_deadband()  # filter redundant events

chords = score.find_chords()  # detect simultaneous activity
rests = score.find_rests()    # detect gaps
print(score.summary())        # {rooms, total_events, duration, chords, rests}
```

### Rendering

```python
from plato_room_musician import MidiRenderer, TensorMidiRenderer, VMSRenderer

# Standard MIDI
midi = MidiRenderer(tempo_bpm=120, ticks_per_beat=480)
midi.render(score, "output.mid")

# Tensor-MIDI (4-byte events for neural synthesis)
tensor = TensorMidiRenderer(beat_resolution=24)
events = tensor.render(score)          # List[TensorMIDIEvent]
raw_bytes = tensor.render_to_bytes(score)  # bytes
json_str = tensor.render_to_json(score)    # JSON string

# Visual Music Score (2D+time visualization)
vms = VMSRenderer(width=1920, height=1080)
vms_data = vms.render(score)            # dict
vms_json = vms.render_to_json(score)    # JSON string
```

## Architecture

```
┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│ fetcher  │────>│ mapping  │────>│  score   │────>│ renderer │
│          │     │          │     │          │     │          │
│ Plato    │     │ RoomMapper│    │ PlatoScore│    │ MIDI     │
│ Synthetic│     │ TileMapper│    │ deadband │     │ Tensor   │
│          │     │ CATEGORY │     │ chords   │     │ VMS      │
│ get_rooms│     │ _CONFIG  │     │ rests    │     │          │
│ get_tiles│     │          │     │          │     │          │
└──────────┘     └──────────┘     └──────────┘     └──────────┘

PLATO API ──> rooms + tiles ──> mapped notes ──> composed score ──> output format
```

## Documentation

- [User Guide](docs/USER-GUIDE.md) — Complete usage documentation
- [Developer Guide](docs/DEVELOPER-GUIDE.md) — Contributing and internals
- [Examples](examples/) — Working code examples

## Related repos

- [holonomy-harmony](https://github.com/SuperInstance/holonomy-harmony) — Chord progression analysis via holonomy
- [spline-midi-smooth](https://github.com/SuperInstance/spline-midi-smooth) — Spline interpolation for MIDI automation
- [tensor-midi](https://github.com/SuperInstance/tensor-midi) — INT8-saturated MIDI for neural synthesis
- [flux-tensor-midi](https://github.com/SuperInstance/flux-tensor-midi) — Flux tensor MIDI for neural synthesis
- [constraint-instrument](https://github.com/SuperInstance/constraint-instrument) — Constraint-based music generation (7 modes, 17 terrains)
- [plato-core](https://github.com/SuperInstance/plato-core) — Foundation types and mesh registry
- [cocapn-plato](https://github.com/SuperInstance/cocapn-plato) — Full PLATO SDK + server

## Requirements

- Python 3.10+
- numpy
- mido (for MIDI rendering)

## Install

```bash
pip install plato-room-musician
```

Or from source:

```bash
git clone https://github.com/SuperInstance/plato-room-musician.git
cd plato-room-musician
pip install -e .
```

## License

Apache License 2.0
