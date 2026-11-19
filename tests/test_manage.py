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
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from manage import COLUMNS, CollectionService, CsvCollection, ServiceError, row_keys  # noqa: E402
from pricing import CardCatalog, CardRef, IdRegistry, JustTcgClient, PricingService, TtlCache, strip_wear_words  # noqa: E402
from pricing.collection import price_entries  # noqa: E402
from serve import STATIC, make_handler  # noqa: E402
from test_pricing import FakeJustTcg, FakeFetch  # noqa: E402


def tcg(card_id, name, number, set_name, pid=None, rarity="Rare"):
    return {"id": card_id, "name": name, "localId": number, "rarity": rarity, "image": f"https://img.test/{card_id}",
            "set": {"name": set_name}, "pricing": {"tcgplayer": {"normal": {"productId": pid}}} if pid else {}}


PAGES = {
    "dexsearch_testmon__.json": [{"id": "ts-1"}, {"id": "ts-2"}, {"id": "xx-1"}],
    "dexsearch_testmon__testset.json": [{"id": "ts-1"}, {"id": "ts-2"}],
    "dexsearch_testmon_2_.json": [{"id": "ts-2"}],
    "dexcard_en_ts-1.json": tcg("ts-1", "Testmon", "1", "Test Set", 9),
    "dexcard_en_ts-2.json": tcg("ts-2", "Testmon ex", "2", "Test Set"),            # TCGdex has no TCGplayer id for this one
    "dexcard_en_xx-1.json": tcg("xx-1", "Testmon", "1", "Other Set", 77),
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
                                             "image": "https://img.test/ts-1/low.webp", "tcgplayerId": "9"})
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
        self.assertEqual(out, {"name": "Testmon", "set": "Test Set", "number": "1", "condition": "LP", "qty": 2, "tcgplayerId": "9"})
        self.assertEqual({k: row[k] for k in ("id", "product-name", "console-name", "notes", "quantity", "date-entered", "price-in-pennies")},
                         {"id": "tcgdex:ts-1", "product-name": "Testmon #1", "console-name": "Pokemon Test Set",
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
