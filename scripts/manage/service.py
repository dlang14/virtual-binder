"""Collection operations behind a small, HTTP-free interface: search the catalog, add a card, edit it, remove it.

Each method takes plain values and returns plain dicts, and failures raise ServiceError(status, message), so a local
server today (scripts/serve.py) or an API route later is a thin wrapper. Nothing here calls a price API: an added card
is priced by the next build, which asks JustTCG only for what its 24 h price cache lacks.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Callable, Optional

from pricing import CardCatalog, CardRef, CatalogCard, CatalogUnavailable, Condition, IdRegistry, parse_condition, strip_wear_words
from pricing.catalog import set_score

from .store import CsvCollection, Row

MAX_QTY, MAX_NOTE = 999, 200
CARD_ID = re.compile(r"^[A-Za-z0-9._+-]{1,40}$")
STALE = "that row is no longer in the collection file; rebuild and reload the page"


class ServiceError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _condition(value) -> Condition:
    try:
        return Condition(str(value).upper())
    except ValueError:
        raise ServiceError(400, "condition must be one of " + ", ".join(c.value for c in Condition)) from None


def _qty(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_QTY:
        raise ServiceError(400, f"quantity must be a whole number from 1 to {MAX_QTY}")
    return value


def _note(cond: Condition, extra: str) -> str:
    """The notes cell: the wear first, the way the pricing step reads it ('LP - corner whitening'), then the user's own text.
    Text that names another wear level would make the condition ambiguous, so it is refused."""
    extra = " ".join((extra or "").split())
    if len(extra) > MAX_NOTE:
        raise ServiceError(400, f"notes can be at most {MAX_NOTE} characters")
    note = f"{cond.value} - {extra}" if extra else cond.value
    if parse_condition(note).condition is not cond:
        raise ServiceError(400, "the note mentions another wear level; use the condition menu for that")
    return note


class CollectionService:
    def __init__(self, catalog: CardCatalog, open_registry: Callable[[], IdRegistry], store: CsvCollection,
                 today: Callable[[], date] = date.today):
        # open_registry is called per add, so ids a build saved in the meantime are never overwritten
        self.catalog, self.open_registry, self.store, self.today = catalog, open_registry, store, today

    # ---------------------------------------------------------- search
    def search(self, name: str, set_name: str = "", number: str = "", limit: int = 12, offset: int = 0) -> dict:
        if len((name or "").strip()) < 2:
            raise ServiceError(400, "type at least two letters of a card name")
        try:
            cards, total = self.catalog.browse(name.strip(), set_name.strip() or None, number.strip() or None, limit, offset)
        except CatalogUnavailable as e:
            raise ServiceError(502, f"{e}; try again in a moment") from None
        return {"total": total, "results": [self._view(c) for c in cards]}

    @staticmethod
    def _view(c: CatalogCard) -> dict:
        thumb = c.image.rsplit("/", 1)[0] + "/low.webp" if c.image else None
        return {"id": c.card_id, "name": c.name, "set": c.set_name, "number": c.number, "rarity": c.rarity,
                "image": thumb, "tcgplayerId": c.tcgplayer_id}

    # ---------------------------------------------------------- add
    def add(self, card_id: str, condition, qty=1, notes: str = "") -> dict:
        cond = _condition(condition)
        qty, note = _qty(qty), _note(cond, notes)
        detail = self.catalog.tcgdex_card(card_id) if CARD_ID.match(str(card_id)) else None
        if not detail:
            raise ServiceError(404, "that card was not found on TCGdex")
        card = self.catalog.card_from_detail(detail)
        console = self._console(card.set_name)
        if card.tcgplayer_id:  # the pricing step finds the id here, so the build never searches for this card again
            registry = self.open_registry()
            registry.put(CardRef(card.name, card.number, console).key, card.tcgplayer_id, "tcgdex", card.name)
            registry.save()
        self.store.append({
            "id": f"tcgdex:{card.card_id}", "product-name": f"{card.name} #{card.number}", "console-name": console,
            "price-in-pennies": "0", "include-string": "Ungraded", "condition-string": "Normal wear", "condition-id": "1",
            "notes": note, "cost-basis-in-pennies": "0", "quantity": str(qty), "date-entered": self.today().isoformat()})
        return {"name": card.name, "set": card.set_name, "number": card.number, "condition": cond.value, "qty": qty,
                "tcgplayerId": card.tcgplayer_id}

    def _console(self, set_name: str) -> str:
        """The collection's own spelling of this set when it already has cards from it, else 'Pokemon <set>'."""
        for c in sorted({r["console-name"] for r in self.store.rows()}):
            if set_score([set_name], c) == 2:
                return c
        return f"Pokemon {set_name}"

    # ---------------------------------------------------------- edit / remove
    def update(self, key: str, condition: Optional[str] = None, qty: Optional[int] = None) -> dict:
        cond = _condition(condition) if condition is not None else None
        new_qty = _qty(qty) if qty is not None else None

        def change(r: Row) -> None:
            if cond is not None:
                if (r.get("grading-company") or "").strip():
                    raise ServiceError(400, "graded cards have no wear condition")
                r["notes"] = _note(cond, strip_wear_words(r.get("notes")))
            if new_qty is not None:
                old = max(int(r.get("quantity") or 1), 1)
                for col in ("price-in-pennies", "cost-basis-in-pennies"):  # row totals: keep the per-card amounts
                    r[col] = str(round(int(r.get(col) or 0) / old * new_qty))
                r["quantity"] = str(new_qty)

        row = self._edit(key, change)
        now = parse_condition(row["notes"]).condition
        return {"key": key, "condition": now.value if now else None, "qty": int(row["quantity"])}

    def remove(self, key: str) -> None:
        try:
            self.store.delete(key)
        except KeyError:
            raise ServiceError(404, STALE) from None

    def _edit(self, key: str, change: Callable[[Row], None]) -> Row:
        try:
            return self.store.edit(key, change)
        except KeyError:
            raise ServiceError(404, STALE) from None
