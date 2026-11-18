"""JustTCG client: per-condition TCGplayer prices by TCGplayer product id.

POST https://api.justtcg.com/v1/cards with a JSON list of {"tcgplayerId", "condition"}; up to 20 per request on the
free tier (100 requests/day, 1,000/month). Each answer lists the card's variants (one per printing) at the asked
condition, each with a price and a priceStatus.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from .domain import Condition, alnum
from .net import HttpResult, request_json

URL = "https://api.justtcg.com/v1/cards"
BATCH = 20
SOURCE = "JustTCG (TCGplayer market)"

_COND_KEYS = {"nm": Condition.NM, "nearmint": Condition.NM, "lp": Condition.LP, "lightlyplayed": Condition.LP,
              "mp": Condition.MP, "moderatelyplayed": Condition.MP, "hp": Condition.HP, "heavilyplayed": Condition.HP,
              "dmg": Condition.DMG, "damaged": Condition.DMG}


@dataclass(frozen=True)
class Listing:
    """One printing of a product at one condition."""
    printing: str                    # the provider's label, e.g. "Reverse Holofoil"
    price: Optional[float]           # USD, None when the provider has no price
    status: str                      # "current", "expired", "unpriced", ...
    updated: Optional[int] = None    # epoch seconds

    def to_json(self) -> dict:
        return {"printing": self.printing, "price": self.price, "status": self.status, "updated": self.updated}

    @staticmethod
    def from_json(d: dict) -> "Listing":
        return Listing(d.get("printing", ""), d.get("price"), d.get("status", ""), d.get("updated"))


@dataclass(frozen=True)
class ProductPrices:
    """What the provider says about one (product, condition). found=False: the provider doesn't know the product."""
    found: bool
    listings: Tuple[Listing, ...] = ()

    def to_json(self) -> dict:
        return {"found": self.found, "listings": [l.to_json() for l in self.listings]}

    @staticmethod
    def from_json(d: dict) -> "ProductPrices":
        return ProductPrices(bool(d.get("found")), tuple(Listing.from_json(x) for x in d.get("listings", [])))


class ProviderError(Exception):
    """The provider couldn't answer (quota, outage, bad key). Never cached."""


def condition_of(label: Optional[str]) -> Optional[Condition]:
    return _COND_KEYS.get(alnum(label))


def chunk_unique_ids(pairs: List[Tuple[str, Condition]], size: int = BATCH) -> List[List[Tuple[str, Condition]]]:
    """Split (product id, condition) pairs into requests of at most `size`, never putting the same product twice in
    one request (an answer is matched to its request by product id, so two conditions of one card can't share one)."""
    chunks: List[List[Tuple[str, Condition]]] = []
    for pair in pairs:
        for ch in chunks:
            if len(ch) < size and all(p != pair[0] for p, _ in ch):
                ch.append(pair)
                break
        else:
            chunks.append([pair])
    return chunks


class JustTcgClient:
    def __init__(self, api_key: str, max_requests: int = 30, request: Callable[..., HttpResult] = request_json,
                 pace: float = 0.5, sleep: Callable[[float], None] = time.sleep):
        self._key = api_key
        self.max_requests = max_requests
        self._request, self._pace, self._sleep = request, pace, sleep
        self.requests_made = 0
        self.quota: Dict[str, object] = {}   # last _metadata the API sent (plan, daily/monthly remaining)

    def fetch(self, pairs: Iterable[Tuple[str, Condition]]) -> Dict[Tuple[str, Condition], object]:
        """{(product id, condition): ProductPrices | ProviderError}. Spends one request per batch of up to 20."""
        out: Dict[Tuple[str, Condition], object] = {}
        for chunk in chunk_unique_ids(list(dict.fromkeys(pairs))):
            if self.requests_made >= self.max_requests:
                for p in chunk:
                    out[p] = ProviderError(f"request budget of {self.max_requests} reached for this build")
                continue
            if self.requests_made:
                self._sleep(self._pace)
            self.requests_made += 1
            res = self._request(URL, headers={"x-api-key": self._key}, body=[{"tcgplayerId": str(p), "condition": c.value} for p, c in chunk])
            if res.status != 200 or not isinstance(res.data, dict):
                msg = {401: "API key rejected (HTTP 401)", 403: "API key rejected (HTTP 403)",
                       429: "rate or daily quota exhausted (HTTP 429)", 0: "network error"}.get(res.status, f"HTTP {res.status}")
                for p in chunk:
                    out[p] = ProviderError(f"JustTCG: {msg}")
                continue
            self.quota = dict(res.data.get("_metadata") or {})
            by_id = {str(c.get("tcgplayerId")): c for c in res.data.get("data") or [] if isinstance(c, dict)}
            for pid, cond in chunk:
                out[(pid, cond)] = parse_product(by_id.get(str(pid)), cond)
        return out


def parse_product(card: Optional[dict], cond: Condition) -> ProductPrices:
    """A JustTCG card object -> its listings at `cond` (variants at any other condition are ignored, never used)."""
    if not card:
        return ProductPrices(False)
    listings = []
    for v in card.get("variants") or []:
        if condition_of(v.get("condition")) is not cond:
            continue
        if v.get("language") not in (None, "English"):
            continue
        price = v.get("price")
        listings.append(Listing(str(v.get("printing") or ""), float(price) if isinstance(price, (int, float)) else None,
                                str(v.get("priceStatus") or ""), v.get("lastUpdated")))
    return ProductPrices(True, tuple(listings))
