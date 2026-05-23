"""Demo: Generate a musical score from synthetic PLATO room activity."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plato_room_musician import SyntheticFetcher, RoomMapper, TileMapper, PlatoScore, MidiRenderer

# 1. Create synthetic room activity (simulates PLATO fleet)
fetcher = SyntheticFetcher(
    rooms=["forgemaster-build", "session-alpha", "fleet-scan", "knowledge-index", "constraint-check"],
    bpm=120,
    duration_beats=32,
)
tiles = fetcher.fetch()
print(f"Fetched {len(tiles)} tiles from {len(set(t.room for t in tiles))} rooms")

# 2. Map rooms → musicians, tiles → notes
room_mapper = RoomMapper()
tile_mapper = TileMapper()

note_events = []
for tile in tiles:
    room_config = room_mapper.map_room(tile.room)
    note = tile_mapper.map_tile(tile, room_config)
    note_events.append(note)
print(f"Mapped to {len(note_events)} note events")

# 3. Arrange into a score with deadband filtering
score = PlatoScore(note_events, deadband_semitones=2, deadband_velocity=10)
print(f"Score: {len(score.events)} events after deadband filtering")
print(f"  Chords detected: {len(score.chords)}")
print(f"  Rest periods: {len(score.rests)}")

# 4. Render to MIDI
renderer = MidiRenderer(bpm=120)
output_path = renderer.render(score, output_path="plato_output.mid")
print(f"\nMIDI rendered: {output_path}")

# Show first few events
for event in score.events[:5]:
    print(f"  {event}")
