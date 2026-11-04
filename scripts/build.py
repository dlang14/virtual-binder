#!/usr/bin/env python3
"""Virtual Binder: build binder data from a PriceCharting collection export.

Usage:
    python3 scripts/build.py [path/to/export.csv] [options]   (see --help)

Reads data/collection.csv by default, matches each card against the
Pokemon TCG API (api.pokemontcg.io) with TCGdex (api.tcgdex.net) as the
fallback, and writes:
    data/cards.json      full matched card data
    binder-data.js       the same data as a JS global, so index.html works over file://
    data/history/<csv name>/<date>.json   a value snapshot (one per day) for the Value tab
API responses are cached in data/cache/ (delete it to force a refresh).
No API key or secret is needed. Prices come only from the CSV.
"""
import argparse, concurrent.futures, csv, json, os, re, subprocess, sys, time, unicodedata, urllib.error, urllib.request, urllib.parse
from difflib import SequenceMatcher

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="backslashreplace")  # e.g. Japanese card names on a Windows cp1252 console
    except (AttributeError, ValueError):
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "cache")
os.makedirs(CACHE, exist_ok=True)

# PriceCharting console-name -> where the cards live.
#   ptcg: Pokemon TCG API set ids (first one is the "main" set used for the missing-card view)
#   dex:  TCGdex set ids (fallback), lang: TCGdex language
#   complete: whether a "show missing cards" view makes sense
SET_MAP = {
    "Pokemon Base Set": {"ptcg": ["base1"], "dex": ["base1"]},
    "Pokemon Jungle": {"ptcg": ["base2"], "dex": ["base2"]},
    "Pokemon Fossil": {"ptcg": ["base3"], "dex": ["base3"]},
    "Pokemon Neo Destiny": {"ptcg": ["neo4"], "dex": ["neo4"]},
    "Pokemon Hidden Fates": {"ptcg": ["sm115", "sma"], "dex": ["sm115", "sma"]},
    "Pokemon Chilling Reign": {"ptcg": ["swsh6"], "dex": ["swsh6"]},
    "Pokemon Evolving Skies": {"ptcg": ["swsh7"], "dex": ["swsh7"]},
    "Pokemon Celebrations": {"ptcg": ["cel25", "cel25c"], "dex": ["cel25", "cel25cc"], "extra_ptcg": ["swshp"]},
    "Pokemon Fusion Strike": {"ptcg": ["swsh8"], "dex": ["swsh8"]},
    "Pokemon Brilliant Stars": {"ptcg": ["swsh9", "swsh9tg"], "dex": ["swsh9", "swsh9tg"]},
    "Pokemon Astral Radiance": {"ptcg": ["swsh10", "swsh10tg"], "dex": ["swsh10", "swsh10tg"]},
    "Pokemon Silver Tempest": {"ptcg": ["swsh12", "swsh12tg"], "dex": ["swsh12", "swsh12tg"]},
    "Pokemon Crown Zenith": {"ptcg": ["swsh12pt5", "swsh12pt5gg"], "dex": ["swsh12.5", "swsh12.5gg"]},
    "Pokemon Scarlet & Violet": {"ptcg": ["sv1"], "dex": ["sv01"]},
    "Pokemon Obsidian Flames": {"ptcg": ["sv3"], "dex": ["sv03"]},
    "Pokemon Scarlet & Violet 151": {"ptcg": ["sv3pt5"], "dex": ["sv03.5"]},
    "Pokemon Paldean Fates": {"ptcg": ["sv4pt5"], "dex": ["sv04.5"]},
    "Pokemon Stellar Crown": {"ptcg": ["sv7"], "dex": ["sv07"]},
    "Pokemon Surging Sparks": {"ptcg": ["sv8"], "dex": ["sv08"]},
    "Pokemon Journey Together": {"ptcg": ["sv9"], "dex": ["sv09"]},
    "Pokemon Destined Rivals": {"ptcg": ["sv10"], "dex": ["sv10"]},
    "Pokemon White Flare": {"ptcg": ["rsv10pt5"], "dex": ["sv10.5w"]},
    "Pokemon Black Bolt": {"ptcg": ["zsv10pt5"], "dex": ["sv10.5b"]},
    "Pokemon Mega Evolution": {"ptcg": ["me1"], "dex": ["me01"]},
    "Pokemon Phantasmal Flames": {"ptcg": ["me2"], "dex": ["me02"]},
    "Pokemon Perfect Order": {"ptcg": ["me3"], "dex": ["me03"]},
    "Pokemon Chaos Rising": {"ptcg": ["me4"], "dex": ["me04"]},
    "Pokemon Pitch Black": {"ptcg": ["me5"], "dex": ["me05"]},
    # PriceCharting files the 30th Classic Collection reprints under 30th Celebration with their
    # original printed numbers, so those match by name in TCGdex "30th-c" and borrow the original print's image.
    "Pokemon 30th Celebration": {"ptcg": ["me55"], "dex": ["30th"], "classic_dex": ["30th-c"]},
    # Promos span many promo sets; name + number must both match.
    "Pokemon Promo": {"ptcg": ["svp", "swshp", "smp", "xyp", "bwp", "hsp", "dpp", "np", "basep"],
                      "dex": ["mep", "svp", "swshp", "smp", "xyp", "bwp", "hgssp", "dpp", "np", "basep", "wp", "miscp"],
                      "complete": False, "strict_name": True},
    # Non-English prints: images come from TCGdex in that language (names differ, so number-only match).
    "Pokemon Japanese Paradise Dragona": {"dex": ["SV7a"], "lang": "ja", "complete": False, "number_only": True},
    "Pokemon Japanese Cyber Judge": {"dex": ["SV5M"], "lang": "ja", "complete": False, "number_only": True},
    # No Chinese data source; uses the English 30th Celebration print image as a stand-in.
    "Pokemon Chinese 30th Celebration": {"ptcg": ["me55"], "dex": ["30th"], "complete": False, "stand_in": True},
}

# ---- automatic set mapping: any PriceCharting console name not in SET_MAP ----
# English console names are matched by normalized name against TCGdex's and the Pokemon TCG API's set lists.
# Japanese names: TCGdex lists Japanese sets under Japanese names, so this table maps PriceCharting's
# English translation to the TCGdex Japanese set id. Add to it (or to SET_MAP) for anything missing.
JA_SETS = {
    "Expansion Pack": "PMCG1", "Jungle": "PMCG2", "Mystery of the Fossils": "PMCG3", "Rocket Gang": "PMCG4",
    "Leaders' Stadium": "PMCG5", "Challenge from the Darkness": "PMCG6", "Gold, Silver, New World": "neo1",
    "Crossing the Ruins": "neo2", "Awakening Legends": "neo3", "Darkness, and to Light": "neo4", "VS": "VS1",
    "Web": "web1", "Expedition Expansion Pack": "E1", "The Town on No Map": "E2", "Wind from the Sea": "E3",
    "Split Earth": "E4", "Mysterious Mountains": "E5", "Clash of the Blue Sky": "PCG2",
    "Rocket Gang Strikes Back": "PCG3", "Golden Sky, Silvery Ocean": "PCG4", "Holon Research": "PCG6",
    "Holon Phantom": "PCG7", "Offense and Defense of the Furthest Ends": "PCG9", "Bandit Ring": "XY7",
    "PokeKyun Collection": "CP3", "Awakening Psychic King": "XY10", "Alolan Moonlight": "SM2L",
    "Shining Legends": "SM3+", "GX Battle Boost": "SM4+", "Tag Bolt": "SM9", "GX Ultra Shiny": "SM8b",
    "Double Blaze": "SM10", "Miracle Twins": "SM11", "Remix Bout": "SM11a", "Dream League": "SM11b",
    "Alter Genesis": "SM12", "Tag All Stars": "SM12a", "Amazing Volt Tackle": "S4", "Shiny Star V": "S4a",
    "Eevee Heroes": "S6a", "Blue Sky Stream": "S7R", "Fusion Arts": "S8", "25th Anniversary Collection": "S8a",
    "VMAX Climax": "S8b", "Star Birth": "S9", "Battle Region": "S9a", "Dark Phantasma": "S10a", "Go": "S10b",
    "Lost Abyss": "S11", "Incandescent Arcana": "S11a", "Paradigm Trigger": "S12", "VSTAR Universe": "S12a",
    "Scarlet Ex": "SV1S", "Violet Ex": "SV1V", "Snow Hazard": "SV2P", "Clay Burst": "SV2D",
    "Scarlet & Violet 151": "SV2a", "Ruler of the Black Flame": "SV3", "Raging Surf": "SV3a",
    "Ancient Roar": "SV4K", "Future Flash": "SV4M", "Shiny Treasure ex": "SV4a", "Wild Force": "SV5K",
    "Cyber Judge": "SV5M", "Crimson Haze": "SV5a", "Mask of Change": "SV6", "Night Wanderer": "SV6a",
    "Stellar Miracle": "SV7", "Paradise Dragona": "SV7a", "Super Electric Breaker": "SV8",
    "Terastal Festival": "SV8a", "Battle Partners": "SV9", "Heat Wave Arena": "SV9a",
    "Glory of Team Rocket": "SV10", "Black Bolt": "SV11B", "White Flare": "SV11W", "Mega Brave": "M1L",
    "Mega Symphonia": "M1S", "Inferno X": "M2", "Mega Dream ex": "M2a", "Nihil Zero": "M3",
    "Ninja Spinner": "M4", "Abyss Eye": "M5", "Storm Emeralda": "M6", "Start Deck 100 Battle Collection": "MC",
    "Triplet Beat": "SV1a", "20th Anniversary": "CP6",
}
# PriceCharting names that differ from the card databases' names (normalized key -> normalized key).
SET_ALIASES = {
    "scarletviolet151": "151", "expedition": "expeditionbaseset",
}
# Multi-set PriceCharting groups (normalized key -> TCGdex ids).
SET_GROUPS = {
    "exlatiaslatios": ["tk-ex-latia", "tk-ex-latio"],
    "pikachulibresuicune": ["tk-xy-p", "tk-xy-su"],
}
# Subsets printed inside a main set; their cards are listed under the main set on PriceCharting.
SUBSET_SUFFIXES = ("Trainer Gallery", "Galarian Gallery", "Shiny Vault", "Classic Collection", "Unown Collection")
LANG_PREFIX = {"Japanese": "ja", "Chinese": "zh", "Korean": "ko", "French": "fr", "German": "de",
               "Italian": "it", "Spanish": "es", "Portuguese": "pt"}

def set_key(name):
    """Comparison key for a set name: lowercase ASCII letters/digits only, no 'pokemon', '&'/'and'/'vs' dropped."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\bpok[ae]mon\b", " ", s).replace("&", " ")
    s = re.sub(r"\b(and|vs|the)\b", " ", s)
    return re.sub(r"[^a-z0-9]", "", s)

_catalogs = {}
def set_catalogs():
    """TCGdex English set list and the Pokemon TCG API set list (cached; the API list is optional)."""
    if not _catalogs:
        _catalogs["dex"] = get_json("https://api.tcgdex.net/v2/en/sets", "tcgdex_sets_en.json", max_age=7 * 86400) or []
        d = get_json("https://api.pokemontcg.io/v2/sets?pageSize=250&select=id,name", "ptcg_sets.json", max_age=30 * 86400, tries=2)
        _catalogs["ptcg"] = (d or {}).get("data", [])
    return _catalogs["dex"], _catalogs["ptcg"]

def resolve_set(console):
    """Mapping (same shape as SET_MAP values) for a PriceCharting console name, or None."""
    name = re.sub(r"^Pokemon\s+", "", console).strip()
    first = name.split(" ", 1)[0]
    if first in LANG_PREFIX:
        rest = name.split(" ", 1)[1] if " " in name else ""
        jid = {set_key(k): v for k, v in JA_SETS.items()}.get(set_key(rest)) if first == "Japanese" else None
        return {"dex": [jid], "lang": "ja", "complete": False, "number_only": True, "auto": True} if jid else None
    dex_sets, ptcg_sets = set_catalogs()
    key = set_key(name)
    key = SET_ALIASES.get(key, key)
    dex_by = {}
    for s in dex_sets:
        dex_by.setdefault(set_key(s["name"]), s)
    mc = re.fullmatch(r"mcdonalds(?:collection)?(\d{4})", key)
    if mc:
        key = "mcdonaldscollection" + mc.group(1)
    if key in SET_GROUPS:
        ids = SET_GROUPS[key]
    elif key in dex_by:
        main = dex_by[key]
        ids = [main["id"]] + [s["id"] for s in dex_sets
                              if any(s["name"] == f"{main['name']} {suf}" for suf in SUBSET_SUFFIXES)]
    else:
        ids = []
    dex_name = {s["id"]: s["name"] for s in dex_sets}
    ptcg_by = {}
    for s in ptcg_sets:
        ptcg_by.setdefault(set_key(s["name"]), s["id"])
    ptcg = [ptcg_by[set_key(dex_name[i])] for i in ids if set_key(dex_name.get(i, "")) in ptcg_by]
    if not ids:
        if key in ptcg_by:  # only in the Pokemon TCG API
            return {"ptcg": [ptcg_by[key]], "auto": True}
        return None
    cfg = {"dex": ids, "auto": True}
    if ptcg:
        cfg["ptcg"] = list(dict.fromkeys(ptcg))
    if "promo" in key:
        cfg.update(complete=False, strict_name=True)
    return cfg

# National Dex regions (4x4 Pokedex tabs). Hisui (899-905) has no dex range of its own and is shown in Galar.
REGIONS = [
    {"key": "kanto", "name": "Kanto", "start": 1, "end": 151},
    {"key": "johto", "name": "Johto", "start": 152, "end": 251},
    {"key": "hoenn", "name": "Hoenn", "start": 252, "end": 386},
    {"key": "sinnoh", "name": "Sinnoh", "start": 387, "end": 493},
    {"key": "unova", "name": "Unova", "start": 494, "end": 649},
    {"key": "kalos", "name": "Kalos", "start": 650, "end": 721},
    {"key": "alola", "name": "Alola", "start": 722, "end": 809, "note": "Includes Meltan #808 and Melmetal #809"},
    {"key": "galar", "name": "Galar", "start": 810, "end": 905, "note": "Includes Hisui #899-905 (Wyrdeer to Enamorus)",
     "sub": {"name": "Hisui", "start": 899, "end": 905}},
    {"key": "paldea", "name": "Paldea", "start": 906, "end": 1025},
]
DEX_MAX = 1025
ART = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/{}.png"
# PokeAPI slugs that don't title-case into the printed English name.
NAME_FIX = {
    "nidoran-f": "Nidoran♀", "nidoran-m": "Nidoran♂", "mr-mime": "Mr. Mime", "mime-jr": "Mime Jr.",
    "mr-rime": "Mr. Rime", "type-null": "Type: Null", "farfetchd": "Farfetch'd", "sirfetchd": "Sirfetch'd",
    "flabebe": "Flabébé", "jangmo-o": "Jangmo-o", "hakamo-o": "Hakamo-o", "kommo-o": "Kommo-o",
}
# Hyphens that are part of the printed name (everything else becomes a space: tapu-koko -> Tapu Koko).
KEEP_HYPHEN = {"ho-oh", "porygon-z", "chien-pao", "wo-chien", "ting-lu", "chi-yu"}

def species_list():
    """[(dex, English name)] for National Dex 1..DEX_MAX, from PokeAPI (cached in data/cache)."""
    data = get_json(f"https://pokeapi.co/api/v2/pokemon-species?limit={DEX_MAX}", f"pokeapi_species_{DEX_MAX}.json")
    out = []
    for r in data["results"]:
        dex = int(r["url"].rstrip("/").rsplit("/", 1)[1])
        slug = r["name"]
        if slug in NAME_FIX:
            name = NAME_FIX[slug]
        elif slug in KEEP_HYPHEN:
            name = "-".join(w.capitalize() for w in slug.split("-"))
        else:
            name = " ".join(w.capitalize() for w in slug.split("-"))
        out.append((dex, name))
    out.sort()
    assert [d for d, _ in out] == list(range(1, DEX_MAX + 1)), "PokeAPI species list is not 1..1025"
    return out

def species_key(name):
    """Token tuple used to find a species in a card title."""
    return tuple(norm_name(name.replace("♀", " female ").replace("♂", " male ")).split())

def build_species_matcher(species):
    # Longest names first (by token count, then length) so 'Mr. Mime' wins over 'Mime Jr.' fragments,
    # 'Porygon-Z' over 'Porygon', 'Iron Valiant' over nothing shorter, etc.
    keys = sorted(((species_key(n), dex) for dex, n in species), key=lambda kd: (-len(kd[0]), -len(" ".join(kd[0]))))
    def match(card_name):
        """National Dex numbers a card depicts, from its English name.
        Prefixes/suffixes are ignored ('Team Rocket's Weezing', 'Alolan Exeggutor ex', 'Mega Charizard X EX',
        'Radiant Greninja', 'Dialga LV.X'); tag teams ('Moltres & Zapdos & Articuno GX') count for each species."""
        toks = norm_name(card_name.replace("♀", " female ").replace("♂", " male ")).split()
        used = [False] * len(toks)
        found = []
        for key, dex in keys:
            L = len(key)
            for i in range(len(toks) - L + 1):
                if not any(used[i:i + L]) and tuple(toks[i:i + L]) == key:
                    for j in range(i, i + L):
                        used[j] = True
                    if dex not in found:
                        found.append(dex)
        return sorted(found)
    return match

UA = {"User-Agent": "virtual-binder/1.0 (personal collection viewer)"}

_down = {}  # host -> failed requests this build

def get_json(url, cache_name, max_age=None, tries=5):
    """GET a JSON URL, cached in data/cache/<cache_name>. max_age (seconds) refetches older cache files."""
    cache_name = re.sub(r'[<>:"/\\|?*\s]', "_", cache_name)  # characters Windows (or any OS) can't use in a file name
    path = os.path.join(CACHE, cache_name)
    if os.path.exists(path) and (max_age is None or time.time() - os.path.getmtime(path) < max_age):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    host = urllib.parse.urlsplit(url).netloc
    if _down.get(host, 0) >= 3:  # 3 requests to this API have failed this build; use the other source instead of waiting
        return None
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.load(r)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
            return data
        except Exception as e:  # rate limits / timeouts on the keyless API
            last = e
            time.sleep(2 + attempt * 3)
    print(f"  ! failed {url}: {last}", file=sys.stderr)
    if isinstance(last, urllib.error.URLError) and "CERTIFICATE_VERIFY_FAILED" in str(last):
        print("  ! Python can't verify HTTPS certificates. See 'Troubleshooting' in README.md.", file=sys.stderr)
    _down[host] = _down.get(host, 0) + 1
    if _down[host] == 3:
        print(f"  ! {host} keeps failing; skipping it for the rest of this build (cards fall back to the other source)", file=sys.stderr)
    return None

# ---- PriceCharting product photos: fallback for rows the card databases have no image for ----
PC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
PC_IMG = re.compile(r"https://storage\.googleapis\.com/images\.pricecharting\.com/[A-Za-z0-9_-]+/(\d+)\.(?:jpg|png|webp)")
_pc_last = [0.0]

def _pc_wait():
    # Be polite: at most one PriceCharting request every 1.5 s, and only for rows that need it (results are cached).
    gap = time.time() - _pc_last[0]
    if gap < 1.5:
        time.sleep(1.5 - gap)
    _pc_last[0] = time.time()

def _pc_get(url, method="GET"):
    """(status, final_url, body). urllib first; curl with the same headers if urllib is refused."""
    _pc_wait()
    try:
        req = urllib.request.Request(url, headers=PC_HEADERS, method=method)
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.geturl(), (r.read().decode("utf-8", "replace") if method == "GET" else "")
    except urllib.error.HTTPError as e:
        if e.code not in (403, 429):
            return e.code, url, ""
    except Exception:
        pass
    _pc_wait()
    args = ["curl", "-sL", "--max-time", "30", "-o", "-", "-w", "\n%{http_code} %{url_effective}"]
    for k, v in PC_HEADERS.items():
        args += ["-H", f"{k}: {v}"]
    if method == "HEAD":
        args.append("-I")
    out = subprocess.run(args + [url], capture_output=True, text=True).stdout
    body, _, tail = out.rpartition("\n")
    code, _, final = tail.partition(" ")
    return int(code or 0), final or url, body

def pc_photo(pc_id):
    """{'img': 1600px or 240px URL, 'thumb': 240px URL, 'page': product page} or {'img': None} when
    PriceCharting has no real photo. Cached in data/cache/pc_<id>.json."""
    if not str(pc_id).isdigit():  # example / hand-made rows have no PriceCharting product to look up
        return {"img": None}
    path = os.path.join(CACHE, f"pc_{pc_id}.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    status, final, html = _pc_get(f"https://www.pricecharting.com/game/{pc_id}")
    res = {"img": None, "thumb": None, "page": final, "status": status}
    if status == 200:
        # The main photo is the first image inside <div class="cover">; anything else there is a placeholder.
        m = re.search(r'<div class="cover">(.*?)</div>', html, re.S)
        cover = PC_IMG.search(m.group(1)) if m else None
        if cover:
            base = cover.group(0).rsplit("/", 1)[0]
            res["thumb"] = base + "/240.jpg"
            big = base + "/1600.jpg"
            res["img"] = big if (big in html or _pc_get(big, "HEAD")[0] == 200) else res["thumb"]
        print(f"  PC photo {pc_id}: {'yes' if res['img'] else 'none'} ({final})", file=sys.stderr)
    else:
        print(f"  ! PriceCharting {pc_id}: HTTP {status}", file=sys.stderr)
        return res  # don't cache failures, so the next build retries
    with open(path, "w", encoding="utf-8") as f:
        json.dump(res, f)
    return res

def ptcg_set(set_id):
    """All cards in a Pokemon TCG API set, in set order."""
    cards, page = [], 1
    while True:
        q = urllib.parse.urlencode({"q": f"set.id:{set_id}", "pageSize": 250, "page": page,
                                    "select": "id,name,number,images,rarity,set"})
        d = get_json(f"https://api.pokemontcg.io/v2/cards?{q}", f"ptcg_{set_id}_{page}.json")
        if not d:
            return None
        cards += d.get("data", [])
        if len(cards) >= d.get("totalCount", 0) or not d.get("data"):
            break
        page += 1
    out = []
    for c in cards:
        out.append({"id": c["id"], "name": c["name"], "number": c["number"],
                    "img": c["images"].get("large") or c["images"].get("small"),
                    "thumb": c["images"].get("small"), "rarity": c.get("rarity"),
                    "set": set_id, "source": "Pokemon TCG API",
                    "setName": c["set"]["name"], "release": c["set"].get("releaseDate", "")})
    out.sort(key=lambda c: num_key(c["number"]))
    return out

def ptcg_search(name, number):
    """Find a card anywhere in the Pokemon TCG API by exact name + printed number."""
    q = urllib.parse.urlencode({"q": f'name:"{name}" number:{number}', "pageSize": 10,
                                "select": "id,name,number,images,set", "orderBy": "set.releaseDate"})
    d = get_json(f"https://api.pokemontcg.io/v2/cards?{q}", f"ptcg_search_{norm_name(name).replace(' ', '_')}_{number}.json")
    for c in (d or {}).get("data", []):
        if norm_name(c["name"]) == norm_name(name):
            return {"id": c["id"], "img": c["images"].get("large"), "thumb": c["images"].get("small")}
    return None

def dex_set(set_id, lang="en"):
    d = get_json(f"https://api.tcgdex.net/v2/{lang}/sets/{urllib.parse.quote(set_id)}", f"dex_{lang}_{set_id}.json")
    if not d:
        return None
    out = []
    for c in d.get("cards", []):
        img = c.get("image")
        out.append({"id": c["id"], "name": c["name"], "number": c["localId"],
                    "img": f"{img}/high.webp" if img else None, "thumb": f"{img}/low.webp" if img else None,
                    "rarity": None, "set": set_id, "source": "TCGdex",
                    "setName": d.get("name"), "release": (d.get("releaseDate") or "").replace("-", "/")})
    out.sort(key=lambda c: num_key(c["number"]))
    return out

def dex_card(card_id, lang="en", max_age=None):
    """One TCGdex card with full details (types, category, pricing). Cached in data/cache/dexcard_<lang>_<id>.json."""
    return get_json(f"https://api.tcgdex.net/v2/{lang}/cards/{urllib.parse.quote(card_id)}",
                    f"dexcard_{lang}_{card_id.replace('/', '_')}.json", max_age)

def dex_twin(e, pool):
    """TCGdex card id for a matched row: the match itself, or the TCGdex card in the same set slot."""
    m = e.get("match")
    if not m:
        return None
    if m["source"] == "TCGdex":
        return m["id"]
    for c in pool.get("dex") or []:
        if slot_key(c["number"], c["name"]) == e.get("slot"):
            return c["id"]
    return None

PRICE_TTL = 3 * 86400  # TCGdex prices refresh daily; refetch a card's price after 3 days
TCGP_VARIANTS = ["normal", "holofoil", "reverse-holofoil", "1st-edition-holofoil", "1st-edition-normal", "unlimited-holofoil", "unlimited"]

def pick_price(pricing):
    """Market price from TCGdex 'pricing': TCGplayer market price in USD (normal print first), else the
    Cardmarket trend in EUR. None when TCGdex has no price. Never estimated."""
    tp = (pricing or {}).get("tcgplayer") or {}
    variants = [v for v in TCGP_VARIANTS if v in tp] + [v for v in tp if v not in TCGP_VARIANTS and isinstance(tp[v], dict)]
    for v in variants:
        mp = (tp.get(v) or {}).get("marketPrice")
        if isinstance(mp, (int, float)) and mp > 0:
            return {"c": round(mp * 100), "cur": "USD", "src": "TCGplayer market", "var": v,
                    "pid": tp[v].get("productId"), "upd": (tp.get("updated") or "")[:10]}
    cm = (pricing or {}).get("cardmarket") or {}
    for k in ("trend", "avg"):
        if isinstance(cm.get(k), (int, float)) and cm[k] > 0:
            return {"c": round(cm[k] * 100), "cur": "EUR", "src": "Cardmarket " + k, "upd": (cm.get("updated") or "")[:10]}
    return None

def tcgdex_catalog():
    """Every English TCGdex set, newest first: [{id, name, total, official, serie}]."""
    sets = get_json("https://api.tcgdex.net/v2/en/sets", "tcgdex_sets_en.json", max_age=7 * 86400) or []
    serie_of = {}
    for sr in get_json("https://api.tcgdex.net/v2/en/series", "tcgdex_series_en.json", max_age=7 * 86400) or []:
        d = get_json(f"https://api.tcgdex.net/v2/en/series/{urllib.parse.quote(sr['id'])}", f"tcgdex_serie_en_{sr['id']}.json", max_age=7 * 86400)
        for st in (d or {}).get("sets", []):
            serie_of[st["id"]] = sr["name"]
    out = [{"id": x["id"], "name": x["name"], "total": (x.get("cardCount") or {}).get("total"),
            "official": (x.get("cardCount") or {}).get("official"), "serie": serie_of.get(x["id"], "")} for x in sets]
    return out[::-1]

def completion_set(set_id):
    """Card list + market prices for one TCGdex set (Set Completion tab)."""
    d = get_json(f"https://api.tcgdex.net/v2/en/sets/{urllib.parse.quote(set_id)}", f"dex_en_{set_id}.json")
    if not d:
        return None
    cards = d.get("cards", [])
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        full = list(pool.map(lambda c: dex_card(c["id"], max_age=PRICE_TTL), cards))
    out = []
    for c, f in zip(cards, full):
        out.append({"id": c["id"], "n": c["localId"], "name": c["name"], "img": c.get("image"),
                    "rarity": (f or {}).get("rarity"), "price": pick_price((f or {}).get("pricing"))})
    return {"id": set_id, "name": d.get("name"), "release": d.get("releaseDate"),
            "official": (d.get("cardCount") or {}).get("official"), "fetched": time.strftime("%Y-%m-%d"), "cards": out}

def num_key(n):
    m = re.match(r"^([A-Za-z]*)(\d+)(.*)$", str(n))
    if not m:
        return ("~", 10**6, str(n))
    return (m.group(1).upper(), int(m.group(2)), m.group(3))

def norm_num(n):
    n = str(n).strip().upper()
    n = re.sub(r"_A$", "", n)                     # Celebrations Classic Collection "8_A"
    m = re.match(r"^([A-Z]*?)0*(\d+)([A-Z]*)$", n)
    return f"{m.group(1)}{int(m.group(2))}{m.group(3)}" if m else n

def norm_name(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = s.lower().replace("&", "and").replace("'", "").replace("\u2019", "")
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return s

def parse_product(product):
    """'Wartortle [Reverse Holo] #8' -> ('Wartortle', 'Reverse Holo', '8')"""
    m = re.match(r"^(.*?)\s*(?:\[(.+?)\])?\s*#(\S+)\s*$", product)
    if not m:
        return product.strip(), None, None
    return m.group(1).strip(), m.group(2), m.group(3)

def slot_key(number, name):
    """Identity of a card within one set, shared by both APIs (ids differ between them)."""
    return f"{norm_num(number)}|{norm_name(name)}"

def name_score(a, b):
    a, b = norm_name(a), norm_name(b)
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()

def parse_args():
    ap = argparse.ArgumentParser(description="Build binder-data.js from a PriceCharting collection export.")
    ap.add_argument("csv", nargs="?", default=os.path.join(ROOT, "data", "collection.csv"),
                    help="PriceCharting export CSV (default: data/collection.csv)")
    ap.add_argument("--no-history", action="store_true",
                    help="don't save a value snapshot to data/history/ for this build")
    ap.add_argument("--snapshot-date", metavar="YYYY-MM-DD",
                    help="date to file this build's value snapshot under (default: today)")
    ap.add_argument("--sets", metavar="IDS",
                    help="precompute Set Completion data (card lists + TCGdex market prices) for these TCGdex set ids, "
                         "comma-separated, or 'owned' for every English set you own, or 'none' to stop. Remembered "
                         "for later builds. Sets not precomputed are fetched by the page on demand.")
    ap.add_argument("--no-types", action="store_true",
                    help="skip the per-card TCGdex lookups that add Pokemon types (used by My Binders filters)")
    return ap.parse_args()

def read_json_file(path, label):
    """Optional hand-made JSON file next to the CSV; None if missing or invalid."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, OSError) as err:
        print(f"  ! ignoring {label}: {err}", file=sys.stderr)
        return None

HISTORY = os.path.join(ROOT, "data", "history")

def save_snapshot(csv_path, entries, date, generated):
    """Write data/history/<csv name>/<date>.json (one per day; a same-day rebuild replaces it) and
    return every snapshot summary for this CSV name, oldest first, plus the previous snapshot's rows."""
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.splitext(os.path.basename(csv_path))[0]) or "collection"
    folder = os.path.join(HISTORY, stem)
    os.makedirs(folder, exist_ok=True)
    items = {}
    for e in entries:
        items[e["key"]] = {"u": e["unitCents"], "v": e["valueCents"], "q": e["qty"], "pc": e["pcId"],
                           "g": e["grade"], "n": e["product"], "s": e["console"]}
    snap = {"version": 1, "date": date, "generated": generated, "source": os.path.basename(csv_path),
            "totalCents": sum(e["valueCents"] for e in entries), "cards": sum(e["qty"] for e in entries),
            "rows": len(entries), "items": items}
    with open(os.path.join(folder, f"{date}.json"), "w", encoding="utf-8") as f:
        json.dump(snap, f, separators=(",", ":"))
    snaps = []
    for name in sorted(os.listdir(folder)):
        if re.match(r"^\d{4}-\d{2}-\d{2}\.json$", name):
            try:
                with open(os.path.join(folder, name), encoding="utf-8") as f:
                    snaps.append(json.load(f))
            except (ValueError, OSError) as err:
                print(f"  ! skipping history file {name}: {err}", file=sys.stderr)
    snaps.sort(key=lambda x: x["date"])
    pos = next(i for i, x in enumerate(snaps) if x["date"] == date)
    prev = snaps[pos - 1] if pos > 0 else None
    print(f"history: snapshot {date} saved in data/history/{stem}/ ({len(snaps)} snapshot(s))", file=sys.stderr)
    return {"folder": stem, "current": date,
            "series": [{k: x.get(k) for k in ("date", "totalCents", "cards", "rows")} for x in snaps],
            "prev": {"date": prev["date"], "items": prev["items"]} if prev else None}

def main():
    args = parse_args()
    csv_path = args.csv
    if not os.path.exists(csv_path):
        sys.exit(f"CSV not found: {csv_path}\n"
                 "Export your collection from PriceCharting and save it as data/collection.csv, or pass a path:\n"
                 "    python3 scripts/build.py path/to/export.csv\n"
                 "To try the example data:  python3 scripts/build.py data/sample-collection.csv")
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    print(f"{len(rows)} rows in {csv_path}")

    pools = {}  # console -> {"cards": [...], "main": [...]}
    unmapped, auto = [], []
    for console in sorted({r["console-name"] for r in rows}):
        cfg = SET_MAP.get(console) or resolve_set(console)
        if not cfg:
            unmapped.append(console)
            pools[console] = {"cards": [], "main": None, "cfg": {}}
            continue
        if cfg.get("auto"):
            auto.append(f"{console} -> {', '.join(cfg.get('dex') or cfg.get('ptcg'))}")
        cards, main_list = [], []
        for sid in cfg.get("ptcg", []):
            lst = ptcg_set(sid) or []
            cards += lst
            if cfg.get("complete", True):
                main_list += lst
        dex_cards = []
        for sid in cfg.get("dex", []):
            dex_cards += dex_set(sid, cfg.get("lang", "en")) or []
        if cfg.get("complete", True) and not main_list:
            main_list = [c for c in dex_cards]
        extra = []
        for sid in cfg.get("extra_ptcg", []):
            extra += ptcg_set(sid) or []
        pools[console] = {"cards": cards, "dex": dex_cards, "extra": extra,
                          "main": main_list if cfg.get("complete", True) else None, "cfg": cfg}
        print(f"  {console}: {len(cards)} ptcg + {len(dex_cards)} tcgdex cards")

    def best(cands, base, num, cfg):
        target = norm_num(num)
        hits = [c for c in cands if norm_num(c["number"]) == target]
        if cfg.get("number_only"):
            return (hits[0], 0.7, "number only (non-English names)") if hits else (None, 0, "")
        scored = sorted(((name_score(base, c["name"]), c) for c in hits), key=lambda t: -t[0])
        if scored:
            s, c = scored[0]
            if s >= 0.999:
                return c, 1.0, "set + number + name"
            if s >= 0.75:
                return c, round(s, 2), "set + number + fuzzy name"
            if not cfg.get("strict_name") and s >= 0.5:
                return c, round(s * 0.8, 2), "set + number, weak name"
        return None, 0, ""

    entries, unmatched = [], []
    seen_keys = {}
    for r in rows:
        console = r["console-name"]
        base, variant, num = parse_product(r["product-name"])
        pool = pools.get(console, {})
        cfg = pool.get("cfg", {})
        match, conf, method = (None, 0, "")
        if num:
            match, conf, method = best(pool.get("cards", []), base, num, cfg)
            if not match:
                match, conf, method = best(pool.get("dex", []), base, num, cfg)
                if match:
                    method += " (TCGdex fallback)"
            if not match and pool.get("extra"):
                match, conf, method = best(pool["extra"], base, num, {**cfg, "strict_name": True})
                if match:
                    method += " (promo printed in this set)"
        if not match and num and cfg.get("classic_dex"):
            for sid in cfg["classic_dex"]:
                for c in dex_set(sid) or []:
                    if name_score(base, c["name"]) >= 0.75 or norm_name(c["name"]) in norm_name(base):
                        orig = ptcg_search(base, num)
                        match = dict(c)
                        if orig:
                            match["img"], match["thumb"] = orig["img"], orig["thumb"]
                            method = f"name in {sid}; image from original print {orig['id']}"
                        else:
                            method = f"name in {sid}; no image available"
                        conf = 0.75 if orig else 0.6
                        break
                if match:
                    break
        if match and cfg.get("stand_in"):
            conf = min(conf, 0.6)
            method += "; English print image used as a stand-in"
        if match and cfg.get("strict_name") and len([c for c in pool.get("cards", []) + pool.get("dex", [])
                                                     if norm_num(c["number"]) == norm_num(num)
                                                     and name_score(base, c["name"]) >= 0.75
                                                     and c["set"] != match["set"] and c["source"] == match["source"]]) > 0:
            conf = min(conf, 0.7)
            method += "; same name+number in another promo set"
        price = int(r["price-in-pennies"] or 0)
        qty = int(r["quantity"] or 1)
        cost = int(r["cost-basis-in-pennies"] or 0)
        grader = (r.get("grading-company") or "").strip()
        cond = (r.get("condition-string") or "").strip()
        grade = f"{grader} {cond}".strip() if grader else "Raw"
        e = {
            "pcId": r["id"], "product": r["product-name"], "console": console,
            "name": base, "variant": variant, "number": num,
            "grade": grade, "graded": bool(grader), "condition": cond,
            "notes": (r.get("notes") or "").strip(), "folder": (r.get("folder") or "").strip(),
            # PriceCharting's price is the row total (it already covers every copy in the row);
            # cost basis follows the same convention. Per-card price = row price / quantity.
            "qty": qty, "valueCents": price, "unitCents": round(price / qty) if qty else price, "costCents": cost,
            "dateEntered": r.get("date-entered", ""),
            "match": None,
        }
        if match:
            e["match"] = {"id": match["id"], "set": match["set"], "setName": match["setName"],
                          "number": match["number"], "apiName": match["name"], "img": match["img"],
                          "thumb": match["thumb"], "rarity": match.get("rarity"), "source": match["source"],
                          "confidence": conf, "method": method}
            e["slot"] = slot_key(match["number"], match["name"])
        else:
            e["slot"] = None
            unmatched.append(e)
        # Stable row key for saved picks: PriceCharting id + row details, plus an occurrence
        # counter for rows that are otherwise identical. Survives re-exports and re-sorting.
        base_key = "|".join([r["id"], grade, cond, r.get("date-entered", ""), e["folder"]])
        seen_keys[base_key] = seen_keys.get(base_key, 0) + 1
        e["key"] = f"{base_key}|{seen_keys[base_key]}"
        entries.append(e)

    sets = []
    for console, pool in pools.items():
        owned = [e for e in entries if e["console"] == console]
        main_list = pool.get("main")
        order = {}
        if main_list:
            for i, c in enumerate(main_list):
                order.setdefault(c["id"], i)
        all_lists = (pool.get("cards") or []) + (pool.get("dex") or [])
        release = next((c["release"] for c in all_lists if c.get("release")), "")
        full = None
        if main_list:
            full = [{"id": c["id"], "name": c["name"], "number": c["number"], "thumb": c["thumb"],
                     "slot": slot_key(c["number"], c["name"])} for c in main_list]
        sets.append({
            "key": console, "name": re.sub(r"^Pokemon ", "", console), "release": release,
            "completeList": full,
            "ownedCount": sum(e["qty"] for e in owned),
        })
    # Real sets first in release order, then promo / non-English groups at the back of the binder.
    sets.sort(key=lambda s: (s["completeList"] is None, s["release"] or "9999", s["name"]))

    # Image sources per row, in order of preference: card database image, then PriceCharting's photo.
    # (The site falls back to official artwork / a labeled sleeve when none load.)
    for e in entries:
        imgs = []
        if e["match"] and e["match"].get("img"):
            imgs.append({"img": e["match"]["img"], "thumb": e["match"].get("thumb") or e["match"]["img"], "source": "db"})
        else:
            pc = pc_photo(e["pcId"])
            if pc.get("img"):
                imgs.append({"img": pc["img"], "thumb": pc.get("thumb") or pc["img"], "source": "pc", "page": pc.get("page")})
        e["images"] = imgs
    no_img = [e for e in entries if not e["images"]]
    print(f"images: {sum(1 for e in entries if e['images'] and e['images'][0]['source'] == 'pc')} PriceCharting photos, "
          f"{len(no_img)} rows with no image", file=sys.stderr)
    for e in no_img:
        print(f"  NO IMAGE: {e['product']} | {e['console']}", file=sys.stderr)

    # Pokedex views: every owned card per National Dex species, most valuable per card first.
    species = species_list()
    match_species = build_species_matcher(species)
    dex = [{"dex": d, "name": n, "art": ART.format(d), "cards": []} for d, n in species]
    no_species = []
    for idx, e in enumerate(entries):
        found = match_species(e["name"])
        e["species"] = found
        if "nidoran" in norm_name(e["name"]) and not found:
            print(f"  ? Nidoran without sex marker: {e['product']}", file=sys.stderr)
        if not found:
            no_species.append(e)
        for d in found:
            dex[d - 1]["cards"].append(idx)
    for k in dex:
        k["cards"].sort(key=lambda i: (-entries[i]["unitCents"], entries[i]["match"] is None))
    multi = [e for e in entries if len(e["species"]) > 1]
    print(f"species: {len(entries) - len(no_species)} rows mapped, {len(no_species)} with no species, "
          f"{sum(1 for k in dex if k['cards'])}/{DEX_MAX} species owned", file=sys.stderr)
    for e in multi:
        print(f"  MULTI: {e['product']} -> {[dex[d - 1]['name'] for d in e['species']]}", file=sys.stderr)
    for e in no_species:
        print(f"  NO SPECIES: {e['product']} | {e['console']}", file=sys.stderr)

    # Optional data/picks.json (from the site's "Export picks" button) becomes the default face cards.
    default_picks = {}
    picks_path = os.path.join(ROOT, "data", "picks.json")
    if os.path.exists(picks_path):
        try:
            with open(picks_path, encoding="utf-8") as f:
                raw = json.load(f)
            raw = raw.get("picks", raw) if isinstance(raw, dict) else {}
            default_picks = {str(k): v for k, v in raw.items() if isinstance(v, str)}
            print(f"picks.json: {len(default_picks)} default Kanto picks", file=sys.stderr)
        except (ValueError, OSError) as err:
            print(f"  ! ignoring data/picks.json: {err}", file=sys.stderr)

    # Types / card category from TCGdex (one cached request per distinct English card; types never change).
    # Used by the My Binders tray filter and the "type" quick-fill rule.
    for e in entries:
        pool = pools.get(e["console"], {})
        e["dexId"] = dex_twin(e, pool) if pool.get("cfg", {}).get("lang", "en") == "en" else None
    if not args.no_types:
        typed = 0
        for e in entries:
            cid = e["dexId"]
            d = dex_card(cid) if cid else None
            e["types"] = (d or {}).get("types") or []
            e["category"] = (d or {}).get("category")
            typed += bool(e["types"])
        print(f"types: {typed}/{len(entries)} rows have a Pokemon type from TCGdex", file=sys.stderr)

    # Optional data/binders.json (from My Binders "Export binders") becomes the default custom binders.
    raw_binders = read_json_file(os.path.join(ROOT, "data", "binders.json"), "data/binders.json")
    default_binders = raw_binders.get("binders", []) if isinstance(raw_binders, dict) else (raw_binders if isinstance(raw_binders, list) else [])
    if default_binders:
        print(f"binders.json: {len(default_binders)} default custom binders", file=sys.stderr)

    # Set Completion: every TCGdex set for the picker, which of its cards you own, and optional precomputed sets.
    catalog = tcgdex_catalog()
    owned_dex = {}
    for i, e in enumerate(entries):
        if e.get("dexId"):
            sid = e["dexId"].rsplit("-", 1)[0]
            owned_dex.setdefault(sid, {}).setdefault(e["dexId"], []).append(i)
    remember = os.path.join(CACHE, "completion_sets.json")
    if args.sets is not None:
        want = [] if args.sets.strip().lower() == "none" else [x.strip() for x in args.sets.split(",") if x.strip()]
        with open(remember, "w", encoding="utf-8") as f:
            json.dump(want, f)
    else:
        want = (read_json_file(remember, "completion_sets.json") or []) if os.path.exists(remember) else []
    if "owned" in want:
        want = [x for x in want if x != "owned"] + sorted(owned_dex)
    known = {x["id"] for x in catalog}
    completion = {}
    for sid in dict.fromkeys(want):
        if catalog and sid not in known:
            print(f"  ? --sets: '{sid}' is not a TCGdex set id (see https://api.tcgdex.net/v2/en/sets)", file=sys.stderr)
            continue
        cs = completion_set(sid)
        if cs:
            completion[sid] = cs
            priced = sum(1 for c in cs["cards"] if c["price"])
            print(f"  completion {sid}: {len(cs['cards'])} cards, {priced} with a market price", file=sys.stderr)
    print(f"set completion: {len(catalog)} TCGdex sets in the picker, {len(completion)} precomputed", file=sys.stderr)

    total_val = sum(e["valueCents"] for e in entries)
    generated = time.strftime("%Y-%m-%d %H:%M %Z")
    history = None
    if not args.no_history:
        date = args.snapshot_date or time.strftime("%Y-%m-%d")
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
            sys.exit(f"--snapshot-date must look like 2026-01-31, not {date!r}")
        history = save_snapshot(csv_path, entries, date, generated)
    out = {
        "generated": generated,
        "source": os.path.basename(csv_path),
        "totals": {"rows": len(rows), "cards": sum(e["qty"] for e in entries), "valueCents": total_val,
                   "matched": len(rows) - len(unmatched), "unmatched": len(unmatched)},
        "sets": sets, "entries": entries, "dex": dex, "regions": REGIONS,
        "defaultPicks": default_picks, "defaultBinders": default_binders,
        "hasTypes": any(e.get("types") for e in entries),
        "history": history,
        "dexSets": catalog, "ownedDex": owned_dex, "completion": completion,
    }
    with open(os.path.join(ROOT, "data", "cards.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    with open(os.path.join(ROOT, "binder-data.js"), "w", encoding="utf-8") as f:
        f.write("// Generated by scripts/build.py. Do not edit by hand.\nwindow.BINDER_DATA = ")
        json.dump(out, f, separators=(",", ":"))
        f.write(";\n")
    print(f"cards={out['totals']['cards']} rows={len(rows)} value=${total_val/100:,.2f} "
          f"matched={out['totals']['matched']} unmatched={len(unmatched)}")
    for e in unmatched:
        print(f"  UNMATCHED: {e['product']} | {e['console']}")
    low = [e for e in entries if e["match"] and e["match"]["confidence"] < 0.9]
    for e in low:
        m = e["match"]
        print(f"  LOW {m['confidence']}: {e['product']} | {e['console']} -> {m['id']} '{m['apiName']}' ({m['method']})")
    if auto:
        print(f"Set mapping: {len(auto)} set(s) matched automatically:")
        for a in auto:
            print(f"  {a}")
    if unmapped:
        n = sum(1 for e in entries if e["console"] in unmapped)
        print(f"Set mapping: {len(unmapped)} PriceCharting set(s) aren't in TCGdex or the Pokemon TCG API, so their "
              f"{n} row(s) use PriceCharting's product photo where it has one:")
        for c in unmapped:
            print(f"  {c}")
        print("  To map one yourself, add it to SET_MAP at the top of scripts/build.py (see README, 'Sets that don't match').")

if __name__ == "__main__":
    main()
