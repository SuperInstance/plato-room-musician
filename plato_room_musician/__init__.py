"""
PLATO Room Musician: Turns PLATO room activity into music.

Every room is a musician. Every tile is a note. The fleet IS an orchestra.
"""

from plato_room_musician.fetcher import PlatoFetcher, SyntheticFetcher
from plato_room_musician.mapping import RoomMapper, TileMapper
from plato_room_musician.score import NoteEvent, PlatoScore
from plato_room_musician.renderer import MidiRenderer, TensorMidiRenderer, VMSRenderer

__all__ = [
    "PlatoFetcher",
    "SyntheticFetcher",
    "RoomMapper",
    "TileMapper",
    "NoteEvent",
    "PlatoScore",
    "MidiRenderer",
    "TensorMidiRenderer",
    "VMSRenderer",
]
