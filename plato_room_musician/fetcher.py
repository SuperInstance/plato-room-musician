"""
PLATO API fetcher + synthetic fallback.

Fetches rooms and tiles from a live PLATO instance.
If unreachable, generates synthetic room patterns that follow
the same schema so the music pipeline always has data to sing.
"""
from __future__ import annotations
import json
import random
import time
import urllib.request
from typing import Any

PLATO_HOST = "http://147.224.38.131:8847"


def _now() -> float:
    return time.time()


class PlatoFetcher:
    """Client for the PLATO HTTP API."""

    def __init__(self, host: str = PLATO_HOST, timeout: float = 5.0):
        self.host = host.rstrip("/")
        self.timeout = timeout

    def _get(self, path: str) -> Any:
        url = f"{self.host}{path}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read())

    def get_rooms(self) -> dict[str, dict]:
        """Return {room_name: room_metadata} from /rooms."""
        try:
            data = self._get("/rooms")
            if isinstance(data, dict):
                return data
            if isinstance(data, list):
                return {r["name"] if isinstance(r, dict) else str(r): {} for r in data}
        except Exception as exc:
            raise ConnectionError(f"PLATO unreachable at {self.host}: {exc}") from exc
        return {}

    def get_room(self, name: str, limit: int = 50) -> dict:
        """Return room payload (including 'tiles' list) for a single room."""
        try:
            data = self._get(f"/room/{name}?limit={limit}")
            if isinstance(data, dict):
                return data
        except Exception as exc:
            raise ConnectionError(f"Room {name} unreachable: {exc}") from exc
        return {"name": name, "tiles": []}

    def get_all_tiles(self) -> dict[str, list[dict]]:
        """Fetch tiles for every known room."""
        rooms = self.get_rooms()
        result: dict[str, list[dict]] = {}
        for room_name in rooms:
            room_data = self.get_room(room_name, limit=50)
            result[room_name] = room_data.get("tiles", [])
        return result


# ── Synthetic fallback ──

ROOM_TEMPLATES = [
    ("forgemaster-cadence", "forgemaster"),
    ("forgemaster-anvil", "forgemaster"),
    ("session-deep-dive", "session"),
    ("session-ambient", "session"),
    ("fleet-coord", "fleet"),
    ("fleet-nav", "fleet"),
    ("fleet-comms", "fleet"),
    ("knowledge-archive", "knowledge"),
    ("knowledge-index", "knowledge"),
    ("constraint-checker", "constraint"),
    ("constraint-bounds", "constraint"),
    ("synthesis-oracle", "session"),
    ("research-log", "session"),
]

AGENTS = [
    "cadence-caller",
    "forge-agent",
    "plato-oracle",
    "fleet-captain",
    "constraint-engine",
    "knowledge-indexer",
    "session-musician",
    "tensor-midi",
]

TILE_SEEDS = [
    "Harmonic convergence detected in room %s",
    "Tile submitted by %s at beat %d",
    "Constraint satisfaction: SAT for kernel K%d",
    "Fleet heartbeat OK — all rooms in tempo",
    "Deadband funnel stable at ε=%.3f",
    "Holonomy check: zero drift across %d rooms",
    "Eisenstein snap applied to rhythm grid",
    "INT8 saturation adds %.4f drift — inaudible",
    "Laman rigidity holds for %d-voice fugue",
    "Nod received from %s — ensemble agrees",
]


class SyntheticFetcher:
    """Generates realistic PLATO room data when the real server is away."""

    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)
        self._base_time = _now() - 300  # 5 minutes ago

    def _make_tile(self, room_name: str, category: str, idx: int, t: float) -> dict:
        agent = self.rng.choice(AGENTS)
        confidence = self.rng.random()
        template = self.rng.choice(TILE_SEEDS)
        # Each template has different format specifiers, so build a
        # per-template arg list instead of a one-size-fits-all tuple.
        _fmt_args = {
            "Harmonic convergence detected in room %s": lambda: (room_name,),
            "Tile submitted by %s at beat %d": lambda: (agent, self.rng.randint(0, 127)),
            "Constraint satisfaction: SAT for kernel K%d": lambda: (self.rng.randint(2, 8),),
            "Fleet heartbeat OK — all rooms in tempo": lambda: (),
            "Deadband funnel stable at ε=%.3f": lambda: (self.rng.random() * 50, ),
            "Holonomy check: zero drift across %d rooms": lambda: (self.rng.randint(2, 8),),
            "Eisenstein snap applied to rhythm grid": lambda: (),
            "INT8 saturation adds %.4f drift — inaudible": lambda: (self.rng.random() * 0.01,),
            "Laman rigidity holds for %d-voice fugue": lambda: (self.rng.randint(2, 8),),
            "Nod received from %s — ensemble agrees": lambda: (agent,),
        }
        content = template % _fmt_args[template]()
        # Content length determines duration later
        return {
            "room": room_name,
            "category": category,
            "agent": agent,
            "timestamp": t,
            "confidence": confidence,
            "question": f"Q{idx}: {content[:40]}",
            "answer": content,
            "tile_id": f"{room_name}-{idx:04x}",
        }

    def get_rooms(self) -> dict[str, dict]:
        return {name: {"category": cat, "tile_count": self.rng.randint(10, 200)}
                for name, cat in ROOM_TEMPLATES}

    def get_room(self, name: str, limit: int = 50) -> dict:
        rooms = self.get_rooms()
        meta = rooms.get(name, {})
        cat = meta.get("category", "session")
        count = self.rng.randint(5, limit)
        tiles = []
        t = self._base_time
        for i in range(count):
            # Exponential-ish spacing: some bursts, some silence
            delta = self.rng.expovariate(1.0 / 3.0) + 0.2
            t += delta
            tiles.append(self._make_tile(name, cat, i, t))
        return {"name": name, "category": cat, "tiles": tiles}

    def get_all_tiles(self) -> dict[str, list[dict]]:
        return {name: self.get_room(name)["tiles"] for name in self.get_rooms()}


def get_fetcher(host: str = PLATO_HOST, timeout: float = 5.0) -> PlatoFetcher | SyntheticFetcher:
    """Try live PLATO; fall back to synthetic on failure."""
    fetcher = PlatoFetcher(host, timeout)
    try:
        fetcher.get_rooms()
        return fetcher
    except Exception:
        return SyntheticFetcher(seed=int(_now()))
