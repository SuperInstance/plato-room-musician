# PLATO Room Musician — Developer Guide

## Architecture

```
plato_room_musician/
├── __init__.py      # Public API re-exports
├── fetcher.py       # PLATO API client + synthetic fallback
├── mapping.py       # Room → channel, Tile → note parameter mapping
├── score.py         # Score arrangement: deadband, chords, rests
├── renderer.py      # Output: MIDI file, Tensor-MIDI, VMS JSON
```

### Module Diagram

```
┌────────────┐     ┌────────────┐     ┌────────────┐     ┌────────────┐
│ fetcher.py │────▶│ mapping.py │────▶│  score.py  │────▶│renderer.py │
│ (PLATO API │     │(RoomMapper,│     │(PlatoScore,│     │(MIDI,      │
│  + synth)  │     │ TileMapper)│     │ deadband,  │     │Tensor-MIDI,│
└────────────┘     └────────────┘     │ chords)    │     │VMS)        │
                                      └────────────┘     └────────────┘
```

### Data Flow

1. `fetcher.py` → raw tile dicts from PLATO or synthetic generator
2. `mapping.py` → deterministic mapping of tiles to note parameters
3. `score.py` → temporal arrangement with deadband filtering, chord/rest detection
4. `renderer.py` → output in MIDI, Tensor-MIDI binary, or VMS JSON

### The Isomorphism

| PLATO Concept | Musical Concept | MIDI Encoding |
|--------------|-----------------|---------------|
| Room | Musician | MIDI channel (0–15) |
| Tile | Note | pitch + velocity + onset + duration |
| Agent | Instrument | Program change (patch) |
| Category | Scale/Register | Pitch range + scale degrees |
| Confidence | Dynamics | Velocity (0–127) |
| Content length | Duration | Beat duration |

## Extending

### Adding a New Category

Add to `CATEGORY_CONFIG` in `mapping.py`:

```python
CATEGORY_CONFIG["experimental"] = {
    "register": (36, 96),       # wide range
    "patches": [88, 89, 90],    # new age, warm pad, pollysynth
    "scale": [0, 1, 2, 4, 5, 7, 8, 10, 11],  # octatonic
    "rhythmic_role": "irregular",
}
```

And update `_category_from_name()` to detect the new prefix.

### Adding a New Room Source

Implement the same interface as `PlatoFetcher`:

```python
class FileFetcher:
    """Load tiles from a JSON file instead of HTTP API."""

    def __init__(self, path: Path):
        self.data = json.loads(path.read_text())

    def get_rooms(self) -> dict[str, dict]:
        return {r["name"]: r for r in self.data["rooms"]}

    def get_room(self, name: str, limit: int = 50) -> dict:
        for room in self.data["rooms"]:
            if room["name"] == name:
                return {"name": name, "tiles": room["tiles"][:limit]}
        return {"name": name, "tiles": []}

    def get_all_tiles(self) -> dict[str, list[dict]]:
        return {name: self.get_room(name)["tiles"] for name in self.get_rooms()}
```

### Adding a New Renderer

Follow the pattern in `renderer.py`:

```python
class MusicXMLRenderer:
    """Render a PlatoScore to MusicXML."""

    def render(self, score: PlatoScore, output_path: str | None = None) -> str:
        score.normalize_time()
        xml = '<?xml version="1.0"?>\n<score-partwise>\n'
        for ev in score.events:
            xml += f'  <note><pitch><step>{ev.pitch}</step></pitch>'
            xml += f'<duration>{ev.duration_beats}</duration></note>\n'
        xml += '</score-partwise>'
        if output_path:
            Path(output_path).write_text(xml)
        return xml
```

### Adding a New Score Operation

Extend `PlatoScore` in `score.py`:

```python
def quantize(self, grid: float = 1.0) -> "PlatoScore":
    """Snap all onsets to the nearest grid line."""
    for e in self._events:
        e.onset_beats = round(e.onset_beats / grid) * grid
    self._normalized = False
    return self

def transpose(self, semitones: int) -> "PlatoScore":
    """Transpose all pitches."""
    for e in self._events:
        e.pitch = max(0, min(127, e.pitch + semitones))
    return self
```

### Customizing the Mapping

Override `TileMapper.map_tile()` for custom mapping logic:

```python
class VelocitySensitiveMapper(TileMapper):
    def map_tile(self, room_name, tile, tempo_bpm=120.0):
        result = super().map_tile(room_name, tile, tempo_bpm)
        # Boost velocity for high-confidence tiles
        if tile.get("confidence", 0) > 0.9:
            result["velocity"] = min(127, result["velocity"] + 20)
        return result
```

## Testing

```bash
pytest                    # all tests
pytest -v                 # verbose
pytest --cov=plato_room_musician  # coverage
```

### Test Patterns

Use `SyntheticFetcher` for deterministic test fixtures:

```python
from plato_room_musician import SyntheticFetcher, RoomMapper, TileMapper, PlatoScore

def test_deadband_reduces_events():
    fetcher = SyntheticFetcher(seed=42)
    all_tiles = fetcher.get_all_tiles()
    rm, tm = RoomMapper(), TileMapper(rm)
    mapped = [tm.map_tile(r, t) for r, ts in all_tiles.items() for t in ts]

    score = PlatoScore.from_mapped_tiles(mapped)
    before = len(score.events)
    score.apply_deadband()
    after = len(score.events)
    assert after <= before
```

### Integration Tests

```python
def test_full_pipeline():
    """End-to-end: fetch → map → score → render."""
    fetcher = SyntheticFetcher(seed=42)
    all_tiles = fetcher.get_all_tiles()
    rm, tm = RoomMapper(), TileMapper(rm)
    mapped = [tm.map_tile(r, t) for r, ts in all_tiles.items() for t in ts]

    score = PlatoScore.from_mapped_tiles(mapped)
    score.apply_deadband()

    # MIDI render
    renderer = MidiRenderer(120.0)
    mid = renderer.render(score)
    assert len(mid.tracks) >= 2

    # Tensor-MIDI render
    tensor = TensorMidiRenderer()
    events = tensor.render(score)
    assert len(events) > 0
    raw = tensor.render_to_bytes(score)
    assert len(raw) == len(events) * 4
```

## Contributing

1. Fork, branch, implement, test, PR
2. Fetchers go in `fetcher.py`
3. Mapping logic goes in `mapping.py`
4. Score operations go in `score.py`
5. Renderers go in `renderer.py`
6. All new functions need tests
7. Use `SyntheticFetcher` in tests (no network dependency)

### Code Style

- Python 3.10+ with `from __future__ import annotations`
- No external dependencies beyond `mido`
- Deterministic mapping (hash-based, no randomness in mapping layer)
- Dataclasses for structured types
- Docstrings with Parameters/Returns

### Build System

```bash
pip install -e .
```

Single dependency: `mido>=1.3`.
