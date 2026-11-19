"""Card catalog: find cards by name / set / number and resolve each to a TCGplayer product id.

Independent of the CSV and the build script. A search UI can call `search()` for candidates and `find_tcgplayer_id()`
for a card it already has; `pricing.service.PricingService` then turns (id, condition, printing) into a price.

Sources: TCGdex (free, no key) lists cards and carries TCGplayer product ids; PkmnPrices (key, 1 credit per search)
is the rescue for cards TCGdex has no id for, such as some promos.
"""
from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Callable, List, Optional, Sequence, Tuple

from .domain import CardRef, alnum
from .net import request_json
from .store import TtlCache

TCGDEX = "https://api.tcgdex.net/v2/en"
PKMNPRICES = "https://api.pkmnprices.com/v1"

# fetch_json(url, cache_name) -> parsed JSON or None. The build passes its own cached fetcher.
FetchJson = Callable[[str, str], object]


@dataclass(frozen=True)
class CatalogCard:
    source: str                      # "tcgdex" or "pkmnprices"
    card_id: str                     # that source's id for the card
    name: str
    set_name: str
    number: str
    image: Optional[str] = None
    tcgplayer_id: Optional[str] = None
    marks: Tuple[str, ...] = ()      # stamp / pattern / distribution that make this a special product ("Pokemon Center Exclusive")
    rarity: Optional[str] = None


class CatalogUnavailable(Exception):
    """The card source could not be reached (as opposed to reached and found nothing)."""


@dataclass(frozen=True)
class IdLookup:
    tcgplayer_id: Optional[str]
    source: str = ""                 # "tcgdex" | "pkmnprices" when found
    reason: str = ""                 # why not, when not found
    transient: bool = False          # the miss is down to a budget or outage, not the card, so don't remember it


def norm_number(n: Optional[str]) -> str:
    """'034/165' -> '34', 'SWSH286' -> 'swsh286'."""
    return re.sub(r"^0+(?=\d)", "", (n or "").strip().lower().split("/")[0])


def _set_key(name: str) -> str:
    """'ME: 30th Celebration' -> '30thcelebration' (drops a 'Pokemon ' prefix and a 'SV05:'-style era prefix)."""
    name = re.sub(r"^Pokemon\s+", "", name or "")
    return alnum(re.sub(r"^[A-Za-z]{1,5}\d{0,2}:\s*", "", name))


def set_score(wanted: Sequence[str], actual: str) -> int:
    """How well a set name fits any of the wanted names: 2 same name, 1 one contains the other, 0 no."""
    a, best = _set_key(actual), 0
    for w in (_set_key(x) for x in wanted if x):
        if w and a and w == a:
            return 2
        if w and a and (w in a or a in w):
            best = 1
    return best


def set_matches(wanted: str, actual: str) -> bool:
    """Loose set-name match: 'Pokemon Promo' vs 'ME: Mega Evolution Promo', 'Jungle' vs 'Jungle'."""
    return set_score([wanted], actual) > 0


def _strip_parens(name: str) -> str:
    """'Gengar (Prime)' -> 'Gengar'."""
    return re.sub(r"\s*\([^)]*\)\s*", " ", name or "").strip()


def _name_close(a: str, b: str) -> bool:
    a, b = alnum(a), alnum(b)
    return a == b or SequenceMatcher(None, a, b).ratio() >= 0.85


class CardCatalog:
    def __init__(self, fetch_json: FetchJson, pkmnprices_key: Optional[str] = None, search_cache: Optional[TtlCache] = None,
                 request: Callable = request_json, max_pkmn_requests: int = 60):
        self._fetch, self._pk_key, self._cache, self._request = fetch_json, pkmnprices_key, search_cache, request
        self.max_pkmn_requests = max_pkmn_requests
        self.pkmn_requests = 0

    def save(self) -> None:
        if self._cache:
            self._cache.save()

    # -------------------------------------------------------------- TCGdex
    def tcgdex_card(self, card_id: str) -> Optional[dict]:
        return self._fetch(f"{TCGDEX}/cards/{urllib.parse.quote(card_id)}", f"dexcard_en_{card_id.replace('/', '_')}.json")  # type: ignore[return-value]

    @staticmethod
    def tcgplayer_id_in(detail: Optional[dict]) -> Optional[str]:
        """TCGplayer product id from a TCGdex card's pricing block (the same id under every printing)."""
        tp = ((detail or {}).get("pricing") or {}).get("tcgplayer") or {}
        for v in tp.values():
            if isinstance(v, dict) and v.get("productId"):
                return str(v["productId"])
        return None

    def search(self, name: str, set_name: Optional[str] = None, number: Optional[str] = None, limit: int = 10) -> List[CatalogCard]:
        """Candidate cards from TCGdex whose name contains `name`, optionally narrowed by set and printed number.
        Each carries its TCGplayer id when TCGdex has one."""
        q = {"name": name}
        if number:
            q["localId"] = norm_number(number)
        listing = self._fetch(f"{TCGDEX}/cards?{urllib.parse.urlencode(q)}", f"dexsearch_{alnum(name)}_{alnum(number)}.json")
        out: List[CatalogCard] = []
        for brief in (listing or [])[:60]:  # type: ignore[union-attr]
            if len(out) >= limit:
                break
            d = self.tcgdex_card(brief["id"])
            if not d:
                continue
            sname = (d.get("set") or {}).get("name", "")
            if set_name and not set_matches(set_name, sname):
                continue
            out.append(self.card_from_detail(d))
        return out

    def card_from_detail(self, d: dict) -> CatalogCard:
        return CatalogCard("tcgdex", d["id"], d.get("name", ""), (d.get("set") or {}).get("name", ""), str(d.get("localId", "")),
                           (d.get("image") + "/high.webp") if d.get("image") else None, self.tcgplayer_id_in(d),
                           rarity=d.get("rarity"))

    def browse(self, name: str, set_name: Optional[str] = None, number: Optional[str] = None,
               limit: int = 12, offset: int = 0) -> Tuple[List[CatalogCard], int]:
        """One page of TCGdex cards whose name contains `name` (set filtered by TCGdex itself), and how many match in all.
        Only the cards on the page are fetched in full; a card seen before comes from the cache. Raises CatalogUnavailable."""
        q = {"name": name}
        if number:
            q["localId"] = norm_number(number)
        if set_name:
            q["set.name"] = set_name
        listing = self._fetch(f"{TCGDEX}/cards?{urllib.parse.urlencode(q)}",
                              f"dexsearch_{alnum(name)}_{alnum(number)}_{alnum(set_name)}.json")
        if not isinstance(listing, list):
            raise CatalogUnavailable("TCGdex did not answer")
        details = (self.tcgdex_card(b["id"]) for b in listing[offset:offset + limit])
        return [self.card_from_detail(d) for d in details if d], len(listing)

    # -------------------------------------------------------------- PkmnPrices
    def pkmn_search(self, name: str, number: Optional[str], set_names: Sequence[str]) -> Tuple[List[CatalogCard], str, bool]:
        """Search PkmnPrices by name + number; keep results whose name, number and set fit.
        Returns (cards best-matching the set, reason if none, whether a failure was transient)."""
        if not self._pk_key:
            return [], "no PkmnPrices key", False
        q = {"name": name, "per_page": 10}
        if number:
            q["number"] = number.split("/")[0].strip()   # as printed ('TG01'): the API is case-sensitive about letters
        qs = urllib.parse.urlencode(q)
        cached = self._cache.get(f"pkmn|{qs}") if self._cache else None
        if cached is None:
            if self.pkmn_requests >= self.max_pkmn_requests:
                return [], "PkmnPrices request budget for this build reached", True
            self.pkmn_requests += 1
            res = self._request(f"{PKMNPRICES}/cards?{qs}", headers={"x-api-key": self._pk_key})
            if res.status != 200 or not isinstance(res.data, dict):
                return [], f"PkmnPrices HTTP {res.status}", True
            cached = res.data.get("data") or []
            if self._cache:
                self._cache.put(f"pkmn|{qs}", cached)
        scored = []
        for r in cached:
            sname = (r.get("set") or {}).get("name", "")
            if not r.get("tcg_player_id") or (number and norm_number(r.get("number")) != norm_number(number)):
                continue
            sc = set_score(set_names, sname)
            # A tail like "(Prime)" is only forgiven when the set matches exactly; in a loose set it marks a different card.
            if sc and (_name_close(name, r.get("name", "")) or (sc == 2 and _name_close(name, _strip_parens(r.get("name", ""))))):
                marks = tuple(str(r[k]) for k in ("stamp", "pattern", "distribution", "placement") if r.get(k))
                scored.append((sc, CatalogCard("pkmnprices", str(r.get("id")), r.get("name", ""), sname, str(r.get("number", "")),
                                               r.get("image_url"), str(r["tcg_player_id"]), marks)))
        if not scored:
            return [], "no PkmnPrices result matches name, number and set", False
        top = max(sc for sc, _ in scored)
        return [c for sc, c in scored if sc == top], "", False

    # -------------------------------------------------------------- resolve
    def find_tcgplayer_id(self, ref: CardRef) -> IdLookup:
        """TCGplayer product id for a card: TCGdex first (by its id if the caller has one, else by search), then the
        PkmnPrices rescue. Ambiguity is a miss, never a guess."""
        why = []
        set_names = [ref.set_name]
        if ref.tcgdex_id:
            detail = self.tcgdex_card(ref.tcgdex_id)
            pid = self.tcgplayer_id_in(detail)
            if pid:
                return IdLookup(pid, "tcgdex")
            why.append("TCGdex has no TCGplayer id for this card")
            tset = ((detail or {}).get("set") or {}).get("name")
            if tset:
                set_names.append(tset)
        else:
            hits = [c for c in self.search(ref.name, ref.set_name, ref.number) if alnum(c.name) == alnum(ref.name)
                    and norm_number(c.number) == norm_number(ref.number)]
            ids = {c.tcgplayer_id for c in hits if c.tcgplayer_id}
            if len(ids) == 1:
                return IdLookup(ids.pop(), "tcgdex")
            why.append("TCGdex search found no single card with a TCGplayer id" if not ids else "TCGdex search is ambiguous")
        cards, reason, transient = self.pkmn_search(ref.name, ref.number, set_names)
        ids = {c.tcgplayer_id for c in cards}
        if len(ids) > 1:
            # An untagged collection row is the plain product, not the stamped / patterned / exclusive one.
            plain = {c.tcgplayer_id for c in cards if not c.marks}
            if len(plain) == 1:
                ids = plain
        if len(ids) == 1:
            return IdLookup(ids.pop(), "pkmnprices")
        why.append(f"PkmnPrices has {len(ids)} different products for this name and number" if ids else reason)
        return IdLookup(None, "", "; ".join(why), transient)
