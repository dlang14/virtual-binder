#!/usr/bin/env python3
"""Local server for Virtual Binder: the static page plus a small JSON API for adding, editing and removing cards.

Usage:
    python3 scripts/serve.py [--port 8123] [--csv data/collection.csv]

Then open http://127.0.0.1:8123 (it listens on this computer only). It serves only the site's own .html/.js/.css files,
never your CSV or cache. The routes are thin wrappers over manage.CollectionService:

    GET    /api/health
    GET    /api/catalog/search?q=&set=&number=&offset=
    POST   /api/collection/entries            {"cardId", "condition", "qty", "notes", "printing"}
    PATCH  /api/collection/entries/<row key>  {"condition"?, "qty"?}
    DELETE /api/collection/entries/<row key>
    GET    /api/build/status                  the page rebuild that follows each change

Every change rebuilds binder-data.js in the background (scripts/build.py --price-new-only, so only never-priced cards
cost a JustTCG request). The first start with no page builds one, from an empty collection if there is no CSV yet.
"""
import argparse, json, os, re, subprocess, sys, tempfile, time, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from manage import COLUMNS, CollectionService, CsvCollection, Rebuilder, ServiceError, load_aliases  # noqa: E402
from pricing import CardCatalog, IdRegistry  # noqa: E402
from pricing.net import request_json  # noqa: E402

STATIC = re.compile(r"^[A-Za-z0-9_.-]+\.(html|js|css)$")
TYPES = {"html": "text/html; charset=utf-8", "js": "text/javascript; charset=utf-8", "css": "text/css; charset=utf-8"}
ENTRIES = "/api/collection/entries/"
BUILD = os.path.join(ROOT, "scripts", "build.py")
PENDING = re.compile(r"(\d+) row\(s\) wait on a price")
# After a change: price only cards never priced before, and cap the requests, so one add never costs a collection refresh.
AFTER_CHANGE = ["--price-new-only", "--max-justtcg-requests", "3", "--max-pkmnprices-requests", "3"]


def cached_fetcher(cache_dir):
    """fetch_json(url, name) for the catalog: files in the build's cache folder (same names, so both share them)."""
    def fetch(url, name):
        path = os.path.join(cache_dir, re.sub(r'[<>:"/\\|?*\s]', "_", name))
        max_age = 7 * 86400 if name.startswith("dexsearch_") else None
        if os.path.exists(path) and (max_age is None or time.time() - os.path.getmtime(path) < max_age):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        res = request_json(url, tries=2, timeout=15)
        if res.status != 200 or not isinstance(res.data, (list, dict)):
            return None
        os.makedirs(cache_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(res.data, f)
        return res.data
    return fetch


def build_runner(csv_path, extra=()):
    """run() for the Rebuilder: scripts/build.py on the collection (or an empty one while there is no CSV yet)."""
    def run():
        source, flags = csv_path, list(extra)
        if not os.path.exists(csv_path):   # nothing added yet: build the empty page, and leave no history snapshot behind
            empty = os.path.join(tempfile.gettempdir(), "virtual-binder-empty.csv")
            with open(empty, "w", encoding="utf-8", newline="") as f:
                f.write(",".join(COLUMNS) + "\n")
            source, flags = empty, flags + ["--no-history"]
        p = subprocess.run([sys.executable, BUILD, source, *flags], capture_output=True, text=True, timeout=900)
        out = p.stdout + p.stderr
        pending = PENDING.search(out)
        lines = [ln for ln in out.splitlines() if ln.strip()]
        return p.returncode == 0, "" if p.returncode == 0 else (lines[-1] if lines else "build failed"), int(pending.group(1)) if pending else 0
    return run


def make_service(csv_path, ids_path, cache_dir, rebuilder=None):
    aliases = load_aliases(os.path.join(os.path.dirname(os.path.abspath(__file__)), "manage", "set_aliases.json"))
    return CollectionService(CardCatalog(cached_fetcher(cache_dir)), lambda: IdRegistry(ids_path), CsvCollection(csv_path),
                             aliases=aliases, on_change=rebuilder.request if rebuilder else (lambda: None))


def make_handler(service, web_root=ROOT, rebuilder=None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            sys.stderr.write("%s %s\n" % (self.command, self.path.split("?")[0]))

        def send(self, status, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def dispatch(self, method):
            url = urllib.parse.urlsplit(self.path)
            try:
                host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
                if host not in ("127.0.0.1", "localhost"):   # blocks DNS-rebinding pages from talking to this server
                    raise ServiceError(403, "use http://127.0.0.1:<port>")
                if not url.path.startswith("/api/"):
                    return self.static(url.path) if method == "GET" else self.send(405, {"error": "method not allowed"})
                if method != "GET" and self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    raise ServiceError(415, "send JSON")   # a plain cross-site form post cannot set this header
                body = self.read_json() if method in ("POST", "PATCH") else {}
                self.send(200, self.route(method, url, body))
            except ServiceError as e:
                self.send(e.status, {"error": str(e)})
            except Exception as e:  # keep the server up; the page shows the message
                sys.stderr.write("error: %r\n" % (e,))
                self.send(500, {"error": "unexpected error; see the server log"})

        def read_json(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > 10_000:
                raise ServiceError(413, "request too large")
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                raise ServiceError(400, "invalid JSON") from None
            if not isinstance(body, dict):
                raise ServiceError(400, "expected a JSON object")
            return body

        def route(self, method, url, body):
            q = dict(urllib.parse.parse_qsl(url.query))
            if (method, url.path) == ("GET", "/api/health"):
                return {"ok": True}
            if (method, url.path) == ("GET", "/api/build/status"):
                return rebuilder.status() if rebuilder else {"state": "idle"}
            if (method, url.path) == ("GET", "/api/catalog/search"):
                return service.search(q.get("q", ""), q.get("set", ""), q.get("number", ""), offset=max(int(q.get("offset", 0) or 0), 0))
            if (method, url.path) == ("POST", ENTRIES.rstrip("/")):
                return service.add(body.get("cardId", ""), body.get("condition"), body.get("qty", 1), str(body.get("notes") or ""),
                                   body.get("printing") or None)
            if url.path.startswith(ENTRIES):
                key = urllib.parse.unquote(url.path[len(ENTRIES):])
                if method == "PATCH":
                    return service.update(key, body.get("condition"), body.get("qty"))
                if method == "DELETE":
                    service.remove(key)
                    return {"removed": key}
            raise ServiceError(404, "no such route")

        def static(self, path):
            name = "index.html" if path == "/" else path.lstrip("/")
            file = os.path.join(web_root, name)
            if not STATIC.match(name) or not os.path.isfile(file):
                return self.send(404, {"error": "not found"})
            with open(file, "rb") as f:
                self.send(200, f.read(), TYPES[name.rsplit(".", 1)[1]])

        do_GET = lambda self: self.dispatch("GET")
        do_POST = lambda self: self.dispatch("POST")
        do_PATCH = lambda self: self.dispatch("PATCH")
        do_DELETE = lambda self: self.dispatch("DELETE")
    return Handler


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", type=int, default=8123)
    ap.add_argument("--csv", default=os.path.join(ROOT, "data", "collection.csv"))
    args = ap.parse_args()
    rebuilder = Rebuilder(build_runner(args.csv, AFTER_CHANGE))
    service = make_service(args.csv, os.path.join(ROOT, "data", "tcgplayer_ids.json"), os.path.join(ROOT, "data", "cache"), rebuilder)
    if not os.path.exists(os.path.join(ROOT, "binder-data.js")):   # first start: build the page before serving it
        print("No page built yet; building it first (about a minute the first time)...", flush=True)
        ok, message, _ = build_runner(args.csv)()
        if not ok:
            sys.exit(f"The first build failed: {message}")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(service, ROOT, rebuilder))
    print(f"Virtual Binder: http://127.0.0.1:{args.port}  (collection: {args.csv}; Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
