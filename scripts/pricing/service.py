"""Pricing service: (card, condition, printing) -> price with its source, or no price with the reason.

Flow per build: resolve each card's TCGplayer id (registry first, so a known card costs no lookup), group the cards by
(product id, condition), answer what the 24 h cache can, fetch only the rest from JustTCG in batches of 20, then pick
each card's own printing. Nothing here knows about the CSV.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .catalog import CardCatalog, IdLookup
from .domain import (CardRef, Condition, PriceResult, Printing, PrintingWant, Status, dollars_to_cents, parse_printing, select_printing)
from .justtcg import SOURCE, JustTcgClient, ProductPrices, ProviderError
from .store import IdRegistry, TtlCache

PRICE_TTL = 24 * 3600


@dataclass(frozen=True)
class PriceItem:
    card: CardRef
    condition: Condition
    want: PrintingWant


def pick_price(prices: ProductPrices, tcgplayer_id: str, condition: Condition, want: PrintingWant) -> PriceResult:
    """The price of this card's own printing at this condition, or the reason there isn't one. Pure."""
    if not prices.found:
        return PriceResult.none(f"JustTCG has no listing for TCGplayer product {tcgplayer_id}", condition, tcgplayer_id)
    if not prices.listings:
        return PriceResult.none(f"JustTCG has no {condition.value} ({condition.label}) listing for this card", condition, tcgplayer_id)
    printing, why = select_printing(want, (parse_printing(l.printing) for l in prices.listings))
    if printing is None:
        return PriceResult.none(why, condition, tcgplayer_id)
    mine = [l for l in prices.listings if parse_printing(l.printing) is printing]
    priced = [l for l in mine if l.price is not None]
    if not priced:
        status = mine[0].status if mine else "unknown"
        return PriceResult.none(f"JustTCG has no price for {condition.value} {printing.value} (status: {status})", condition, tcgplayer_id, printing)
    l = priced[0]
    as_of = time.strftime("%Y-%m-%d", time.gmtime(l.updated)) if l.updated else None
    stale = l.status not in ("", "current")
    return PriceResult(
        status=Status.PRICED, cents=dollars_to_cents(l.price), currency="USD", source=SOURCE,
        condition=condition, printing=printing, tcgplayer_id=tcgplayer_id, as_of=as_of, stale=stale,
        reason=f"JustTCG marks this price '{l.status}'" if stale else "")


class PricingService:
    def __init__(self, catalog: CardCatalog, registry: IdRegistry, cache: TtlCache,
                 provider: Optional[JustTcgClient] = None, offline: bool = False, disabled_reason: Optional[str] = None):
        self.catalog, self.registry, self.cache, self.provider, self.offline = catalog, registry, cache, provider, offline
        self.disabled_reason = disabled_reason
        self.cache_hits = 0
        self.id_lookups = 0

    # ---------------------------------------------------------- ids
    def resolve_id(self, ref: CardRef) -> IdLookup:
        hit = self.registry.get(*(["pc:" + ref.ext_id] if ref.ext_id else []), ref.key)
        if hit:
            return IdLookup(hit["id"], hit.get("source", "registry"))
        miss = self.registry.recent_miss(ref.key)
        if miss is not None:
            return IdLookup(None, "", miss + " (looked up recently; retried after 7 days)")
        self.id_lookups += 1
        found = self.catalog.find_tcgplayer_id(ref)
        if found.tcgplayer_id:
            self.registry.put(ref.key, found.tcgplayer_id, found.source, ref.name)
        elif not found.transient:
            self.registry.put_miss(ref.key, found.reason)
        return found

    # ---------------------------------------------------------- prices
    def _pinned_printing(self, ref: CardRef) -> Optional[Printing]:
        """A printing you pinned by hand in the registry ("printing": "Holofoil" on a manual entry), if any."""
        hit = self.registry.get(*(["pc:" + ref.ext_id] if ref.ext_id else []), ref.key)
        return parse_printing(hit.get("printing")) if hit and hit.get("source") == "manual" else None

    def price_many(self, items: Sequence[PriceItem]) -> List[PriceResult]:
        if self.disabled_reason:
            return [PriceResult.none(self.disabled_reason, i.condition) for i in items]
        results: List[Optional[PriceResult]] = [None] * len(items)
        wants: List[PrintingWant] = []
        for n, i in enumerate(items):
            pinned = self._pinned_printing(i.card)
            wants.append(PrintingWant("explicit", frozenset({pinned}), f"pinned {pinned.value}") if pinned else i.want)
            if wants[n].kind == "unsupported":  # no API calls for a card we can't price faithfully
                results[n] = PriceResult.none(select_printing(wants[n], [])[1], i.condition)
        live = [n for n in range(len(items)) if results[n] is None]
        ids = {n: self.resolve_id(items[n].card) for n in live}
        wanted = list(dict.fromkeys((ids[n].tcgplayer_id, items[n].condition) for n in live if ids[n].tcgplayer_id))
        answers: Dict[Tuple[str, Condition], object] = {}
        todo = []
        for pid, cond in wanted:
            raw = self.cache.get(f"{pid}|{cond.value}")
            if raw is not None:
                answers[(pid, cond)] = ProductPrices.from_json(raw)
                self.cache_hits += 1
            else:
                todo.append((pid, cond))
        if todo:
            if self.offline:
                why = "not in the price cache (cache-only run)"
            elif self.provider is None:
                why = "no JUSTTCG_API_KEY set"
            else:
                why = ""
            if why:
                answers.update({p: ProviderError(why) for p in todo})
            else:
                for p, a in self.provider.fetch(todo).items():  # type: ignore[union-attr]
                    answers[p] = a
                    if isinstance(a, ProductPrices):
                        self.cache.put(f"{p[0]}|{p[1].value}", a.to_json())
        for n in live:
            item, look = items[n], ids[n]
            if not look.tcgplayer_id:
                results[n] = PriceResult.none(f"no TCGplayer id: {look.reason}", item.condition)
                continue
            a = answers[(look.tcgplayer_id, item.condition)]
            if isinstance(a, ProviderError):
                results[n] = PriceResult.none(str(a), item.condition, look.tcgplayer_id, pending=a.pending)
            else:
                results[n] = pick_price(a, look.tcgplayer_id, item.condition, wants[n])  # type: ignore[arg-type]
        return results  # type: ignore[return-value]

    def save(self) -> None:
        self.cache.save()
        self.registry.save()
        self.catalog.save()
