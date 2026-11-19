"""Tests for scripts/manage (search, add, edit, remove) and scripts/serve.py. Fake cards only (Testmon, Test Set);
temp files only; no network, no real collection, no price API.

Run:  python3 -m unittest discover -s tests -v
"""
import csv
import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
from datetime import date
from http.server import BaseHTTPRequestHandler as BaseHTTPRequestHandlerBase, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import serve  # noqa: E402
from manage import COLUMNS, CollectionService, CsvCollection, Rebuilder, ServiceError, load_aliases, row_keys  # noqa: E402
from pricing import (CardCatalog, CardRef, Condition, IdRegistry, JustTcgClient, PricingService, ProviderError, TtlCache,  # noqa: E402
                     strip_wear_words)
from pricing.collection import price_entries  # noqa: E402
from pricing.net import HttpResult, request_json  # noqa: E402
from serve import STATIC, make_handler  # noqa: E402
from test_pricing import FakeJustTcg, FakeFetch  # noqa: E402


def tcg(card_id, name, number, set_name, pid=None, rarity="Rare", variants=None):
    d = {"id": card_id, "name": name, "localId": number, "rarity": rarity, "image": f"https://img.test/{card_id}",
         "set": {"name": set_name}, "pricing": {"tcgplayer": {"normal": {"productId": pid}}} if pid else {}}
    if variants:
        d["variants_detailed"] = variants
    return d


def variant(kind, pid=None, **extra):
    return {"type": kind, **({"thirdParty": {"tcgplayer": pid}} if pid else {}), **extra}


PAGES = {
    "dexsearch_testmon__.json": [{"id": "ts-1"}, {"id": "ts-2"}, {"id": "xx-1"}],
    "dexsearch_testmon__testset.json": [{"id": "ts-1"}, {"id": "ts-2"}],
    "dexsearch_testmon_2_.json": [{"id": "ts-2"}],
    "dexcard_en_ts-1.json": tcg("ts-1", "Testmon", "1", "Test Set", 9),
    "dexcard_en_ts-2.json": tcg("ts-2", "Testmon ex", "2", "Test Set"),            # TCGdex has no TCGplayer id for this one
    "dexcard_en_xx-1.json": tcg("xx-1", "Testmon", "1", "Other Set", 77),
    "dexcard_en_ts-3.json": tcg("ts-3", "Testchu", "3", "Test Set", 30, variants=[variant("normal", 30), variant("reverse", 30)]),
    "dexcard_en_ts-4.json": tcg("ts-4", "Testzam ex", "4", "Test 151", 40, variants=[variant("holo", 40)]),
}
ROW = {"id": "1001", "product-name": "Otherchu #5", "console-name": "Pokemon Test Set", "price-in-pennies": "900",
       "include-string": "Ungraded", "condition-string": "Normal wear", "condition-id": "1", "sku": "", "notes": "LP - corner whitening",
       "cost-basis-in-pennies": "300", "quantity": "3", "date-entered": "2025-01-01", "date-purchased": "", "grading-company": "",
       "grading-cert-id": "", "folder": "Want"}


def read(path, mode="r"):
    with open(path, mode, **({} if "b" in mode else {"encoding": "utf-8"})) as f:
        return f.read()


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.csv = os.path.join(self.dir.name, "collection.csv")
        self.ids = os.path.join(self.dir.name, "ids.json")
        self.fetch = FakeFetch(dict(PAGES))
        self.svc = CollectionService(CardCatalog(self.fetch), lambda: IdRegistry(self.ids), CsvCollection(self.csv),
                                     today=lambda: date(2026, 11, 19))

    def write_csv(self, rows, newline="\n"):
        with open(self.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator=newline)
            w.writeheader()
            w.writerows(rows)

    def rows(self):
        return CsvCollection(self.csv).rows()


class WearWords(unittest.TestCase):
    def test_strip_keeps_only_the_users_own_text(self):
        for note, rest in {"LP": "", "": "", "LP - corner whitening": "corner whitening", "near mint, from a show": "from a show",
                           "Moderately Played (edge wear)": "(edge wear)", "bought at a show": "bought at a show"}.items():
            self.assertEqual(strip_wear_words(note), rest, note)


class CsvStore(Base):
    def test_rewrite_keeps_columns_order_and_line_endings(self):
        self.write_csv([ROW], "\r\n")
        before = read(self.csv, "rb")
        CsvCollection(self.csv).edit(row_keys([ROW])[0], lambda r: None)
        self.assertEqual(read(self.csv, "rb"), before)

    def test_each_change_leaves_the_previous_file_beside_it(self):
        self.write_csv([ROW])
        CsvCollection(self.csv).delete(row_keys([ROW])[0])
        prev = os.path.join(self.dir.name, "collection.prev.csv")
        self.assertEqual(len(list(csv.DictReader(read(prev).splitlines()))), 1)
        self.assertEqual(self.rows(), [])

    def test_identical_rows_get_distinct_keys(self):
        self.assertEqual(row_keys([ROW, ROW])[0][:-1], row_keys([ROW, ROW])[1][:-1])
        self.assertEqual(len(set(row_keys([ROW, ROW]))), 2)

    def test_a_missing_file_starts_with_the_export_columns(self):
        CsvCollection(self.csv).append({"id": "x", "product-name": "Testmon #1"})
        self.assertEqual(read(self.csv).splitlines()[0].split(","), COLUMNS)

    def test_unknown_key_raises(self):
        self.write_csv([ROW])
        with self.assertRaises(KeyError):
            CsvCollection(self.csv).delete("nope")


class Search(Base):
    def test_results_carry_image_set_number_rarity_and_id(self):
        out = self.svc.search("Testmon", "Test Set")
        self.assertEqual(out["total"], 2)
        self.assertEqual(out["results"][0], {"id": "ts-1", "name": "Testmon", "set": "Test Set", "number": "1", "rarity": "Rare",
                                             "image": "https://img.test/ts-1/low.webp", "tcgplayerId": "9",
                                             "printings": [{"key": "default", "label": "Standard"}]})
        self.assertIsNone(out["results"][1]["tcgplayerId"])

    def test_number_and_set_narrow_the_query_on_the_server(self):
        self.svc.search("Testmon", number="2")
        self.svc.search("Testmon", set_name="Test Set")
        listings = [u for u in self.fetch.urls if "/cards?" in u]
        self.assertIn("localId=2", listings[0])
        self.assertIn("set.name=Test+Set", listings[1])

    def test_only_the_requested_page_is_fetched_in_full(self):
        self.svc.search("Testmon", limit=1)
        self.assertEqual([u for u in self.fetch.urls if "/cards/" in u], ["https://api.tcgdex.net/v2/en/cards/ts-1"])

    def test_short_queries_and_outages_are_clean_errors(self):
        for bad in ("", " a "):
            with self.assertRaises(ServiceError) as cm:
                self.svc.search(bad)
            self.assertEqual(cm.exception.status, 400)
        with self.assertRaises(ServiceError) as cm:
            self.svc.search("Unknownmon")   # the fake source has no page: TCGdex "did not answer"
        self.assertEqual(cm.exception.status, 502)


class Add(Base):
    def test_a_new_row_in_the_export_format_with_wear_in_notes(self):
        out = self.svc.add("ts-1", "lp", 2, "corner whitening")
        row, = self.rows()
        self.assertEqual(out, {"name": "Testmon", "set": "Test Set", "number": "1", "condition": "LP", "qty": 2,
                               "printing": "Standard", "tcgplayerId": "9"})
        self.assertEqual({k: row[k] for k in ("id", "product-name", "console-name", "notes", "quantity", "date-entered", "price-in-pennies")},
                         {"id": "tcgdex:ts-1:default", "product-name": "Testmon #1", "console-name": "Pokemon Test Set",
                          "notes": "LP - corner whitening", "quantity": "2", "date-entered": "2026-11-19", "price-in-pennies": "0"})
        self.assertEqual(list(row), COLUMNS)

    def test_the_tcgplayer_id_goes_to_the_id_registry_under_the_pricing_key(self):
        self.svc.add("ts-1", "NM")
        hit = IdRegistry(self.ids).get(CardRef("Testmon", "1", "Pokemon Test Set").key)
        self.assertEqual((hit["id"], hit["source"]), ("9", "tcgdex"))

    def test_a_card_without_an_id_is_still_added_and_nothing_is_guessed(self):
        self.svc.add("ts-2", "NM")
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(IdRegistry(self.ids).cards, {})

    def test_an_id_a_build_saved_since_the_server_started_survives(self):
        self.svc.add("ts-1", "NM")
        reg = IdRegistry(self.ids)
        reg.put("another|key", "5", "pkmnprices")
        reg.save()
        self.svc.add("xx-1", "NM")
        self.assertIn("another|key", IdRegistry(self.ids).cards)

    def test_a_set_already_in_the_collection_keeps_its_spelling(self):
        self.write_csv([dict(ROW, **{"console-name": "Pokemon Test Set"}), dict(ROW, id="2", **{"console-name": "Pokemon Other Set"})])
        self.svc.add("xx-1", "NM")
        self.assertEqual(self.rows()[-1]["console-name"], "Pokemon Other Set")

    def test_inputs_are_validated_before_anything_is_written(self):
        for args in (("ts-1", "XX"), ("ts-1", "NM", 0), ("ts-1", "NM", 1000), ("ts-1", "NM", "2"), ("ts-1", "NM", True),
                     ("ts-1", "LP", 1, "was HP at first"), ("ts-1", "NM", 1, "x" * 201), ("../etc", "NM"), ("nope-1", "NM")):
            with self.assertRaises(ServiceError, msg=args):
                self.svc.add(*args)
        self.assertFalse(os.path.exists(self.csv))
        self.assertEqual(IdRegistry(self.ids).cards, {})

    def test_the_added_row_is_priced_at_its_own_condition_without_any_id_lookup(self):
        self.svc.add("ts-1", "LP", 2)
        row, = self.rows()
        name, number = row["product-name"].rsplit(" #", 1)
        entry = {"pcId": row["id"], "product": row["product-name"], "console": row["console-name"], "name": name, "variant": None,
                 "number": number, "notes": row["notes"], "qty": 2, "valueCents": 0, "unitCents": 0}
        fake = FakeJustTcg()
        service = PricingService(CardCatalog(FakeFetch({})), IdRegistry(self.ids), TtlCache(os.path.join(self.dir.name, "p.json"), 3600),
                                 JustTcgClient("k", request=fake, pace=0, sleep=lambda s: None))
        price_entries([entry], service, lambda e: None)
        self.assertEqual((entry["price"]["state"], entry["price"]["cond"], entry["price"]["pid"]), ("priced", "LP", "9"))
        self.assertEqual((service.id_lookups, fake.calls), (0, [[{"tcgplayerId": "9", "condition": "LP"}]]))
        price_entries([dict(entry, price=None)], service, lambda e: None)   # second build: cached, no new request
        self.assertEqual(len(fake.calls), 1)


class EditRemove(Base):
    def setUp(self):
        super().setUp()
        self.write_csv([ROW])
        self.key = row_keys([ROW])[0]

    def test_condition_is_rewritten_in_the_notes_and_the_users_text_kept(self):
        out = self.svc.update(self.key, condition="HP")
        self.assertEqual(out, {"key": self.key, "condition": "HP", "qty": 3})
        self.assertEqual(self.rows()[0]["notes"], "HP - corner whitening")

    def test_quantity_scales_the_row_totals_so_per_card_amounts_hold(self):
        self.svc.update(self.key, qty=6)
        r = self.rows()[0]
        self.assertEqual((r["quantity"], r["price-in-pennies"], r["cost-basis-in-pennies"], r["notes"]), ("6", "1800", "600", "LP - corner whitening"))

    def test_graded_cards_have_no_wear_condition(self):
        self.write_csv([dict(ROW, **{"grading-company": "PSA"})])
        with self.assertRaises(ServiceError):
            self.svc.update(row_keys(self.rows())[0], condition="NM")
        self.assertEqual(self.rows()[0]["notes"], "LP - corner whitening")

    def test_remove_and_stale_keys(self):
        self.svc.remove(self.key)
        self.assertEqual(self.rows(), [])
        for call in (lambda: self.svc.remove(self.key), lambda: self.svc.update(self.key, qty=1)):
            with self.assertRaises(ServiceError) as cm:
                call()
            self.assertEqual(cm.exception.status, 404)


def multi_printing_fake():
    """JustTCG stand-in whose product has two printings at different prices, so the one picked shows in the price."""
    class Fake(FakeJustTcg):
        def __call__(self, url, headers=None, body=None, **kw):
            self.calls.append(body)
            return HttpResult(200, {"data": [{"tcgplayerId": i["tcgplayerId"], "variants": [
                {"condition": "Near Mint", "printing": pr, "price": cents / 100, "priceStatus": "current", "lastUpdated": 1_700_000_000,
                 "language": "English"} for pr, cents in (("Normal", 100), ("Reverse Holofoil", 500))]}
                for i in body], "_metadata": {}}, {})
    return Fake()


def priced(row, fake, dir_, ids, pricing_cls=PricingService):
    """Run one collection row through the real pricing path with a fake JustTCG; returns the entry."""
    name, number = row["product-name"].rsplit(" #", 1)
    tag = None
    if name.endswith("]"):
        name, tag = name[:-1].rsplit(" [", 1)
    entry = {"pcId": row["id"], "product": row["product-name"], "console": row["console-name"], "name": name, "variant": tag,
             "number": number, "notes": row["notes"], "qty": 1, "valueCents": 0, "unitCents": 0}
    service = pricing_cls(CardCatalog(FakeFetch({})), IdRegistry(ids), TtlCache(os.path.join(dir_, "p.json"), 3600),
                          JustTcgClient("k", request=fake, pace=0, sleep=lambda s: None))
    cov = price_entries([entry], service, lambda e: None)
    return entry, cov


class Printings(Base):
    def test_options_follow_what_tcgdex_lists_and_pricing_can_tell_apart(self):
        card = lambda *v: CardCatalog.printings_in({"variants_detailed": list(v), "pricing": {"tcgplayer": {"holofoil": {"productId": 7}}}})
        opts = card(variant("normal", 1), variant("reverse", 1))
        self.assertEqual([(o.key, o.label, o.tag, o.tcgplayer_id) for o in opts],
                         [("normal", "Normal", None, "1"), ("reverse", "Reverse Holo", "Reverse Holo", "1")])
        opts = card(variant("holo", 2, subtype="unlimited"), variant("holo", 3, stamp=["1st-edition"], subtype="shadowless"),
                    variant("holo", 4, stamp=["1st-edition"]), variant("holo", 5, subtype="shadowless"),
                    variant("holo", 6, stamp=["staff"]), variant("holo", 8, size="jumbo"))
        self.assertEqual([(o.key, o.tag, o.tcgplayer_id) for o in opts], [("holo", "Holo", "2"), ("1st-holo", "1st Edition", "3")])
        self.assertEqual(card(variant("normal", 1), variant("holo", 2))[0].tag, "Normal")   # both exist: the tag says which
        only = card(variant("holo"))                 # no id on the variant, one printing: the card's own id
        self.assertEqual((only[0].tag, only[0].tcgplayer_id), ("Holo", "7"))
        self.assertEqual([(o.key, o.tcgplayer_id) for o in card()], [("default", "7")])       # nothing detailed: one standard printing

    def test_search_offers_the_printings(self):
        out = CollectionService._view(CardCatalog(self.fetch).card_from_detail(PAGES["dexcard_en_ts-3.json"]))
        self.assertEqual(out["printings"], [{"key": "normal", "label": "Normal"}, {"key": "reverse", "label": "Reverse Holo"}])

    def test_the_choice_is_written_where_pricing_reads_it_and_gets_its_own_registry_key(self):
        self.svc.add("ts-3", "NM", 1, "", "reverse")
        row, = self.rows()
        self.assertEqual((row["product-name"], row["id"]), ("Testchu [Reverse Holo] #3", "tcgdex:ts-3:reverse"))
        self.assertEqual(IdRegistry(self.ids).get(CardRef("Testchu", "3", "Pokemon Test Set", "Reverse Holo").key)["id"], "30")
        self.assertIsNone(IdRegistry(self.ids).get(CardRef("Testchu", "3", "Pokemon Test Set").key))

    def test_each_printing_is_priced_from_its_own_justtcg_variant(self):
        for printing in ("normal", "reverse", None):
            self.svc.add("ts-3", "NM", 1, "", printing)
        entries = [priced(r, multi_printing_fake(), self.dir.name, self.ids)[0] for r in self.rows()]
        self.assertEqual([(e["price"]["printing"], e["unitCents"]) for e in entries],
                         [("Normal", 100), ("Reverse Holofoil", 500), ("Normal", 100)])   # no choice = the default (first) printing

    def test_the_same_card_in_two_printings_gets_two_distinct_row_keys(self):
        self.svc.add("ts-3", "NM", 1, "", "normal")
        self.svc.add("ts-3", "NM", 1, "", "reverse")
        keys = row_keys(self.rows())
        self.assertEqual(len(set(k.rsplit("|", 1)[0] for k in keys)), 2)

    def test_an_unknown_printing_is_refused_and_nothing_is_written(self):
        with self.assertRaises(ServiceError) as cm:
            self.svc.add("ts-3", "NM", 1, "", "1st-holo")
        self.assertEqual(cm.exception.status, 400)
        self.assertIn("Reverse Holo", str(cm.exception))
        self.assertFalse(os.path.exists(self.csv))


class Aliases(Base):
    def setUp(self):
        super().setUp()
        self.svc.aliases = {"test151": "Test Violet 151"}

    def test_a_listed_set_lands_in_the_collections_own_set_group(self):
        self.svc.add("ts-4", "NM")
        row, = self.rows()
        self.assertEqual(row["console-name"], "Pokemon Test Violet 151")
        self.assertEqual(IdRegistry(self.ids).get(CardRef("Testzam ex", "4", "Pokemon Test Violet 151", "Holo").key)["id"], "40")

    def test_names_match_without_regard_to_case_accents_or_punctuation(self):
        self.svc.aliases = load_aliases(os.path.join(os.path.dirname(serve.__file__), "manage", "set_aliases.json"))
        for name in ("151", "Pokémon GO", "pokemon go"):
            self.assertTrue(self.svc._console(name).startswith("Pokemon "), name)
        self.assertEqual(self.svc._console("151"), "Pokemon Scarlet & Violet 151")
        self.assertEqual(self.svc._console("SWSH Black Star Promos"), "Pokemon Promo")

    def test_an_unlisted_set_is_unchanged(self):
        self.assertEqual(self.svc._console("Base Set"), "Pokemon Base Set")

    def test_the_committed_table_is_well_formed(self):
        with open(os.path.join(os.path.dirname(serve.__file__), "manage", "set_aliases.json"), encoding="utf-8") as f:
            raw = json.load(f)
        table = {k: v for k, v in raw.items() if not k.startswith("_")}
        self.assertGreaterEqual(len(table), 3)
        self.assertTrue(all(isinstance(v, str) and v.strip() and not v.startswith("Pokemon ") for v in table.values()))
        self.assertEqual(len(load_aliases(os.path.join(os.path.dirname(serve.__file__), "manage", "set_aliases.json"))), len(table))


class PricePending(Base):
    def run_one(self, fake):
        self.svc.add("ts-1", "NM")
        return priced(self.rows()[0], fake, self.dir.name, self.ids)

    def test_a_spent_quota_is_pending_not_no_price_and_a_later_run_clears_it(self):
        entry, cov = self.run_one(FakeJustTcg(fail=429))
        self.assertEqual((entry["price"]["state"], entry["price"].get("pending")), ("none", True))
        self.assertEqual((cov.pending, cov.priced), (1, 0))
        self.assertIn("1 row(s) wait on a price", cov.format())
        self.assertEqual(cov.to_json()["pending"], 1)
        entry, cov = priced(self.rows()[0], FakeJustTcg(), self.dir.name, self.ids)   # the next build gets an answer
        self.assertEqual((entry["price"]["state"], entry["price"].get("pending"), cov.pending), ("priced", None, 0))

    def test_outages_and_the_build_budget_are_pending_but_a_rejected_key_is_not(self):
        for fail, pending in ((429, True), (503, True), (401, False), (403, False)):
            out = JustTcgClient("k", request=FakeJustTcg(fail=fail), pace=0, sleep=lambda s: None).fetch([("1", Condition.NM)])
            self.assertEqual(out[("1", Condition.NM)].pending, pending, fail)
        down = JustTcgClient("k", request=lambda *a, **kw: HttpResult(0, {"error": "URLError"}, {}), pace=0).fetch([("1", Condition.NM)])
        self.assertTrue(down[("1", Condition.NM)].pending)       # network error
        out = JustTcgClient("k", max_requests=0, request=FakeJustTcg()).fetch([("1", Condition.NM)])
        self.assertTrue(out[("1", Condition.NM)].pending)
        self.assertFalse(ProviderError("x").pending)

    def test_pending_is_not_cached_so_the_retry_costs_one_request(self):
        fake = FakeJustTcg(fail=429)
        self.run_one(fake)
        ok = FakeJustTcg()
        priced(self.rows()[0], ok, self.dir.name, self.ids)
        self.assertEqual(len(ok.calls), 1)


class Quota(unittest.TestCase):
    def serve(self, body, status=429):
        hits = []

        class H(BaseHTTPRequestHandlerBase):
            def do_POST(self):
                hits.append(1)
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        return f"http://127.0.0.1:{httpd.server_address[1]}/", hits

    def test_a_spent_daily_or_monthly_quota_is_not_retried_but_a_rate_limit_is(self):
        for code, tries in (("DAILY_LIMIT_EXCEEDED", 1), ("REQUEST_LIMIT_EXCEEDED", 1), ("RATE_LIMIT_EXCEEDED", 3)):
            url, hits = self.serve({"error": "x", "code": code})
            res = request_json(url, body=[], sleep=lambda s: None, no_retry_429=("DAILY_LIMIT_EXCEEDED", "REQUEST_LIMIT_EXCEEDED"))
            self.assertEqual((res.status, len(hits)), (429, tries), code)


class Registry(Base):
    def test_saving_keeps_ids_another_writer_saved_meanwhile(self):
        mine = IdRegistry(self.ids)
        theirs = IdRegistry(self.ids)
        theirs.put("a|1", "5", "tcgdex")
        theirs.put_miss("b|2", "no match")
        theirs.save()
        mine.put("c|3", "6", "tcgdex")
        mine.save()
        self.assertEqual(sorted(IdRegistry(self.ids).cards), ["a|1", "c|3"])
        self.assertIn("b|2", IdRegistry(self.ids).misses)
        theirs.put("b|2", "7", "tcgdex")   # a card found later replaces its recorded miss
        theirs.save()
        self.assertNotIn("b|2", IdRegistry(self.ids).misses)


class RebuildAfterChange(Base):
    def test_every_change_asks_for_a_rebuild_and_a_refused_one_does_not(self):
        calls = []
        self.svc.on_change = lambda: calls.append(1)
        self.svc.add("ts-1", "NM")
        key = row_keys(self.rows())[0]
        self.svc.update(key, qty=2)
        self.svc.remove(key)
        self.assertEqual(len(calls), 3)
        for bad in (lambda: self.svc.add("ts-1", "ZZ"), lambda: self.svc.update(key, qty=1), lambda: self.svc.remove(key)):
            with self.assertRaises(ServiceError):
                bad()
        self.assertEqual(len(calls), 3)

    def test_a_burst_runs_one_build_and_one_more_and_never_two_at_once(self):
        gate, started, live, peak, runs = threading.Event(), threading.Event(), [0], [0], []

        def run():
            live[0] += 1
            peak[0] = max(peak[0], live[0])
            runs.append(1)
            started.set()
            gate.wait(5)
            live[0] -= 1
            return True, "", len(runs) - 1
        rb = Rebuilder(run)
        rb.request()
        self.assertTrue(started.wait(5))
        self.assertEqual(rb.status()["state"], "running")
        for _ in range(5):
            rb.request()
        gate.set()
        rb.wait()
        self.assertEqual((len(runs), peak[0]), (2, 1))
        self.assertEqual(rb.status(), {"state": "idle", "ok": True, "message": "", "pending": 1, "builds": 2})

    def test_a_crashing_build_is_reported_and_the_next_request_still_runs(self):
        outcomes = [RuntimeError("boom"), (True, "", 0)]

        def run():
            o = outcomes.pop(0)
            if isinstance(o, Exception):
                raise o
            return o
        rb = Rebuilder(run)
        rb.request()
        rb.wait()
        self.assertEqual((rb.status()["state"], rb.status()["ok"]), ("idle", False))
        self.assertIn("boom", rb.status()["message"])
        rb.request()
        rb.wait()
        self.assertTrue(rb.status()["ok"])


class BuildRunner(Base):
    def fake_run(self, returncode, out):
        calls = []

        def run(cmd, **kw):
            calls.append(cmd)
            return type("P", (), {"returncode": returncode, "stdout": out, "stderr": ""})()
        return run, calls

    def test_no_collection_yet_builds_the_empty_page_without_history(self):
        run, calls = self.fake_run(0, "ok\n")
        old, serve.subprocess.run = serve.subprocess.run, run
        self.addCleanup(setattr, serve.subprocess, "run", old)
        ok, message, pending = serve.build_runner(self.csv, serve.AFTER_CHANGE)()
        cmd = calls[0]
        self.assertEqual((ok, pending), (True, 0))
        self.assertNotEqual(cmd[2], self.csv)
        self.assertEqual(read(cmd[2]).split(",")[:2], ["id", "product-name"])
        self.assertIn("--no-history", cmd)
        self.assertFalse(os.path.exists(self.csv))

    def test_a_real_collection_is_built_cheaply_and_pending_rows_are_reported(self):
        self.write_csv([ROW])
        run, calls = self.fake_run(0, "x\n  2 row(s) wait on a price (JustTCG limit or outage); the next build or add retries them\n")
        old, serve.subprocess.run = serve.subprocess.run, run
        self.addCleanup(setattr, serve.subprocess, "run", old)
        self.assertEqual(serve.build_runner(self.csv, serve.AFTER_CHANGE)(), (True, "", 2))
        self.assertEqual(calls[0][2], self.csv)
        self.assertIn("--price-new-only", calls[0])
        self.assertEqual(calls[0][calls[0].index("--max-justtcg-requests") + 1], "3")
        self.assertNotIn("--no-history", calls[0])

    def test_a_failed_build_reports_its_last_line(self):
        run, _ = self.fake_run(1, "a\nTraceback\nValueError: bad\n")
        old, serve.subprocess.run = serve.subprocess.run, run
        self.addCleanup(setattr, serve.subprocess, "run", old)
        self.assertEqual(serve.build_runner(self.csv)(), (False, "ValueError: bad", 0))


class Server(Base):
    def setUp(self):
        super().setUp()
        self.web = os.path.join(self.dir.name, "web")
        os.mkdir(self.web)
        for name, text in (("index.html", "<html>"), ("app.js", "x"), ("collection.csv", "secret"), (".env", "KEY=secret")):
            with open(os.path.join(self.web, name), "w") as f:
                f.write(text)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.svc, self.web))
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.port = self.httpd.server_address[1]

    def call(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Content-Type": "application/json", **(headers or {})}
        c.request(method, path, json.dumps(body) if body is not None else None, h)
        r = c.getresponse()
        raw = r.read()
        c.close()
        return r.status, (json.loads(raw) if r.getheader("Content-Type", "").startswith("application/json") else raw.decode())

    def test_search_add_edit_remove_over_http(self):
        self.assertEqual(self.call("GET", "/api/health"), (200, {"ok": True}))
        status, out = self.call("GET", "/api/catalog/search?q=Testmon&set=Test%20Set")
        self.assertEqual((status, out["total"], out["results"][0]["id"]), (200, 2, "ts-1"))
        status, out = self.call("POST", "/api/collection/entries", {"cardId": "ts-1", "condition": "NM", "qty": 1, "notes": ""})
        self.assertEqual((status, out["condition"]), (200, "NM"))
        key = row_keys(self.rows())[0]
        from urllib.parse import quote
        self.assertEqual(self.call("PATCH", "/api/collection/entries/" + quote(key), {"condition": "MP", "qty": 4})[1]["condition"], "MP")
        self.assertEqual(self.rows()[0]["quantity"], "4")
        self.assertEqual(self.call("DELETE", "/api/collection/entries/" + quote(key))[0], 200)
        self.assertEqual(self.rows(), [])

    def test_printing_goes_through_and_the_build_status_is_served(self):
        self.assertEqual(self.call("GET", "/api/build/status")[1], {"state": "idle"})
        status, out = self.call("POST", "/api/collection/entries", {"cardId": "ts-3", "condition": "NM", "printing": "reverse"})
        self.assertEqual((status, out["printing"]), (200, "Reverse Holo"))
        self.assertEqual(self.call("POST", "/api/collection/entries", {"cardId": "ts-3", "condition": "NM", "printing": "x"})[0], 400)

    def test_errors_come_back_as_json_with_the_right_status(self):
        self.assertEqual(self.call("POST", "/api/collection/entries", {"cardId": "ts-1", "condition": "ZZ"})[0], 400)
        self.assertEqual(self.call("GET", "/api/catalog/search?q=a")[0], 400)
        self.assertEqual(self.call("DELETE", "/api/collection/entries/gone")[0], 404)
        self.assertEqual(self.call("GET", "/api/nope")[0], 404)
        self.assertEqual(self.call("POST", "/api/collection/entries", headers={"Content-Type": "application/json"})[0], 400)

    def test_writes_need_json_and_a_local_host_name(self):
        self.assertEqual(self.call("POST", "/api/collection/entries", {"cardId": "ts-1", "condition": "NM"},
                                   {"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.call("GET", "/api/health", headers={"Host": "evil.example"})[0], 403)
        self.assertFalse(os.path.exists(self.csv))

    def test_only_the_sites_own_files_are_served(self):
        self.assertEqual(self.call("GET", "/")[1], "<html>")
        self.assertEqual(self.call("GET", "/app.js")[0], 200)
        for path in ("/collection.csv", "/.env", "/../ids.json", "/%2e%2e/ids.json", "/data/cache"):
            self.assertEqual(self.call("GET", path)[0], 404, path)
        self.assertFalse(STATIC.match("collection.csv"))


if __name__ == "__main__":
    unittest.main()
