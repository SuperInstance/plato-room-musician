# Developer Guide — plato-room-musician

## Architecture

### Module structure

```
plato_room_musician/
├── __init__.py      # Public API exports
├── fetcher.py       # PlatoFetcher, SyntheticFetcher, get_fetcher
├── mapping.py       # RoomMapper, TileMapper, CATEGORY_CONFIG
├── score.py         # PlatoScore, NoteEvent
└── renderer.py      # MidiRenderer, TensorMidiRenderer, VMSRenderer
```

### Data flow

```
PLATO HTTP API
    │
    ▼ fetcher.get_rooms() / get_room() / get_all_tiles()
Tile dicts: {room, agent, timestamp, confidence, answer, tile_id, ...}
    │
    ▼ RoomMapper.channel_for() + config_for() + patch_for()
    ▼ TileMapper.map_tile()
Mapped note dicts: {room, channel, pitch, velocity, onset_beats, duration_beats, patch, ...}
    │
    ▼ PlatoScore.from_mapped_tiles()
NoteEvent objects
    │
    ├── normalize_time()    # shift to beat 0
    ├── apply_deadband()    # filter redundant events
    ├── find_chords()       # detect simultaneity
    └── find_rests()        # detect gaps
    │
    ▼ renderer.render()
Output format (MIDI, Tensor-MIDI bytes, VMS JSON)
```

### Key abstractions

**PlatoFetcher** — HTTP client for PLATO API. Handles JSON parsing, timeout, and error propagation.

**SyntheticFetcher** — Offline data generator. Creates realistic room/tile data from templates with configurable seed. Used for development, testing, and when PLATO is unreachable.

**RoomMapper** — Maps room names to MIDI channels and category configs. Uses SHA-256 for deterministic hashing with collision resolution.

**TileMapper** — Maps individual tiles to note parameters. Depends on RoomMapper for channel/config lookup.

**NoteEvent** — Internal representation of a musical event. Carries room, channel, pitch, velocity, onset, duration, patch, agent, category, tile_id.

**PlatoScore** — Arranges NoteEvents into a temporal score. Provides deadband filtering, chord detection, rest detection, and summary statistics.

**MidiRenderer** — Renders score to Type-1 MIDI file via `mido`. One track per channel, program changes per agent.

**TensorMidiRenderer** — Renders to 4-byte Tensor-MIDI events. Phase-direction encoding (cos/sin of pitch class), beat counter, state byte.

**VMSRenderer** — Renders to Visual Music Score JSON. 2D+time glyph representation.

## Mapping internals

### Room → category

```python
def _category_from_name(room_name):
    # Matches prefixes: forgemaster, session, fleet, knowledge, constraint
    # Case-insensitive, checks both startswith and mid-string
```

If no prefix matches, defaults to `"session"`.

### Room → channel

```python
def channel_for(room_name):
    raw = SHA256(room_name)[:4]  # first 4 hex chars
    ch = int(raw, 16) % 16
    # Collision resolution: increment until free
    while ch in used_channels:
        ch = (ch + 1) % 16
```

Deterministic: same room name always gets the same channel. Collision resolution is order-dependent (first-come-first-served).

### Room → patch

```python
def patch_for(room_name, tile):
    cfg = config_for(room_name)
    agent = tile.get("agent", "")
    idx = SHA256(f"{room_name}:{agent}")[:4]
    return cfg["patches"][idx % len(cfg["patches"])]
```

Same agent in same room = same patch. Different agent = possibly different patch.

### Tile → pitch

```python
def _pitch_from_tile(tile_hash, register, scale):
    degree_idx = tile_hash % len(scale)
    degree = scale[degree_idx]
    octave_offset = ((tile_hash // len(scale)) % max(1, span // 12 + 1)) * 12
    pitch = register[0] + octave_offset + degree
    return clamp(pitch, register[0], register[1] - 1)
```

The hash determines both the scale degree and the octave offset, ensuring pitch variety within the register.

## Score internals

### Deadband filtering

Per-room sequential filter:

```python
for room, events in by_room:
    last = None
    for event in events:
        if last is None:
            keep(event)
        elif |event.pitch - last.pitch| > deadband_semitones:
            keep(event)
        elif |event.velocity - last.velocity| > deadband_velocity:
            keep(event)
        else:
            discard(event)
        last = event
```

### Chord detection

Sliding window approach:

```python
i = 0
while i < len(events):
    window = events[i:i+?]  # within chord_window_beats
    if len(unique_rooms) >= 2:
        record_chord(window)
    advance i past window
```

Chord classification uses interval analysis:

| Intervals present | Type |
|---|---|
| Major/minor third + perfect fifth | `triad` |
| Third but no fifth | `dyad-third` |
| Fifth but no third | `dyad-fifth` |
| Major seventh or minor seventh | `seventh-color` |
| None of the above | `cluster` |
| All same pitch class | `unison` |

### Rest detection

Per-room gap analysis:

```python
for room, events in by_room:
    prev_end = 0.0
    for event in sorted(events, key=onset):
        gap = event.onset - prev_end
        if gap >= rest_threshold_beats:
            record_rest(room, prev_end, event.onset)
        prev_end = max(prev_end, event.end)
```

## Renderer internals

### MidiRenderer

Outputs Type-1 MIDI:
- Track 0: `track_name`, `set_tempo`, `time_signature`, `end_of_track`
- Track 1-16: one per active channel
  - `track_name` = "Room CH{n}"
  - `program_change` per agent change
  - `note_on`/`note_on(vel=0)` pairs with delta ticks

Note-offs are collected per track, sorted by absolute tick, and appended after all note-ons.

### TensorMidiRenderer

Each NoteEvent becomes 4 bytes:

```python
angle = 2π × (pitch % 12) / 12
cos_int8 = clamp(int(cos(angle) × 127), -128, 127)
sin_int8 = clamp(int(sin(angle) × 127), -128, 127)
beat_k = int(onset × beat_resolution) % 256
state = (channel << 4) | (velocity >> 3)
```

Phase direction encodes pitch class as a unit circle coordinate. Beat counter wraps at 256. State byte packs channel (4 bits) and velocity (4 bits, divided by 8).

### VMSRenderer

Note position:
- `x = (onset / total_duration) × width`
- `y = height - (pitch / 127) × height` (bottom = low, top = high)
- `width = (duration / total_duration) × canvas_width`
- `height = velocity / 2`

Chord annotations: white bars at y=20.
Rest annotations: grey bars at y=height-20.

Colors: 16 predefined hues, indexed by channel.

## Extending

### Add a new category

Add to `CATEGORY_CONFIG` in `mapping.py`:

```python
CATEGORY_CONFIG["quantum"] = {
    "register": (96, 120),
    "patches": [104, 105],        # sitar, banjo
    "scale": [0, 1, 4, 5, 7, 8, 11],  # some exotic scale
    "rhythmic_role": "pulse",
}
```

Room names containing the prefix "quantum" will auto-match via `_category_from_name`.

### Add a new renderer

Create a new class in `renderer.py` or a new module:

```python
class MyRenderer:
    def __init__(self, **options):
        self.options = options

    def render(self, score: PlatoScore) -> SomeFormat:
        score.normalize_time()
        events = score.events
        # Transform events to your format
        ...
```

Follow the pattern: accept a `PlatoScore`, call `normalize_time()`, iterate `score.events`.

### Add a new fetcher backend

Implement the same interface as `PlatoFetcher`:

```python
class MyFetcher:
    def get_rooms(self) -> dict[str, dict]: ...
    def get_room(self, name: str, limit: int = 50) -> dict: ...
    def get_all_tiles(self) -> dict[str, list[dict]]: ...
```

### Customize mapping algorithms

Override `TileMapper` methods:

```python
class CustomTileMapper(TileMapper):
    def _tile_hash(self, tile):
        # Custom hash function
        ...

    def map_tile(self, room_name, tile, tempo_bpm=120.0):
        # Custom mapping logic
        result = super().map_tile(room_name, tile, tempo_bpm)
        # Post-process
        result["velocity"] = min(127, result["velocity"] * 1.2)
        return result
```

## Testing

### Running tests

```bash
python -m pytest tests/ -v
```

### What to test

1. **Fetcher** — Live and synthetic return same schema
2. **Mapping determinism** — Same input → same output (hash stability)
3. **Channel collision resolution** — >16 rooms handled gracefully
4. **Deadband** — Filtered events are actually redundant
5. **Chord detection** — Simultaneous events across rooms detected
6. **Rest detection** — Gaps above threshold found
7. **MIDI rendering** — Output is valid MIDI, plays correctly
8. **Tensor-MIDI** — 4-byte encoding round-trips correctly
9. **VMS** — Glyph positions are within canvas bounds

### Test patterns

```python
from plato_room_musician import SyntheticFetcher, RoomMapper, TileMapper, PlatoScore

def test_mapping_deterministic():
    tm = TileMapper(RoomMapper())
    fetcher = SyntheticFetcher(seed=42)
    tile = fetcher.get_room("forgemaster-anvil")["tiles"][0]

    r1 = tm.map_tile("forgemaster-anvil", tile)
    r2 = tm.map_tile("forgemaster-anvil", tile)
    assert r1["pitch"] == r2["pitch"]
    assert r1["channel"] == r2["channel"]

def test_deadband_reduces_events():
    tm = TileMapper(RoomMapper())
    fetcher = SyntheticFetcher(seed=42)
    mapped = []
    for name in fetcher.get_rooms():
        for tile in fetcher.get_room(name)["tiles"][:5]:
            mapped.append(tm.map_tile(name, tile))

    score = PlatoScore.from_mapped_tiles(mapped)
    before = len(score.events)
    score.apply_deadband()
    after = len(score.events)
    assert after <= before
```

## Contributing

1. Fork the repo
2. Create a feature branch
3. Keep the mapping/fetching/rendering separation clean
4. Add tests for any new functionality
5. Run `python -m pytest tests/ -v`
6. Submit a pull request

### Code style

- Python 3.10+ with type hints
- Dataclasses for structured data
- Dict-based APIs for flexible serialization
- No heavy dependencies beyond numpy and mido

### Design principles

- **Deterministic mapping** — Same input always produces same output
- **Graceful degradation** — Synthetic fallback when PLATO is unreachable
- **Format-agnostic core** — Score is independent of output format
- **Category-driven** — Room behavior follows from category assignment
