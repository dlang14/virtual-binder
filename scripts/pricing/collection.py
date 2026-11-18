"""Adapter between the build's collection rows and the pricing service, plus the coverage report.

Each row (a dict built by scripts/build.py) gets an entry["price"] block saying where its price came from:

    state "priced"    JustTCG / TCGplayer market price at the card's own condition and printing
    state "fallback"  no TCGplayer price for that exact condition + printing; PriceCharting's price from the CSV is
                      used and labelled as such (it is not condition-adjusted)
    state "skipped"   non-English card: TCGplayer is English-only; PriceCharting's price is shown, labelled
    state "none"      no price at all (and no PriceCharting price to fall back on)

unitCents / valueCents hold whichever value applies; pcUnitCents / pcValueCents always keep the CSV's PriceCharting
numbers (the row total divided by quantity) so before/after can be compared and a fallback is never mistaken for a
TCGplayer price.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from .domain import CardRef, Condition, PriceResult, parse_condition, parse_variant_tag
from .service import PriceItem, PricingService

NON_ENGLISH = re.compile(r"Japanese|Chinese|Korean|German|French|Italian|Spanish|Portuguese|Thai|Indonesian|Dutch|Russian", re.I)
FALLBACK_SOURCE = "PriceCharting"


def card_label(e: dict) -> str:
    variant = f" [{e['variant']}]" if e.get("variant") else ""
    return f"{e['name']}{variant} #{e['number']} ({re.sub(r'^Pokemon ', '', e['console'])})"


def per_card_cents(row_total_cents: int, qty: int) -> int:
    """The CSV's price is the row total, so one card is total / quantity."""
    return round(row_total_cents / qty) if qty else row_total_cents


@dataclass
class Coverage:
    rows: int = 0
    priced: int = 0
    fallback: int = 0
    skipped: int = 0
    none: int = 0
    english_rows: int = 0
    missing: List[dict] = field(default_factory=list)      # English rows without a TCGplayer price: {label, cond, reason, state}
    skipped_rows: List[dict] = field(default_factory=list)
    flags: List[str] = field(default_factory=list)         # notes that were assumed or stale
    pc_value_cents: int = 0                                # what the CSV said the whole collection was worth
    value_cents: int = 0                                   # value after pricing (all sources)
    priced_value_cents: int = 0
    fallback_value_cents: int = 0
    calls: Dict[str, object] = field(default_factory=dict)

    def to_json(self) -> dict:
        return {"rows": self.rows, "englishRows": self.english_rows, "priced": self.priced, "fallback": self.fallback,
                "skipped": self.skipped, "none": self.none, "pcValueCents": self.pc_value_cents,
                "valueCents": self.value_cents, "pricedValueCents": self.priced_value_cents,
                "fallbackValueCents": self.fallback_value_cents, "source": "JustTCG (TCGplayer market), per condition"}

    def format(self) -> str:
        money = lambda c: f"${c / 100:,.2f}"
        lines = [f"Pricing coverage: {self.priced}/{self.english_rows} English rows priced at their own condition and printing "
                 f"(JustTCG / TCGplayer market)",
                 f"  priced {self.priced} · missing {len(self.missing)} · skipped non-English {self.skipped} · total rows {self.rows}",
                 f"  value: {money(self.value_cents)} now ({money(self.priced_value_cents)} TCGplayer + {money(self.fallback_value_cents)} "
                 f"PriceCharting fallback) vs {money(self.pc_value_cents)} all PriceCharting before"]
        if self.missing:
            lines.append("  Missing a TCGplayer price (shown with a labelled PriceCharting price where the CSV has one):")
            lines += [f"    - {m['label']} [{m['cond']}]: {m['reason']}" for m in self.missing]
        if self.skipped_rows:
            lines.append("  Skipped (non-English; TCGplayer prices English cards only):")
            lines += [f"    - {m['label']}" for m in self.skipped_rows]
        if self.flags:
            lines.append("  Heads up:")
            lines += [f"    - {f}" for f in self.flags]
        c = self.calls
        if c:
            lines.append("  API calls this build: " + ", ".join(f"{k} {v}" for k, v in c.items()))
        return "\n".join(lines)


def price_entries(entries: List[dict], service: PricingService, tcgdex_id_for: Callable[[dict], Optional[str]]) -> Coverage:
    cov = Coverage(rows=len(entries))
    todo: List[tuple] = []   # (entry, PriceItem)
    for e in entries:
        e["pcValueCents"] = e["valueCents"]
        e["pcUnitCents"] = per_card_cents(e["valueCents"], e["qty"])
        cov.pc_value_cents += e["valueCents"]
        if NON_ENGLISH.search(e["console"]):
            e["price"] = {"state": "skipped", "reason": "non-English card (TCGplayer prices English cards only)"}
            continue
        cov.english_rows += 1
        cp = parse_condition(e.get("notes"))
        e["price"] = {"cond": cp.condition.value if cp.condition else None}
        if cp.how == "unrecognized":
            cov.flags.append(f"{card_label(e)}: {cp.detail}")
        if cp.condition is None:
            e["price"]["reason"] = cp.detail
            continue
        ref = CardRef(e["name"], e["number"] or "", e["console"], e.get("variant"), tcgdex_id_for(e), str(e["pcId"]))
        todo.append((e, PriceItem(ref, cp.condition, parse_variant_tag(e.get("variant")))))
    results = service.price_many([i for _, i in todo])
    for (e, _), r in zip(todo, results):
        _apply(e, r)
    for e in entries:
        _finish(e, cov)
    cov.value_cents = sum(e["valueCents"] for e in entries)
    cov.calls = _calls(service)
    return cov


def _apply(e: dict, r: PriceResult) -> None:
    p = e["price"]
    p["pid"] = r.tcgplayer_id
    p["printing"] = r.printing.value if r.printing else None
    if r.priced:
        p.update(state="priced", src=r.source, asOf=r.as_of, stale=r.stale, reason=r.reason)
        e["unitCents"] = r.cents
        e["valueCents"] = r.cents * e["qty"]
    else:
        p["reason"] = r.reason


def _finish(e: dict, cov: Coverage) -> None:
    p = e["price"]
    if p.get("state") == "priced":
        cov.priced += 1
        cov.priced_value_cents += e["valueCents"]
        if p.get("stale"):
            cov.flags.append(f"{card_label(e)}: price is not current ({p['reason']})")
        return
    non_english = p.get("state") == "skipped"
    if e["pcUnitCents"] > 0:   # labelled last-resort fallback; the value is PriceCharting's and is never relabelled as TCGplayer
        p["state"] = "skipped" if non_english else "fallback"
        p["src"] = FALLBACK_SOURCE
        e["unitCents"], e["valueCents"] = e["pcUnitCents"], e["pcValueCents"]
        cov.fallback_value_cents += e["valueCents"]
    else:
        p["state"] = "skipped" if non_english else "none"
        e["unitCents"] = e["valueCents"] = 0
    if non_english:
        cov.skipped += 1
        cov.skipped_rows.append({"label": card_label(e)})
        return
    cov.fallback += p["state"] == "fallback"
    cov.none += p["state"] == "none"
    cov.missing.append({"label": card_label(e), "cond": p.get("cond") or "?", "reason": p.get("reason", ""), "state": p["state"]})


def _calls(service: PricingService) -> Dict[str, object]:
    out: Dict[str, object] = {}
    if service.provider is not None:
        out["JustTCG requests"] = service.provider.requests_made
        q = service.provider.quota
        if q.get("apiDailyRequestsRemaining") is not None:
            out["JustTCG remaining today/month"] = f"{q.get('apiDailyRequestsRemaining')}/{q.get('apiRequestsRemaining')}"
    out["price cache hits"] = service.cache_hits
    out["TCGplayer id lookups"] = service.id_lookups
    if service.catalog.pkmn_requests:
        out["PkmnPrices searches"] = service.catalog.pkmn_requests
    return out
