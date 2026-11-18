"""Tests for scripts/pricing. Fake cards only (Testmon, Test Set); no network, no real collection data.

Run:  python3 -m unittest discover -s tests -v
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from pricing import (CardCatalog, CardRef, Condition, IdRegistry, JustTcgClient, Listing, PriceItem, PricingService,  # noqa: E402
                     Printing, ProductPrices, ProviderError, Status, TtlCache, parse_condition, parse_variant_tag,
                     pick_price, select_printing)
from pricing.collection import NON_ENGLISH, per_card_cents, price_entries  # noqa: E402
from pricing.justtcg import chunk_unique_ids, parse_product  # noqa: E402
from pricing.net import HttpResult, get_keys, load_env_file  # noqa: E402

P = Printing


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def listing(printing, price, status="current", updated=1_700_000_000):
    return Listing(printing, price, status, updated)


def want(tag=None):
    return parse_variant_tag(tag)


class ConditionParsing(unittest.TestCase):
    def test_no_note_is_near_mint(self):
        r = parse_condition("")
        self.assertEqual((r.condition, r.how), (Condition.NM, "default"))
        self.assertEqual(parse_condition(None).condition, Condition.NM)
        self.assertEqual(parse_condition("   ").condition, Condition.NM)

    def test_wear_spellings(self):
        cases = {"LP": Condition.LP, "lp": Condition.LP, "Lightly Played": Condition.LP, "light play": Condition.LP,
                 "SP": Condition.LP, "slightly played": Condition.LP, "MP": Condition.MP, "Moderately Played": Condition.MP,
                 "moderate play": Condition.MP, "HP": Condition.HP, "heavily played": Condition.HP,
                 "DMG": Condition.DMG, "Damaged": Condition.DMG, "NM": Condition.NM, "Near Mint": Condition.NM,
                 "Mint": Condition.NM, "mp - corner whitening": Condition.MP, "LP (edge wear)": Condition.LP}
        for text, cond in cases.items():
            r = parse_condition(text)
            self.assertEqual((r.condition, r.how), (cond, "note"), text)

    def test_words_that_merely_contain_letters_are_not_wear(self):
        for text in ("help", "ramp", "split", "Cosmos"):
            r = parse_condition(text)
            self.assertEqual(r.how, "unrecognized", text)

    def test_unrecognized_note_assumes_nm_but_says_so(self):
        r = parse_condition("bought at a show")
        self.assertEqual((r.condition, r.how), (Condition.NM, "unrecognized"))
        self.assertIn("assumed Near Mint", r.detail)

    def test_two_wear_levels_is_ambiguous_not_a_guess(self):
        r = parse_condition("LP/MP")
        self.assertIsNone(r.condition)
        self.assertEqual(r.how, "ambiguous")


class PrintingRules(unittest.TestCase):
    def test_tag_mapping(self):
        self.assertEqual(want().kind, "default")
        self.assertEqual(want("Reverse Holo").allowed, frozenset({P.REVERSE_HOLOFOIL}))
        self.assertIn(P.UNLIMITED_HOLOFOIL, want("Holo").allowed)
        self.assertEqual(want("1st Edition").allowed, frozenset({P.FIRST_EDITION, P.FIRST_EDITION_HOLOFOIL}))
        for tag in ("Jumbo", "Knockout Collection", "World Championship 2026", "Cosmos Holo"):
            self.assertEqual(want(tag).kind, "unsupported", tag)

    def test_default_picks_the_base_printing(self):
        self.assertEqual(select_printing(want(), [P.HOLOFOIL, P.REVERSE_HOLOFOIL])[0], P.HOLOFOIL)
        self.assertEqual(select_printing(want(), [P.NORMAL, P.REVERSE_HOLOFOIL])[0], P.NORMAL)
        self.assertEqual(select_printing(want(), [P.UNLIMITED_HOLOFOIL, P.FIRST_EDITION_HOLOFOIL])[0], P.UNLIMITED_HOLOFOIL)

    def test_default_single_printing_is_that_printing(self):
        self.assertEqual(select_printing(want(), [P.REVERSE_HOLOFOIL])[0], P.REVERSE_HOLOFOIL)

    def test_default_never_becomes_first_edition(self):
        p, why = select_printing(want(), [P.FIRST_EDITION_HOLOFOIL])
        self.assertIsNone(p)
        self.assertIn("no base printing", why)

    def test_default_ambiguous_base_printings_get_no_guess(self):
        p, why = select_printing(want(), [P.NORMAL, P.HOLOFOIL])
        self.assertIsNone(p)
        self.assertIn("ambiguous", why)

    def test_explicit_tag_needs_that_printing(self):
        self.assertEqual(select_printing(want("Reverse Holo"), [P.NORMAL, P.REVERSE_HOLOFOIL])[0], P.REVERSE_HOLOFOIL)
        p, why = select_printing(want("Reverse Holo"), [P.NORMAL, P.HOLOFOIL])
        self.assertIsNone(p)
        self.assertIn("Reverse Holo", why)
        self.assertEqual(select_printing(want("1st Edition"), [P.UNLIMITED_HOLOFOIL, P.FIRST_EDITION_HOLOFOIL])[0], P.FIRST_EDITION_HOLOFOIL)

    def test_unsupported_variant_never_matches(self):
        p, why = select_printing(want("Jumbo"), [P.HOLOFOIL])
        self.assertIsNone(p)
        self.assertIn("Jumbo", why)

    def test_unlisted_printing_labels_are_ignored(self):
        self.assertIsNone(select_printing(want(), [None])[0])


class PickPriceNoSubstitution(unittest.TestCase):
    def test_priced_at_own_condition_and_printing(self):
        r = pick_price(ProductPrices(True, (listing("Holofoil", 12.34), listing("Reverse Holofoil", 1.0))), "1", Condition.LP, want())
        self.assertEqual((r.status, r.cents, r.printing, r.condition, r.currency), (Status.PRICED, 1234, P.HOLOFOIL, Condition.LP, "USD"))
        self.assertEqual(r.as_of, "2023-11-14")
        self.assertFalse(r.stale)

    def test_no_listing_at_the_condition_is_no_price_not_nm(self):
        # parse_product keeps only the asked condition, so a card with only NM data returns no listings for LP
        card = {"tcgplayerId": "1", "variants": [{"condition": "Near Mint", "printing": "Holofoil", "price": 50.0, "priceStatus": "current"}]}
        prices = parse_product(card, Condition.LP)
        self.assertEqual(prices.listings, ())
        r = pick_price(prices, "1", Condition.LP, want())
        self.assertEqual(r.status, Status.NO_PRICE)
        self.assertIsNone(r.cents)
        self.assertIn("LP", r.reason)

    def test_wrong_printing_is_no_price(self):
        r = pick_price(ProductPrices(True, (listing("Normal", 0.2), listing("Holofoil", 3.0))), "1", Condition.NM, want("Reverse Holo"))
        self.assertEqual(r.status, Status.NO_PRICE)
        self.assertIsNone(r.cents)

    def test_printing_without_a_price_is_no_price_with_status(self):
        r = pick_price(ProductPrices(True, (listing("Holofoil", None, "expired"),)), "1", Condition.NM, want())
        self.assertEqual(r.status, Status.NO_PRICE)
        self.assertIn("expired", r.reason)
        self.assertEqual(r.printing, P.HOLOFOIL)

    def test_stale_price_is_flagged(self):
        r = pick_price(ProductPrices(True, (listing("Holofoil", 5.0, "expired"),)), "1", Condition.NM, want())
        self.assertTrue(r.priced)
        self.assertTrue(r.stale)
        self.assertIn("expired", r.reason)

    def test_unknown_product(self):
        r = pick_price(ProductPrices(False), "99", Condition.NM, want())
        self.assertEqual(r.status, Status.NO_PRICE)
        self.assertIn("99", r.reason)

    def test_other_languages_and_conditions_are_dropped_by_the_parser(self):
        card = {"tcgplayerId": "1", "variants": [
            {"condition": "Lightly Played", "printing": "Holofoil", "price": 9.0, "priceStatus": "current", "language": "English"},
            {"condition": "Lightly Played", "printing": "Holofoil", "price": 99.0, "priceStatus": "current", "language": "Japanese"},
            {"condition": "Near Mint", "printing": "Holofoil", "price": 20.0, "priceStatus": "current", "language": "English"}]}
        got = parse_product(card, Condition.LP)
        self.assertEqual([l.price for l in got.listings], [9.0])


class QuantityDivision(unittest.TestCase):
    def test_row_total_divided_by_quantity(self):
        self.assertEqual(per_card_cents(1078, 2), 539)
        self.assertEqual(per_card_cents(1001, 2), 500)  # rounds, never floors the cents to zero
        self.assertEqual(per_card_cents(500, 1), 500)
        self.assertEqual(per_card_cents(500, 0), 500)

    def test_non_english_detector(self):
        for c in ("Pokemon Japanese Test Set", "Pokemon Chinese 30th Celebration", "Pokemon Korean Test"):
            self.assertTrue(NON_ENGLISH.search(c), c)
        self.assertFalse(NON_ENGLISH.search("Pokemon Base Set"))


class CacheAndRegistry(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "c.json")

    def test_ttl_expiry(self):
        clock = Clock()
        c = TtlCache(self.path, 24 * 3600, clock)
        c.put("k", {"a": 1})
        self.assertEqual(c.get("k"), {"a": 1})
        clock.t += 24 * 3600 - 1
        self.assertEqual(c.get("k"), {"a": 1})
        clock.t += 2
        self.assertIsNone(c.get("k"))

    def test_survives_a_restart_until_it_expires(self):
        clock = Clock()
        c = TtlCache(self.path, 100, clock)
        c.put("k", 5)
        c.save()
        clock.t += 50
        self.assertEqual(TtlCache(self.path, 100, clock).get("k"), 5)
        clock.t += 60
        self.assertIsNone(TtlCache(self.path, 100, clock).get("k"))

    def test_registry_persists_ids_and_never_overwrites_manual(self):
        r = IdRegistry(self.path)
        r.put("a", "1", "tcgdex")
        r.put("m", "7", "manual")
        r.put("m", "8", "tcgdex")
        r.save()
        r2 = IdRegistry(self.path)
        self.assertEqual(r2.get("a")["id"], "1")
        self.assertEqual(r2.get("m")["id"], "7")
        self.assertEqual(r2.get("zzz", "a")["id"], "1")

    def test_registry_miss_expires(self):
        clock = Clock()
        r = IdRegistry(self.path, miss_ttl=100, clock=clock)
        r.put_miss("x", "nope")
        self.assertEqual(r.recent_miss("x"), "nope")
        clock.t += 101
        self.assertIsNone(r.recent_miss("x"))
        r.put("x", "5", "tcgdex")
        self.assertIsNone(r.recent_miss("x"))


class FakeJustTcg:
    """Stands in for the HTTP call. Answers any product id; 2xx unless fail is set."""

    def __init__(self, fail=None, missing=()):
        self.calls, self.fail, self.missing = [], fail, set(missing)

    def __call__(self, url, headers=None, body=None, **kw):
        self.calls.append(body)
        if self.fail:
            return HttpResult(self.fail, {"error": "x"}, {})
        data = []
        for item in body:
            if item["tcgplayerId"] in self.missing:
                continue
            data.append({"tcgplayerId": item["tcgplayerId"], "variants": [
                {"condition": {"NM": "Near Mint", "LP": "Lightly Played", "MP": "Moderately Played"}[item["condition"]],
                 "printing": "Holofoil", "price": float(item["tcgplayerId"]) / 100, "priceStatus": "current", "lastUpdated": 1_700_000_000,
                 "language": "English"}]})
        return HttpResult(200, {"data": data, "_metadata": {"apiDailyRequestsRemaining": 90, "apiRequestsRemaining": 990}}, {})


class JustTcgBatching(unittest.TestCase):
    def test_chunks_are_at_most_20_and_never_repeat_a_product(self):
        pairs = [(str(i), Condition.NM) for i in range(45)] + [("3", Condition.LP)]
        chunks = chunk_unique_ids(pairs)
        self.assertEqual(sum(len(c) for c in chunks), 46)
        for ch in chunks:
            self.assertLessEqual(len(ch), 20)
            self.assertEqual(len({p for p, _ in ch}), len(ch))
        self.assertEqual(len(chunks), 3)

    def test_one_request_per_batch(self):
        fake = FakeJustTcg()
        client = JustTcgClient("k", request=fake, pace=0, sleep=lambda s: None)
        out = client.fetch([(str(i), Condition.NM) for i in range(41)])
        self.assertEqual(client.requests_made, 3)
        self.assertEqual(len(out), 41)
        self.assertEqual(client.quota["apiDailyRequestsRemaining"], 90)

    def test_request_budget_is_enforced(self):
        fake = FakeJustTcg()
        client = JustTcgClient("k", max_requests=1, request=fake, pace=0, sleep=lambda s: None)
        out = client.fetch([(str(i), Condition.NM) for i in range(30)])
        self.assertEqual(client.requests_made, 1)
        self.assertEqual(sum(isinstance(v, ProviderError) for v in out.values()), 10)

    def test_http_errors_become_provider_errors_and_are_not_prices(self):
        client = JustTcgClient("k", request=FakeJustTcg(fail=429), pace=0, sleep=lambda s: None)
        out = client.fetch([("1", Condition.NM)])
        self.assertIsInstance(out[("1", Condition.NM)], ProviderError)
        self.assertIn("429", str(out[("1", Condition.NM)]))

    def test_the_key_is_sent_only_as_a_header(self):
        seen = {}

        def req(url, headers=None, body=None, **kw):
            seen.update(url=url, headers=headers, body=body)
            return HttpResult(200, {"data": []}, {})
        JustTcgClient("SECRET", request=req, pace=0).fetch([("1", Condition.NM)])
        self.assertEqual(seen["headers"], {"x-api-key": "SECRET"})
        self.assertNotIn("SECRET", repr(seen["url"]) + repr(seen["body"]))


class FakeCatalog:
    """Resolves ids from a dict keyed by card name; counts lookups."""

    def __init__(self, ids):
        self.ids, self.lookups, self.pkmn_requests = ids, 0, 0

    def find_tcgplayer_id(self, ref):
        from pricing.catalog import IdLookup
        self.lookups += 1
        pid = self.ids.get(ref.name)
        return IdLookup(pid, "tcgdex") if pid else IdLookup(None, "", "not in fake catalog")

    def save(self):
        pass


class ServiceFlow(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.clock = Clock()

    def make(self, fake, offline=False, key=True, ids=None):
        catalog = FakeCatalog(ids or {"Testmon": "100", "Otherchu": "200"})
        provider = JustTcgClient("k", request=fake, pace=0, sleep=lambda s: None) if key else None
        svc = PricingService(catalog, IdRegistry(os.path.join(self.dir.name, "ids.json"), clock=self.clock),
                             TtlCache(os.path.join(self.dir.name, "p.json"), 24 * 3600, self.clock), provider, offline=offline)
        return svc, catalog

    def item(self, name="Testmon", cond=Condition.NM, tag=None, ext=None):
        return PriceItem(CardRef(name, "1", "Test Set", tag, None, ext), cond, want(tag))

    def test_second_run_uses_cache_and_registry_with_no_requests(self):
        fake = FakeJustTcg()
        svc, cat = self.make(fake)
        first = svc.price_many([self.item(), self.item("Otherchu", Condition.LP)])
        svc.save()
        self.assertEqual([r.cents for r in first], [100, 200])
        self.assertEqual((len(fake.calls), cat.lookups), (1, 2))
        fake2 = FakeJustTcg()
        svc2, cat2 = self.make(fake2)
        second = svc2.price_many([self.item(), self.item("Otherchu", Condition.LP)])
        self.assertEqual([r.cents for r in second], [100, 200])
        self.assertEqual((len(fake2.calls), cat2.lookups, svc2.cache_hits), (0, 0, 2))

    def test_after_24_hours_the_prices_are_fetched_again_but_ids_are_not(self):
        fake = FakeJustTcg()
        svc, _ = self.make(fake)
        svc.price_many([self.item()])
        svc.save()
        self.clock.t += 24 * 3600 + 1
        fake2 = FakeJustTcg()
        svc2, cat2 = self.make(fake2)
        svc2.price_many([self.item()])
        self.assertEqual((len(fake2.calls), cat2.lookups), (1, 0))

    def test_same_card_two_conditions_are_priced_separately(self):
        svc, _ = self.make(FakeJustTcg())
        a, b = svc.price_many([self.item(cond=Condition.NM), self.item(cond=Condition.LP)])
        self.assertEqual((a.condition, b.condition), (Condition.NM, Condition.LP))
        self.assertTrue(a.priced and b.priced)

    def test_unsupported_variant_costs_no_calls(self):
        fake = FakeJustTcg()
        svc, cat = self.make(fake)
        r, = svc.price_many([self.item(tag="Jumbo")])
        self.assertEqual(r.status, Status.NO_PRICE)
        self.assertEqual((len(fake.calls), cat.lookups), (0, 0))

    def test_manual_pin_prices_an_unsupported_variant(self):
        fake = FakeJustTcg()
        svc, _ = self.make(fake)
        svc.registry.cards["pc:555"] = {"id": "300", "source": "manual", "printing": "Holofoil"}
        r, = svc.price_many([self.item(tag="Jumbo", ext="555")])
        self.assertEqual((r.cents, r.printing, r.tcgplayer_id), (300, P.HOLOFOIL, "300"))

    def test_unknown_card_has_a_reason(self):
        svc, _ = self.make(FakeJustTcg())
        r, = svc.price_many([self.item("Nobodymon")])
        self.assertEqual(r.status, Status.NO_PRICE)
        self.assertIn("no TCGplayer id", r.reason)

    def test_a_failed_lookup_is_not_retried_every_build(self):
        svc, cat = self.make(FakeJustTcg())
        svc.price_many([self.item("Nobodymon")])
        svc.price_many([self.item("Nobodymon")])
        self.assertEqual(cat.lookups, 1)

    def test_a_transient_miss_is_retried_next_build(self):
        from pricing.catalog import IdLookup
        svc, cat = self.make(FakeJustTcg())
        cat.find_tcgplayer_id = lambda ref: IdLookup(None, "", "budget", True)
        svc.price_many([self.item("Nobodymon")])
        self.assertIsNone(svc.registry.recent_miss(CardRef("Nobodymon", "1", "Test Set").key))

    def test_cache_only_run_makes_no_calls_and_says_so(self):
        fake = FakeJustTcg()
        svc, _ = self.make(fake, offline=True)
        r, = svc.price_many([self.item()])
        self.assertEqual(len(fake.calls), 0)
        self.assertIn("cache-only", r.reason)

    def test_no_key_is_a_reason_not_a_price(self):
        svc, _ = self.make(FakeJustTcg(), key=False)
        r, = svc.price_many([self.item()])
        self.assertEqual(r.status, Status.NO_PRICE)
        self.assertIn("JUSTTCG_API_KEY", r.reason)

    def test_provider_failure_is_not_cached(self):
        svc, _ = self.make(FakeJustTcg(fail=500))
        r, = svc.price_many([self.item()])
        self.assertEqual(r.status, Status.NO_PRICE)
        self.assertIsNone(svc.cache.get("100|NM"))

    def test_disabled_service_never_prices(self):
        svc, cat = self.make(FakeJustTcg())
        svc.disabled_reason = "off"
        r, = svc.price_many([self.item()])
        self.assertEqual((r.status, r.reason, cat.lookups), (Status.NO_PRICE, "off", 0))


def entry(name, console="Pokemon Test Set", number="1", variant=None, notes="", qty=1, total=1000, pc_id="1"):
    return {"pcId": pc_id, "product": name, "console": console, "name": name, "variant": variant, "number": number,
            "notes": notes, "qty": qty, "valueCents": total, "unitCents": per_card_cents(total, qty)}


class CollectionAdapter(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def service(self, ids=None, key=True):
        fake = FakeJustTcg()
        self.fake = fake
        return PricingService(FakeCatalog(ids or {"Testmon": "100", "Otherchu": "200"}), IdRegistry(os.path.join(self.dir.name, "i.json")),
                              TtlCache(os.path.join(self.dir.name, "p.json"), 3600),
                              JustTcgClient("k", request=fake, pace=0, sleep=lambda s: None) if key else None)

    def test_priced_rows_use_own_condition_and_per_card_price(self):
        rows = [entry("Testmon", notes="LP", qty=2, total=9999, pc_id="1"), entry("Otherchu", qty=3, total=3000, pc_id="2")]
        cov = price_entries(rows, self.service(), lambda e: None)
        a, b = rows
        self.assertEqual((a["price"]["state"], a["price"]["cond"], a["unitCents"], a["valueCents"]), ("priced", "LP", 100, 200))
        self.assertEqual((b["price"]["state"], b["price"]["cond"], b["unitCents"], b["valueCents"]), ("priced", "NM", 200, 600))
        self.assertEqual((a["pcUnitCents"], b["pcUnitCents"]), (5000, 1000))  # CSV total / qty kept for comparison
        self.assertEqual((cov.priced, len(cov.missing), cov.skipped), (2, 0, 0))
        self.assertEqual((cov.pc_value_cents, cov.value_cents, cov.priced_value_cents, cov.fallback_value_cents), (12999, 800, 800, 0))

    def test_missing_price_falls_back_to_labelled_pricecharting_per_card(self):
        rows = [entry("Nobodymon", qty=2, total=1000), entry("Testmon", variant="Jumbo")]
        cov = price_entries(rows, self.service(), lambda e: None)
        for r in rows:
            self.assertEqual((r["price"]["state"], r["price"]["src"]), ("fallback", "PriceCharting"))
            self.assertIsNone(r["price"].get("printing"))
        self.assertEqual((rows[0]["unitCents"], rows[0]["valueCents"]), (500, 1000))
        self.assertEqual((cov.priced, len(cov.missing), cov.fallback), (0, 2, 2))
        self.assertEqual((cov.priced_value_cents, cov.fallback_value_cents), (0, 2000))  # never counted as a TCGplayer value
        self.assertIn("Jumbo", cov.format())
        self.assertIn("Nobodymon", cov.format())

    def test_non_english_is_skipped_with_a_reason_and_no_calls(self):
        rows = [entry("Testmon", console="Pokemon Japanese Test Set", total=700)]
        cov = price_entries(rows, self.service(), lambda e: None)
        self.assertEqual(rows[0]["price"]["state"], "skipped")
        self.assertIn("non-English", rows[0]["price"]["reason"])
        self.assertEqual((cov.skipped, cov.english_rows, len(self.fake.calls)), (1, 0, 0))
        self.assertEqual(rows[0]["unitCents"], 700)

    def test_ambiguous_condition_note_gets_no_tcgplayer_price(self):
        rows = [entry("Testmon", notes="LP/MP")]
        cov = price_entries(rows, self.service(), lambda e: None)
        self.assertEqual(rows[0]["price"]["state"], "fallback")
        self.assertIn("several wear levels", rows[0]["price"]["reason"])
        self.assertEqual(len(self.fake.calls), 0)
        self.assertEqual(len(cov.missing), 1)

    def test_unrecognized_note_is_flagged_in_the_report(self):
        rows = [entry("Testmon", notes="from a trade")]
        cov = price_entries(rows, self.service(), lambda e: None)
        self.assertEqual(rows[0]["price"]["state"], "priced")
        self.assertTrue(any("assumed Near Mint" in f for f in cov.flags))

    def test_no_key_keeps_pricecharting_and_says_why(self):
        rows = [entry("Testmon", total=800)]
        cov = price_entries(rows, self.service(key=False), lambda e: None)
        self.assertEqual((rows[0]["price"]["state"], rows[0]["unitCents"]), ("fallback", 800))
        self.assertIn("JUSTTCG_API_KEY", rows[0]["price"]["reason"])
        self.assertEqual(cov.priced, 0)

    def test_report_lists_each_missing_card_with_its_reason(self):
        rows = [entry("Testmon"), entry("Nobodymon", pc_id="9")]
        text = price_entries(rows, self.service(), lambda e: None).format()
        self.assertIn("1/2 English rows priced", text)
        self.assertIn("Nobodymon #1 (Test Set) [NM]: no TCGplayer id", text)
        self.assertIn("JustTCG requests 1", text)

    def test_zero_pricecharting_and_no_tcgplayer_price_is_no_price(self):
        rows = [entry("Nobodymon", total=0)]
        cov = price_entries(rows, self.service(), lambda e: None)
        self.assertEqual((rows[0]["price"]["state"], rows[0]["unitCents"], cov.none), ("none", 0, 1))


class FakeFetch:
    def __init__(self, pages):
        self.pages, self.urls = pages, []

    def __call__(self, url, name):
        self.urls.append(url)
        return self.pages.get(name)


class CatalogResolution(unittest.TestCase):
    def pkmn(self, rows, status=200):
        calls = []

        def req(url, headers=None, **kw):
            calls.append(url)
            return HttpResult(status, {"data": rows}, {})
        req.calls = calls
        return req

    def test_tcgdex_id_hint_wins_and_costs_no_pkmnprices_credit(self):
        fetch = FakeFetch({"dexcard_en_ts-1.json": {"id": "ts-1", "pricing": {"tcgplayer": {"holofoil": {"productId": 4242}}}}})
        req = self.pkmn([])
        cat = CardCatalog(fetch, "k", None, req)
        got = cat.find_tcgplayer_id(CardRef("Testmon", "1", "Test Set", None, "ts-1"))
        self.assertEqual((got.tcgplayer_id, got.source, cat.pkmn_requests), ("4242", "tcgdex", 0))

    def test_pkmnprices_rescue_when_tcgdex_has_no_id(self):
        fetch = FakeFetch({"dexcard_en_ts-1.json": {"id": "ts-1", "pricing": {}}})
        rows = [{"id": 1, "tcg_player_id": 555, "name": "Testmon", "number": "001", "set": {"name": "Test Set Promo"}}]
        req = self.pkmn(rows)
        cat = CardCatalog(fetch, "k", None, req)
        got = cat.find_tcgplayer_id(CardRef("Testmon", "1", "Pokemon Test Set", None, "ts-1"))
        self.assertEqual((got.tcgplayer_id, got.source, cat.pkmn_requests), ("555", "pkmnprices", 1))

    def test_rescue_refuses_to_guess_between_products(self):
        rows = [{"id": 1, "tcg_player_id": 555, "name": "Testmon", "number": "1", "set": {"name": "Test Set"}},
                {"id": 2, "tcg_player_id": 556, "name": "Testmon", "number": "1", "set": {"name": "Test Set"}}]
        cat = CardCatalog(FakeFetch({}), "k", None, self.pkmn(rows))
        got = cat.find_tcgplayer_id(CardRef("Testmon", "1", "Test Set", None, "ts-1"))
        self.assertIsNone(got.tcgplayer_id)
        self.assertIn("2 different products", got.reason)

    def test_rescue_ignores_other_sets_and_numbers(self):
        rows = [{"id": 1, "tcg_player_id": 555, "name": "Testmon", "number": "2", "set": {"name": "Test Set"}},
                {"id": 2, "tcg_player_id": 556, "name": "Testmon", "number": "1", "set": {"name": "Elsewhere"}}]
        cat = CardCatalog(FakeFetch({}), "k", None, self.pkmn(rows))
        self.assertIsNone(cat.find_tcgplayer_id(CardRef("Testmon", "1", "Test Set", None, "ts-1")).tcgplayer_id)

    def test_untagged_row_takes_the_plain_product_over_the_stamped_one(self):
        rows = [{"id": 1, "tcg_player_id": 555, "name": "Testmon", "number": "009", "set": {"name": "Test Promo"}},
                {"id": 2, "tcg_player_id": 556, "name": "Testmon", "number": "009", "stamp": "Pokemon Center Exclusive",
                 "set": {"name": "Test Promo"}}]
        cat = CardCatalog(FakeFetch({}), "k", None, self.pkmn(rows))
        self.assertEqual(cat.find_tcgplayer_id(CardRef("Testmon", "9", "Pokemon Promo", None, "ts-1")).tcgplayer_id, "555")

    def test_exact_set_beats_a_set_that_merely_contains_the_name(self):
        rows = [{"id": 1, "tcg_player_id": 555, "name": "Testmon", "number": "19", "set": {"name": "ME: 30th Celebration"}},
                {"id": 2, "tcg_player_id": 556, "name": "Testmon", "number": "19", "set": {"name": "ME: 30th Celebration Classic Collection"}}]
        cat = CardCatalog(FakeFetch({}), "k", None, self.pkmn(rows))
        self.assertEqual(cat.find_tcgplayer_id(CardRef("Testmon", "19", "Pokemon 30th Celebration", None, "x-1")).tcgplayer_id, "555")

    def test_name_tail_is_forgiven_only_in_an_exact_set(self):
        rows = [{"id": 1, "tcg_player_id": 555, "name": "Testmon (Prime)", "number": "94", "set": {"name": "ME: Test Set Classic"}}]
        exact = CardCatalog(FakeFetch({}), "k", None, self.pkmn(rows))
        self.assertEqual(exact.find_tcgplayer_id(CardRef("Testmon", "94", "Test Set Classic", None, "x-1")).tcgplayer_id, "555")
        loose = CardCatalog(FakeFetch({}), "k", None, self.pkmn(rows))
        self.assertIsNone(loose.find_tcgplayer_id(CardRef("Testmon", "94", "Pokemon Test Set", None, "x-1")).tcgplayer_id)

    def test_budget_and_outage_misses_are_transient(self):
        cat = CardCatalog(FakeFetch({}), "k", None, self.pkmn([]), max_pkmn_requests=0)
        got = cat.find_tcgplayer_id(CardRef("Testmon", "1", "Test Set", None, "ts-1"))
        self.assertTrue(got.transient)
        cat = CardCatalog(FakeFetch({}), "k", None, self.pkmn([], status=500))
        self.assertTrue(cat.find_tcgplayer_id(CardRef("Testmon", "1", "Test Set", None, "ts-1")).transient)
        cat = CardCatalog(FakeFetch({}), "k", None, self.pkmn([]))
        self.assertFalse(cat.find_tcgplayer_id(CardRef("Testmon", "1", "Test Set", None, "ts-1")).transient)

    def test_the_printed_number_is_sent_as_is(self):
        req = self.pkmn([])
        CardCatalog(FakeFetch({}), "k", None, req).find_tcgplayer_id(CardRef("Testmon", "TG01", "Test Set", None, "ts-1"))
        self.assertIn("number=TG01", req.calls[0])

    def test_without_a_key_there_is_no_rescue(self):
        cat = CardCatalog(FakeFetch({}), None, None, self.pkmn([]))
        got = cat.find_tcgplayer_id(CardRef("Testmon", "1", "Test Set", None, "ts-1"))
        self.assertIsNone(got.tcgplayer_id)
        self.assertIn("no PkmnPrices key", got.reason)

    def test_search_filters_by_set_and_reports_ids(self):
        fetch = FakeFetch({
            "dexsearch_testmon_1.json": [{"id": "ts-1"}, {"id": "xx-1"}],
            "dexcard_en_ts-1.json": {"id": "ts-1", "name": "Testmon", "localId": "1", "set": {"name": "Test Set"},
                                     "pricing": {"tcgplayer": {"normal": {"productId": 9}}}},
            "dexcard_en_xx-1.json": {"id": "xx-1", "name": "Testmon", "localId": "1", "set": {"name": "Other Set"}, "pricing": {}}})
        got = CardCatalog(fetch).search("Testmon", "Test Set", "1")
        self.assertEqual([(c.card_id, c.tcgplayer_id) for c in got], [("ts-1", "9")])


class KeysAndEnv(unittest.TestCase):
    def test_env_file_parsing_and_precedence(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, ".env")
            with open(path, "w") as f:
                f.write("# comment\nJUSTTCG_API_KEY=\"abc\"\nexport PKMNPRICES_API_KEY=def\nEMPTY=\n")
            self.assertEqual(load_env_file(path)["JUSTTCG_API_KEY"], "abc")
            old = os.environ.get("PKMNPRICES_API_KEY")
            os.environ["PKMNPRICES_API_KEY"] = "from-env"
            try:
                keys = get_keys(path)
            finally:
                if old is None:
                    del os.environ["PKMNPRICES_API_KEY"]
                else:
                    os.environ["PKMNPRICES_API_KEY"] = old
            self.assertEqual(keys, {"JUSTTCG_API_KEY": "abc", "PKMNPRICES_API_KEY": "from-env"})

    def test_missing_env_file_is_fine(self):
        self.assertEqual(load_env_file("/nonexistent/.env"), {})


if __name__ == "__main__":
    unittest.main()
