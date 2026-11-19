"""Tests for the JustTCG and PkmnPrices request limits. A fake clock stands in for time: sleeping advances it, nothing really waits,
and no API is called.

Run:  python3 -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from pricing import CardCatalog, Condition, JustTcgClient  # noqa: E402
from pricing.net import HttpResult, RateLimiter  # noqa: E402
from test_pricing import FakeFetch  # noqa: E402


class FakeTime:
    def __init__(self):
        self.t, self.slept = 1000.0, []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def ok(meta=None):
    return HttpResult(200, {"data": [], "_metadata": meta or {}}, {})


def limited(code="RATE_LIMIT_EXCEEDED", retry_after=None):
    return HttpResult(429, {"error": "x", "code": code}, {"Retry-After": str(retry_after)} if retry_after is not None else {})


class Server:
    """Answers each request from a script (the last answer repeats) and records when it was asked, by the fake clock."""

    def __init__(self, ft, *answers):
        self.ft, self.answers, self.at = ft, list(answers), []

    def __call__(self, url, headers=None, body=None, **kw):
        self.at.append(self.ft.now())
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


def client(ft, server, **kw):
    return JustTcgClient("k", request=server, pace=0, sleep=ft.sleep, clock=ft.now, **kw)


def pairs(n):   # n distinct products = ceil(n / 20) requests
    return [(str(i), Condition.NM) for i in range(n)]


class Limiter(unittest.TestCase):
    def test_calls_within_the_limit_never_wait_and_the_next_waits_for_the_oldest_to_age_out(self):
        ft = FakeTime()
        lim = RateLimiter(3, 60, ft.now, ft.sleep)
        for _ in range(3):
            lim.wait()
            ft.t += 10
        self.assertEqual(ft.slept, [])
        lim.wait()                         # t=1030: the first call (t=1000) leaves the window at t=1060
        self.assertEqual(ft.slept, [30])
        lim.limit = 1                      # a lowered limit holds the next call until only one is left in the window
        lim.wait()
        self.assertEqual(sum(ft.slept), 30 + 60)


class JustTcgPerMinute(unittest.TestCase):
    def test_a_long_build_stays_under_nine_requests_in_any_minute(self):
        ft = FakeTime()
        srv = Server(ft, ok())
        c = client(ft, srv)
        c.fetch(pairs(25 * 20))            # 25 requests
        self.assertEqual((c.requests_made, len(srv.at)), (25, 25))
        for i, t in enumerate(srv.at):
            self.assertLessEqual(sum(1 for u in srv.at if t - 60 < u <= t), 9, f"request {i}")
        self.assertGreaterEqual(srv.at[-1] - srv.at[0], 120)   # 25 requests at 9 a minute take at least two minutes

    def test_the_plans_own_limit_from_the_answer_replaces_the_default(self):
        for rate, used in ((10, 9), (50, 45), (100, 90), (1, 1)):
            ft = FakeTime()
            c = client(ft, Server(ft, ok({"apiRateLimit": rate})))
            c.fetch(pairs(20))
            self.assertEqual(c._limiter.limit, used, rate)
        ft = FakeTime()
        srv = Server(ft, ok({"apiRateLimit": 50}))
        client(ft, srv).fetch(pairs(30 * 20))
        self.assertEqual((len(srv.at), [x for x in ft.slept if x]), (30, []))   # a 50 a minute plan isn't held to the free plan's 9

    def test_a_per_minute_429_waits_for_retry_after_then_succeeds(self):
        ft = FakeTime()
        srv = Server(ft, limited(retry_after=7), ok())
        c = client(ft, srv)
        out = c.fetch([("1", Condition.NM)])
        self.assertFalse(isinstance(out[("1", Condition.NM)], Exception))
        self.assertEqual((c.requests_made, ft.slept), (2, [7.0]))

    def test_without_retry_after_it_waits_out_the_minute(self):
        ft = FakeTime()
        srv = Server(ft, limited(), ok())
        client(ft, srv).fetch([("1", Condition.NM)])
        self.assertEqual(srv.at[1] - srv.at[0], 60)

    def test_retries_are_bounded_and_the_message_names_the_per_minute_limit(self):
        ft = FakeTime()
        srv = Server(ft, limited(retry_after=2))
        c = client(ft, srv)
        err = c.fetch([("1", Condition.NM)])[("1", Condition.NM)]
        self.assertEqual((len(srv.at), ft.slept), (3, [2.0, 2.0]))
        self.assertTrue(err.pending)
        self.assertIn("per-minute", str(err))
        self.assertNotIn("daily", str(err))

    def test_a_daily_limit_is_not_retried_names_itself_and_stops_the_rest_of_the_build(self):
        ft = FakeTime()
        srv = Server(ft, limited("DAILY_LIMIT_EXCEEDED", retry_after=40000))
        c = client(ft, srv)
        out = c.fetch(pairs(60))           # three batches
        self.assertEqual((len(srv.at), [x for x in ft.slept if x]), (1, []))
        errs = {str(v) for v in out.values()}
        self.assertEqual(len(errs), 1)
        self.assertIn("daily request limit", errs.pop())
        self.assertTrue(all(v.pending for v in out.values()))

    def test_a_monthly_limit_says_monthly(self):
        ft = FakeTime()
        srv = Server(ft, limited("REQUEST_LIMIT_EXCEEDED"))
        err = client(ft, srv).fetch([("1", Condition.NM)])[("1", Condition.NM)]
        self.assertEqual(len(srv.at), 1)
        self.assertIn("monthly request limit", str(err))

    def test_the_request_cap_counts_every_attempt_so_the_add_path_cap_of_three_holds(self):
        ft = FakeTime()
        srv = Server(ft, limited(retry_after=1))
        c = client(ft, srv, per_minute=100)
        c.max_requests = 3
        out = c.fetch(pairs(60))           # first batch uses all three attempts, so the cap is reached
        self.assertEqual(len(srv.at), 3)
        self.assertTrue(all(v.pending for v in out.values()))
        self.assertIn("budget", str(out[("59", Condition.NM)]))

    def test_other_errors_are_not_retried(self):
        for status in (401, 403, 500):
            ft = FakeTime()
            srv = Server(ft, HttpResult(status, {"error": "x"}, {}))
            err = client(ft, srv).fetch([("1", Condition.NM)])[("1", Condition.NM)]
            self.assertEqual((len(srv.at), ft.slept), (1, []), status)
            self.assertEqual(err.pending, status == 500)


class PkmnPrices(unittest.TestCase):
    def search(self, ft, answers, limit=2):
        calls = []

        def req(url, headers=None, **kw):
            calls.append(kw)
            return answers.pop(0) if len(answers) > 1 else answers[0]
        cat = CardCatalog(FakeFetch({}), "k", None, req, limiter=RateLimiter(limit, 60, ft.now, ft.sleep))
        return cat, calls

    def test_searches_are_spread_to_the_per_minute_limit(self):
        ft = FakeTime()
        cat, _ = self.search(ft, [HttpResult(200, {"data": []}, {})])
        for name in ("A", "B", "C"):
            cat.pkmn_search(name, "1", ["Set"])
        self.assertEqual(ft.slept, [60])      # the third waits for the first to leave the minute

    def test_a_daily_429_is_not_retried_and_says_daily(self):
        ft = FakeTime()
        body = {"error": {"code": "credit_limit_exceeded", "limit_type": "daily", "retry_after": 41000}}
        cat, calls = self.search(ft, [HttpResult(429, body, {})])
        _, reason, transient = cat.pkmn_search("A", "1", ["Set"])
        self.assertIn("daily limit", reason)
        self.assertTrue(transient)
        self.assertEqual(calls[0]["no_retry_429"], ("credit_limit_exceeded",))

    def test_a_per_minute_429_says_per_minute(self):
        ft = FakeTime()
        cat, _ = self.search(ft, [HttpResult(429, {"error": {"code": "rate_limit_exceeded", "limit_type": "per_minute"}}, {})])
        self.assertIn("per-minute limit", cat.pkmn_search("A", "1", ["Set"])[1])


if __name__ == "__main__":
    unittest.main()
