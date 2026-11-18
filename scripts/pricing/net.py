"""Small HTTP and key helpers. Standard library only."""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Dict, NamedTuple, Optional

UA = "virtual-binder/1.0 (personal collection viewer)"


class HttpResult(NamedTuple):
    status: int          # 0 = network failure
    data: object         # parsed JSON (or {"error": text})
    headers: dict


def request_json(url: str, *, headers: Optional[dict] = None, body: object = None, method: Optional[str] = None,
                 tries: int = 3, timeout: int = 40, sleep: Callable[[float], None] = time.sleep) -> HttpResult:
    """GET (or POST when body is given) and parse JSON. Retries network errors and 429s (honouring Retry-After, capped
    at 30 s). Never raises; a failure comes back as a status code with {"error": ...} data. The caller's headers
    (which may hold an API key) are never logged or put in the result."""
    payload = json.dumps(body).encode() if body is not None else None
    hdrs = {"User-Agent": UA, "Accept": "application/json"}
    if body is not None:
        hdrs["Content-Type"] = "application/json"
    hdrs.update(headers or {})
    err = "unknown error"
    for attempt in range(tries):
        req = urllib.request.Request(url, data=payload, headers=hdrs, method=method or ("POST" if body is not None else "GET"))
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                text = r.read().decode("utf-8", "replace")
                return HttpResult(r.status, json.loads(text) if text.strip() else None, dict(r.headers))
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")[:500]
            try:
                data = json.loads(text)
            except ValueError:
                data = {"error": text}
            if e.code == 429 and attempt < tries - 1:
                try:
                    wait = min(float(e.headers.get("Retry-After", "")), 30.0)
                except ValueError:
                    wait = 5.0 * (attempt + 1)
                sleep(wait)
                continue
            return HttpResult(e.code, data, dict(e.headers))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:  # network trouble or non-JSON body
            err = type(e).__name__
            sleep(2.0)
    return HttpResult(0, {"error": err}, {})


def load_env_file(path: str) -> Dict[str, str]:
    """Read KEY=VALUE lines from a .env file ('#' comments, optional quotes, optional 'export '). Missing file -> {}."""
    out: Dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$", line)
                if not m:
                    continue
                v = m.group(2)
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                    v = v[1:-1]
                out[m.group(1)] = v
    except OSError:
        pass
    return out


def get_keys(env_path: str, names=("JUSTTCG_API_KEY", "PKMNPRICES_API_KEY")) -> Dict[str, str]:
    """API keys by variable name: real environment variables win over the .env file. Empty values are dropped.
    Callers should report which names are present, never the values."""
    file_vals = load_env_file(env_path)
    keys = {}
    for n in names:
        v = (os.environ.get(n) or file_vals.get(n) or "").strip()
        if v:
            keys[n] = v
    return keys
