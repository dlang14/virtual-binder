"""Domain types for card pricing: condition, printing, what a CSV variant tag means, and a price result.

Everything here is pure (no network, no files), so the rules that decide which price a card gets can be tested
on their own. The one rule everything follows: a price is only ever returned for the card's own condition and
printing. When that exact price doesn't exist the result says why; it never falls back to another condition,
printing or currency.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Optional, Sequence


def alnum(text: Optional[str]) -> str:
    """Lowercase ASCII letters and digits only: 'Pokémon & Co.' -> 'pokemonco'."""
    s = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


# ---------------------------------------------------------------- condition
class Condition(Enum):
    NM = "NM"
    LP = "LP"
    MP = "MP"
    HP = "HP"
    DMG = "DMG"

    @property
    def label(self) -> str:
        return {"NM": "Near Mint", "LP": "Lightly Played", "MP": "Moderately Played",
                "HP": "Heavily Played", "DMG": "Damaged"}[self.value]


# Whole-word spellings of each condition, matched against a lowercased note. "sp" (slightly played) is the
# old name for what TCGplayer calls Lightly Played.
_COND_WORDS = {
    Condition.NM: [r"nm", r"near\s*mint", r"nm/mt", r"mint"],
    Condition.LP: [r"lp", r"lightly\s*played", r"light\s*play", r"light\s*wear", r"slightly\s*played", r"sp"],
    Condition.MP: [r"mp", r"moderately\s*played", r"moderate\s*play", r"moderate\s*wear"],
    Condition.HP: [r"hp", r"heavily\s*played", r"heavy\s*play", r"heavy\s*wear"],
    Condition.DMG: [r"dmg", r"damaged", r"damage"],
}
_COND_RES = {c: re.compile(r"(?<![a-z0-9])(?:" + "|".join(ws) + r")(?![a-z0-9])") for c, ws in _COND_WORDS.items()}


@dataclass(frozen=True)
class ConditionParse:
    """Result of reading a CSV notes cell. condition is None only when the note names two different wear levels."""
    condition: Optional[Condition]
    how: str  # "default" (no note), "note" (recognised), "unrecognized" (text with no wear word: NM assumed), "ambiguous"
    detail: str = ""


def parse_condition(note: Optional[str]) -> ConditionParse:
    """No note means Near Mint. A note that names one wear level uses it ('LP', 'Lightly Played', 'mp - corner whitening').
    A note with no wear word at all (say, 'bought at a show') is assumed NM and flagged. A note naming two different
    levels ('LP/MP') is ambiguous and gets no price rather than a guess."""
    text = (note or "").strip()
    if not text:
        return ConditionParse(Condition.NM, "default")
    low = text.lower()
    found = [c for c, rx in _COND_RES.items() if rx.search(low)]
    # "near mint" contains the standalone word "mint"; nothing else overlaps, so a lone NM hit is fine.
    if len(found) == 1:
        return ConditionParse(found[0], "note")
    if not found:
        return ConditionParse(Condition.NM, "unrecognized", f"note {text!r} names no wear level; assumed Near Mint")
    return ConditionParse(None, "ambiguous", f"note {text!r} names several wear levels ({', '.join(c.value for c in found)})")


def strip_wear_words(note: Optional[str]) -> str:
    """The note without its wear words, so a new condition can be written in front of what is left:
    'LP - corner whitening' -> 'corner whitening'."""
    text = note or ""
    for rx in _COND_RES.values():
        text = re.compile(rx.pattern, re.I).sub(" ", text)
    text = re.sub(r"\(\s*\)", "", re.sub(r"\s+", " ", text))
    return text.strip(" -\u2013:/,;")


# ---------------------------------------------------------------- printing
class Printing(Enum):
    NORMAL = "Normal"
    HOLOFOIL = "Holofoil"
    REVERSE_HOLOFOIL = "Reverse Holofoil"
    UNLIMITED = "Unlimited"
    UNLIMITED_HOLOFOIL = "Unlimited Holofoil"
    FIRST_EDITION = "1st Edition"
    FIRST_EDITION_HOLOFOIL = "1st Edition Holofoil"


_PRINTING_BY_KEY = {alnum(p.value): p for p in Printing}


def parse_printing(text: Optional[str]) -> Optional[Printing]:
    """A provider's printing label ('Reverse Holofoil', '1st Edition Holofoil', ...) -> Printing; None if unknown."""
    return _PRINTING_BY_KEY.get(alnum(text))


BASE_PRINTINGS = frozenset({Printing.NORMAL, Printing.HOLOFOIL, Printing.UNLIMITED, Printing.UNLIMITED_HOLOFOIL})
FIRST_EDITION_PRINTINGS = frozenset({Printing.FIRST_EDITION, Printing.FIRST_EDITION_HOLOFOIL})


@dataclass(frozen=True)
class PrintingWant:
    """What the collection says about a card's printing.

    kind "default":     no variant tag: the card's base printing (see select_printing).
    kind "explicit":    a tag we understand; allowed is the set of provider printings that can match it.
    kind "unsupported": a tag naming a distinct product ('Jumbo', 'Knockout Collection', ...) that these price
                        sources can't be trusted to distinguish; such cards get no price instead of the base card's.
    """
    kind: str
    allowed: frozenset = frozenset()
    tag: Optional[str] = None


_EXPLICIT_TAGS = {
    "holo": frozenset({Printing.HOLOFOIL, Printing.UNLIMITED_HOLOFOIL}),
    "holofoil": frozenset({Printing.HOLOFOIL, Printing.UNLIMITED_HOLOFOIL}),
    "reverseholo": frozenset({Printing.REVERSE_HOLOFOIL}),
    "reverseholofoil": frozenset({Printing.REVERSE_HOLOFOIL}),
    "1stedition": FIRST_EDITION_PRINTINGS,
    "unlimited": frozenset({Printing.UNLIMITED, Printing.UNLIMITED_HOLOFOIL}),
}


def parse_variant_tag(tag: Optional[str]) -> PrintingWant:
    """The [bracket] part of a PriceCharting product name ('Machamp [Holo] #68') -> PrintingWant."""
    if not (tag or "").strip():
        return PrintingWant("default")
    allowed = _EXPLICIT_TAGS.get(alnum(tag))
    if allowed:
        return PrintingWant("explicit", allowed, tag)
    return PrintingWant("unsupported", frozenset(), tag)


def select_printing(want: PrintingWant, available: Iterable[Optional[Printing]]) -> "tuple[Optional[Printing], str]":
    """Pick the one printing of a product that is this card. Returns (printing, "") or (None, reason).

    `available` is every printing the product has at the wanted condition, priced or not, so ambiguity is judged on
    the product itself and not on which printings happen to have a price today.
    """
    have = [p for p in dict.fromkeys(available) if p is not None]
    names = sorted(p.value for p in have) or ["none"]
    if want.kind == "unsupported":
        return None, (f"variant '{want.tag}' is a distinct product the price sources can't identify "
                      "(pin its TCGplayer id in data/tcgplayer_ids.json to price it)")
    if want.kind == "explicit":
        hits = [p for p in have if p in want.allowed]
        if len(hits) == 1:
            return hits[0], ""
        if not hits:
            return None, f"no printing matching '{want.tag}' (product has: {', '.join(names)})"
        return None, f"'{want.tag}' matches several printings ({', '.join(sorted(p.value for p in hits))})"
    # default: the base printing. A product with a single printing is that printing (unless it's 1st Edition only,
    # which would be a different card than an untagged row).
    non_first = [p for p in have if p not in FIRST_EDITION_PRINTINGS]
    if len(have) == 1 and non_first:
        return have[0], ""
    base = [p for p in have if p in BASE_PRINTINGS]
    if len(base) == 1:
        return base[0], ""
    if not base:
        return None, f"no base printing (product has: {', '.join(names)})"
    return None, f"base printing is ambiguous (product has: {', '.join(names)})"


# ---------------------------------------------------------------- card reference and price result
@dataclass(frozen=True)
class CardRef:
    """A card as a person names it. No condition, price or CSV details: just which card."""
    name: str
    number: str
    set_name: str
    variant: Optional[str] = None
    tcgdex_id: Optional[str] = None   # a hint when the caller already matched the card in TCGdex
    ext_id: Optional[str] = None      # caller's own id (the CSV's PriceCharting id); lets a manual override pin one product

    @property
    def key(self) -> str:
        return "|".join([alnum(self.set_name), alnum(re.sub(r"^0+(?=\d)", "", self.number.split("/")[0])), alnum(self.name),
                         alnum(self.variant)])


class Status(Enum):
    PRICED = "priced"
    NO_PRICE = "no_price"


@dataclass(frozen=True)
class PriceResult:
    status: Status
    cents: Optional[int] = None
    currency: str = "USD"
    source: str = ""
    condition: Optional[Condition] = None
    printing: Optional[Printing] = None
    tcgplayer_id: Optional[str] = None
    as_of: Optional[str] = None     # date the source last updated this price, YYYY-MM-DD
    stale: bool = False             # the source marks the price as not current
    reason: str = ""                # why there is no price, or a caveat on a price

    @property
    def priced(self) -> bool:
        return self.status is Status.PRICED

    @staticmethod
    def none(reason: str, condition: Optional[Condition] = None, tcgplayer_id: Optional[str] = None,
             printing: Optional[Printing] = None) -> "PriceResult":
        return PriceResult(Status.NO_PRICE, None, condition=condition, tcgplayer_id=tcgplayer_id, printing=printing, reason=reason)


def dollars_to_cents(value: float) -> int:
    return int(round(float(value) * 100))
