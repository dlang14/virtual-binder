"""Local JSON stores: a TTL price cache and the TCGplayer id registry. Both live under data/ (gitignored)."""
from __future__ import annotations

import json
import os
import time
from typing import Callable, Dict, Optional


def _read(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, sort_keys=True)
    os.replace(tmp, path)


class TtlCache:
    """key -> JSON value, each stamped with when it was stored; get() returns None once it is older than ttl seconds."""

    def __init__(self, path: str, ttl: float, clock: Callable[[], float] = time.time):
        self.path, self.ttl, self.clock = path, ttl, clock
        self._items: Dict[str, dict] = _read(path).get("items", {})
        self._dirty = False

    def get(self, key: str):
        item = self._items.get(key)
        if not item or self.clock() - item.get("at", 0) >= self.ttl:
            return None
        return item.get("v")

    def put(self, key: str, value) -> None:
        self._items[key] = {"at": self.clock(), "v": value}
        self._dirty = True

    def save(self) -> None:
        if self._dirty:
            # drop entries that expired long ago so the file doesn't grow forever
            cutoff = self.clock() - self.ttl * 14
            self._items = {k: v for k, v in self._items.items() if v.get("at", 0) >= cutoff}
            _write(self.path, {"version": 1, "items": self._items})
            self._dirty = False


class IdRegistry:
    """Resolved TCGplayer product id per card, so later builds never look an id up twice.

    file: {"cards": {card key: {"id": "85270", "source": "tcgdex"|"pkmnprices"|"manual", "name": ..., "at": epoch}},
           "misses": {card key: {"reason": ..., "at": epoch}}}
    Entries with source "manual" are yours: they're never overwritten. Misses expire after miss_ttl so a card that
    gains an id later is retried, but a card with no id isn't searched for on every build.
    """

    def __init__(self, path: str, miss_ttl: float = 7 * 86400, clock: Callable[[], float] = time.time):
        raw = _read(path)
        self.path, self.miss_ttl, self.clock = path, miss_ttl, clock
        self.cards: Dict[str, dict] = raw.get("cards", {})
        self.misses: Dict[str, dict] = raw.get("misses", {})
        self._dirty = False

    def get(self, *keys: str) -> Optional[dict]:
        for k in keys:
            if k in self.cards:
                return self.cards[k]
        return None

    def recent_miss(self, key: str) -> Optional[str]:
        m = self.misses.get(key)
        if m and self.clock() - m.get("at", 0) < self.miss_ttl:
            return m.get("reason", "")
        return None

    def put(self, key: str, tcgplayer_id: str, source: str, name: str = "") -> None:
        if self.cards.get(key, {}).get("source") == "manual":
            return
        self.cards[key] = {"id": str(tcgplayer_id), "source": source, "name": name, "at": int(self.clock())}
        self.misses.pop(key, None)
        self._dirty = True

    def put_miss(self, key: str, reason: str) -> None:
        self.misses[key] = {"reason": reason, "at": int(self.clock())}
        self._dirty = True

    def save(self) -> None:
        if self._dirty:
            # Merge with the file first: an id the add-card server (or you, by hand) saved since this registry was loaded stays.
            raw = _read(self.path)
            cards = {**raw.get("cards", {}), **self.cards}
            misses = {k: v for k, v in {**raw.get("misses", {}), **self.misses}.items() if k not in cards}
            _write(self.path, {"version": 1, "cards": cards, "misses": misses})
            self.cards, self.misses, self._dirty = cards, misses, False
