# Virtual Binder

Virtual Binder turns a [PriceCharting](https://www.pricecharting.com/) collection export into a Pokémon card binder you can browse in your browser. It's a small static site: no server, no account. You run one Python script and open `index.html`. Prices at each card's own condition need a free [JustTCG](https://justtcg.com) API key (see [Pricing](#pricing)); without one the site still works and shows the PriceCharting prices from your export.

## Features

- **Set binder:** your cards in 3×3 binder pages, grouped by set in release order. Each pocket shows the card image, variant, condition, quantity and price. You can filter by set, sort by set order or value, and search. A **Show missing cards** toggle fills in the cards from a set you don't own as faded placeholders.
- **Region Pokédex tabs:** one 4×4 binder per region, from Kanto to Paldea (National Dex #1–1025), in dex order.
  - Each species shows your most valuable card of that Pokémon from any set.
  - Species you don't have appear as grayed-out official artwork.
  - Each region shows "X / N collected", a progress bar and a value total. An "All regions" summary adds them up.
- **Swap the card in a slot:** click a Pokédex slot to see every card you own of that species, then choose **Use this card**. You can also cycle with the ‹ › arrows. Your choices are pinned, saved in the browser, and can be exported or imported as `picks.json`.
- **My Binders:** make your own binders, like "Eeveelutions", "Charizards" or "Fire types". See [My Binders](#my-binders).
- **Value over time:** every build saves a snapshot of your collection's value, so the Value tab can chart it and list your biggest gainers and losers since the last export. PriceCharting doesn't keep that history for you. See [Value over time](#value-over-time).
- **Set Completion:** pick any of TCGdex's English sets to see every card in it in set-number order, which ones you own (with your PriceCharting value) and which you're missing, and what it would cost to finish the set. See [Set Completion](#set-completion).
- **Add cards:** search TCGdex by name (with optional set and number), pick a printing, condition and quantity, and save the card to your collection file; it is priced and your pages update on their own. You can also edit a card's condition and quantity, or remove it, from its zoom panel. See [Add, edit and remove cards](#add-edit-and-remove-cards).
- **Image fallbacks:** card images come from TCGdex or the Pokémon TCG API. If neither has an image, the PriceCharting product photo is used and tagged **PC photo**. If that's missing too, the binder shows official artwork or a labeled sleeve. Images that fail to load fall back to the next source automatically.
- **Prices at each card's own condition:** English cards are priced from TCGplayer market prices (via JustTCG) at the condition in your notes column (no note = Near Mint) and the right printing. A card with no exact price shows a labelled PriceCharting price or "no price", never another condition's. See [Pricing](#pricing).

## Requirements

- Python 3.8 or newer, on macOS, Windows or Linux. The build uses only the standard library, so there's nothing to `pip install`. On Windows, see [Windows](#windows).
- A modern browser. Chrome, Edge or Firefox are recommended; see [Saved picks](#saved-picks) for Safari.
- An internet connection for the first build, which fetches set lists and images. After that, results are cached.
- Optional but recommended: a free [JustTCG](https://justtcg.com) API key for per-condition prices (and a free [PkmnPrices](https://pkmnprices.com) key for a few promos). See [Pricing](#pricing).

## Quick start

```bash
git clone https://github.com/dlang14/virtual-binder.git
cd virtual-binder

# Try it with the made-up example data:
python3 scripts/build.py data/sample-collection.csv
open index.html          # macOS. On Linux: xdg-open index.html
```

On Windows, use the PowerShell commands in [Windows](#windows).

## Use your own collection

1. **Export your collection from PriceCharting.** Sign in, add your cards to your collection, then go to <https://www.pricecharting.com/export-collection> and download the CSV. Free accounts can export once a week.
2. **Put the CSV at `data/collection.csv`.** You can also keep it anywhere and pass its path to the build.
3. **Build:**
   ```bash
   python3 scripts/build.py                        # reads data/collection.csv
   python3 scripts/build.py ~/Downloads/export.csv # or any path
   ```
   The build also saves a value snapshot for the Value tab. It prints a summary: card count, total value, matched and unmatched rows, rows with no species, and rows with no image.
4. **Open `index.html`** in your browser. Reload it after every rebuild.

To add the cards from a new export, replace the CSV and run the build again.

### Windows

Install Python from <https://www.python.org/downloads/> (tick **Add python.exe to PATH**) or from the Microsoft Store. On Windows, the command is usually `py` instead of `python3`; `python` also works if it's on your PATH. Every `python3 scripts/build.py …` command in this README works the same way with `py scripts\build.py …`.

If you don't use git, download the repository with **Code → Download ZIP** on GitHub and extract it.

In PowerShell:

```powershell
cd $HOME\Downloads\virtual-binder
py scripts\build.py data\sample-collection.csv    # try the example data
py scripts\build.py                                # your export, saved as data\collection.csv
py scripts\build.py $HOME\Downloads\export.csv      # or any path
Start-Process index.html                          # open the site in your default browser
```

You can also double-click `index.html` in File Explorer. Chrome, Edge and Firefox all work from a local file. After a rebuild, reload the page; press **Ctrl+Shift+R** to make sure the browser loads the new files. To force a fresh download of everything the build caches, delete the cache folder with `Remove-Item -Recurse -Force data\cache`.

### What the build does

`scripts/build.py` reads the CSV and matches each row to a card in the Pokémon TCG API, with TCGdex as the fallback, using the set name, card number and card name. It writes two files:

- `data/cards.json`: the full matched data
- `binder-data.js`: the same data as a JavaScript global, so the page works when opened straight from a file (`file://`)

API responses are cached in `data/cache/`. Delete that folder to refresh after a new set comes out.

Prices come from the pricing step described under [Pricing](#pricing).

Supported sets are listed in `SET_MAP` at the top of `build.py`. To add a set, add its PriceCharting set name (the `console-name` column) with its Pokémon TCG API and TCGdex set ids. Rows that can't be matched are listed under **Not matched** at the bottom of the page, and their prices still count toward the total.

### How cards map to Pokédex species

Species are found from the card name. The 1,025 species names come from [PokeAPI](https://pokeapi.co/) at build time.

- **Longest names first:** "Mr. Mime" isn't read as "Mime Jr.", "Porygon-Z" isn't read as "Porygon", and "Iron Valiant", "Tapu Koko" and "Chien-Pao" stay whole.
- **Extra words are ignored:** prefixes and suffixes don't change the species. For example, "Team Rocket's Weezing", "Alolan Exeggutor ex", "Mega Charizard X EX", "Radiant Greninja" and "Dialga LV.X" all count as the base species.
- **Tag teams count for each Pokémon:** "Moltres & Zapdos & Articuno GX" fills three slots.
- **Hisui:** the Hisuian Pokémon (#899–905) are shown in the Galar tab with a "Hisui" tag. Meltan and Melmetal are shown in Alola.

### Sets that don't match

The build matches each PriceCharting set name ("console name" in the CSV) to the card databases automatically. It drops the "Pokemon " prefix and compares names while ignoring case, punctuation, accents and "&"/"and"/"vs", so "Pokemon Fire Red & Leaf Green" finds "FireRed & LeafGreen". A matched set also includes the subsets PriceCharting lists under it: Trainer Gallery, Galarian Gallery, Shiny Vault and Classic Collection cards. Japanese sets are looked up in the `JA_SETS` table in `scripts/build.py`, because TCGdex lists them only under their Japanese names.

At the end of the build, a summary lists the sets that were matched automatically and any that weren't. Rows from an unmatched set still build: they keep their PriceCharting price and use PriceCharting's product photo when it has one. Chinese, Korean, Topps and other sets that neither database covers stay unmatched.

To map a set yourself, add a line to `SET_MAP` at the top of `scripts/build.py`. Use the console name exactly as it appears in your CSV, with TCGdex set ids (from `https://api.tcgdex.net/v2/en/sets`) and, optionally, Pokemon TCG API set ids:

```python
"Pokemon Delta Reign": {"dex": ["<tcgdex set id>"]},
"Pokemon Japanese Eevee Heroes": {"dex": ["S6a"], "lang": "ja", "complete": False, "number_only": True},
```

Entries in `SET_MAP` always win over the automatic match.

## Add, edit and remove cards

The page itself is static, but saving needs a small local server (Python standard library only):

```
python3 scripts/serve.py            # then open http://127.0.0.1:8123
```

It listens on this computer only, serves just the site's own `.html`, `.js` and `.css` files (never your CSV or cache), and edits `data/collection.csv` (or `--csv path`).

- **Add cards** tab: search by name, optionally narrowed by set and number (the set filter is applied by TCGdex). Each result shows the image, set, number and rarity. Choose a printing, a condition (NM, LP, MP, HP, DMG), a quantity and optional notes, then **Add**.
- **Edit or remove:** click a card in the Set binder. The zoom panel has a row per owned stack with the condition, quantity, **Save** and **Remove**.
- **Starting from nothing:** a fresh clone needs no `data/collection.csv` and no built page. `serve.py` builds an empty page on first start, and your first add creates `data/collection.csv` (and `data/`). If you already have a CSV, the first start builds the page from it (a normal full build).
- **Printing:** the menu offers the printings TCGdex lists for that card that pricing can tell apart: Normal, Holo, Reverse Holo, and their 1st Edition versions. The choice is written as the `[Reverse Holo]`-style tag in the product name, which is where the pricing step already reads a card's printing, so it is priced from the matching JustTCG printing (a Reverse Holo is never priced as the Normal card). Normal has no tag, as in a PriceCharting export, unless the card also has a Holo. Not offered, because the price sources can't identify them: stamped promos, jumbo cards, and shadowless or similar older-print variants. When TCGdex lists several 1st Edition products, the first is used.
- **What gets written:** a new row in the PriceCharting export format (id `tcgdex:<card id>:<printing>`, `Name [Tag] #Number`, the set's name, quantity, today's date). The condition goes in the notes column the way pricing reads it: `LP`, or `LP - corner whitening` with your own text after it. A note that names a different wear level is refused, because the price would be ambiguous. Changing a quantity scales the row's PriceCharting price and cost basis so per-card amounts stay the same.
- **Price on add:** every add, edit and remove rebuilds `binder-data.js` in the background (`build.py --price-new-only`), so the page needs no manual build. A new card costs one JustTCG request (cards already in the 24 hour price cache cost none, and a card whose price is older than that is not refetched by an add; only a normal `build.py` refreshes those). Each add-triggered build is capped at 3 JustTCG requests, so the free tier (100 a day, 1,000 a month) is never burned by adding cards. Changes that arrive during a build fold into one more build. The banner on the Add cards tab follows it and then offers **Reload to see it**; the data is a static script, so the open page can't swap it in by itself. A separate "Rebuild now" button isn't needed.
- **Price pending:** if JustTCG can't answer (daily or monthly limit, rate limit, outage), the card is saved and shows a **price pending** chip instead of "no price". Nothing is cached for it, so the next add, edit, remove or `python3 scripts/build.py` asks again and the chip goes away once a price comes back. A rejected API key is not "pending"; it shows as no price with the reason. New cards have no PriceCharting price, so there is nothing to fall back on while a price is pending.
- **Set names:** a card from a set the collection already has uses that spelling. Where PriceCharting spells a set differently from TCGdex (for example "Scarlet & Violet 151" versus TCGdex's "151"), `scripts/manage/set_aliases.json` maps the TCGdex set name to the one your collection uses, so new cards join the existing set group instead of forming a new one. It's seeded with 151, Pokémon GO and the promo sets (which `build.py` groups as "Promo"); add a line when you see a duplicate set. Case, accents and punctuation don't matter, and the right-hand name must be one `build.py` can resolve (its `SET_MAP`, or the TCGdex set's own name). A set that isn't listed is written as `Pokemon <TCGdex set name>`.
- Every change first copies the old file to `data/collection.prev.csv`, one step of undo.

## Themes

Pick a look from the **Theme** menu at the top right of every tab. Your choice is saved in the browser (in Safari on a local file it lasts until you close the page). Themes only change colors and fonts; card images are never recolored, and missing Pokédex cards stay grayed out in every theme.

- **Original**: the default dark-blue binder.
- **Auto**: follows your system's light or dark setting (Classic binder or Dark mode).
- **Classic binder**: brown leather cover with cream pages.
- **Dark mode**: near-black and neutral gray.
- **Holo foil shimmer**: a slow rainbow sheen over your cards. It stays still if your system has reduced motion turned on.
- **Night Sky / Galaxy**: starfield with purple and blue nebula.
- **Trainer Card poster**: bright white, blue and yellow.
- **High contrast**: black, white and yellow for maximum legibility.

## Saved picks

- **Automatic:** picks are saved in the browser's `localStorage`, keyed by National Dex number and a stable row key. The row key is built from the PriceCharting id plus the row's details, so picks survive reloads, rebuilds and new exports.
  - If you no longer own the picked card, the slot quietly goes back to your most valuable copy.
  - Chrome, Edge and Firefox keep `localStorage` for local `file://` pages.
  - Safari usually blocks storage for local files. The page shows a note when that happens, and picks only last until you close the page.
- **Export / Import picks:** use the buttons in any region header. Export downloads `picks.json`, covering every region, and Import loads one back. Use this to move picks between browsers.
- **Permanent:** save an exported file as `data/picks.json` and rebuild. Those picks become the defaults in every browser. A choice made in a browser still takes priority.

## My Binders

The **My Binders** tab is for binders you lay out yourself.

- **Create, rename and delete** binders from the bar at the top. Start empty, or start from a preset: Eeveelutions, Charizards, Pikachus, Kanto starters, or Fire types.
- **Page layout:** choose 3×3 or 4×4 per binder. Switching keeps the cards in order and re-flows them onto the new page size. **Add page** adds an empty page; each page has a **delete page** link. **Close gaps** moves cards up to fill empty pockets.
- **Card tray:** the panel on the right lists every card you own (one per CSV row). Filter it by name, set and Pokémon type, sort it, and hide the cards that are already in the binder. Switch the tray to **Unowned species** to place grayed-out artwork for Pokémon you don't have yet.
- **Placing cards:**
  - Drag a card from the tray into a pocket. Dropping on a filled pocket replaces it.
  - Drag a pocket onto another pocket to move it there; if that pocket is filled, the two swap.
  - Drag a pocket out of the pages (for example back onto the tray) to remove it, or use its **×** button.
  - No drag and drop (touch screens, some trackpads)? Click a card, then click a pocket. Click a filled pocket, then another pocket, to move it.
  - Double-click a card in a binder to zoom in.
- **Quick fill** adds every matching card to the empty pockets, adding pages as needed, and skips cards already in the binder:
  - **Species in a list:** for example `Eevee, Vaporeon, Jolteon, Flareon, Espeon, Umbreon, Leafeon, Glaceon, Sylveon`. Names or National Dex numbers work. Options: one card per species (your most valuable), and grayed placeholders for species you don't own.
  - **Name contains:** for example `Charizard`.
  - **Pokémon type:** for example Fire. Types come from TCGdex (see below). If no card has a type, the option is hidden.
- **Empty pockets** are fine and stay where you leave them. A pocket whose card is no longer in your export says so instead of disappearing.
- **Saving:** binders save in the browser's `localStorage`, using the same stable row keys as Pokédex picks, so they survive rebuilds and new exports. If a row's details change in a new export, the pocket falls back to the same PriceCharting product.
- **Export / Import:** **Export binders** downloads `binders.json`; **Import** loads one back and adds its binders (a binder with the same id is replaced). Save an exported file as `data/binders.json` and rebuild to make those binders the default in every browser. A browser that already has its own binders keeps them.

### Pokémon types

The build looks up each owned English card on TCGdex once (about one request per card, cached in `data/cache/dexcard_*.json`) to get its Pokémon type and whether it's a Trainer or Energy card. A first build of a few hundred cards takes about 30 seconds more. Japanese prints and rows that aren't in TCGdex have no type. Run `python3 scripts/build.py --no-types` to skip the lookups.

## Value over time

Each build saves a snapshot to `data/history/<csv name>/<date>.json`, for example `data/history/collection/2026-11-03.json`. A snapshot holds the date, total value, card and row counts, and each row's per-card price and value, keyed by the same stable row key as picks and binders. A snapshot also records whether its prices were TCGplayer per condition or PriceCharting; when that changes between two snapshots, the Value tab says so, because the gainers and losers then mostly reflect the switch.

- **One per day:** rebuilding on the same day replaces that day's snapshot, so the history has one point per day you rebuilt (in practice, one per export).
- **Kept per CSV name:** building the sample (`sample-collection.csv`) never mixes with your own `collection.csv` history.
- **The Value tab** shows:
  - a line chart of total value over time, and one of card count (inline SVG, no libraries or CDNs)
  - the change since the previous snapshot, and since the first one
  - the top 10 gainers and top 10 losers by per-card price since the previous snapshot, in $ and %
  - cards that are new since the previous snapshot and cards that were removed
  - a table of every snapshot
- **Matching rows between snapshots:** rows pair up by row key. A row whose details changed in the new export (for example a different folder) is paired by PriceCharting id and grade, so it doesn't show up as removed and new.
- **Only one snapshot yet?** The tab says so. Rebuild after your next export to see changes.
- **Options:** `--snapshot-date 2026-10-01` files a build under another date (useful for an older export you still have). `--no-history` skips saving a snapshot.

Prices are only ever the ones each build got from its sources (see [Pricing](#pricing)); nothing is estimated between snapshots.

## Set Completion

The Set Completion tab has a search box covering every English set on [TCGdex](https://tcgdex.dev), with the sets you own listed first. For the set you pick, it shows:

- how many of its cards you own, and the value of those cards
- every card in the set, in set-number order. Cards you own have a solid highlighted border and a caption like "You own 3 - $1.77": the number of copies and your PriceCharting value for all of them. Cards you're missing have a dashed border, dimmed art and their TCGplayer market price (or the Cardmarket price in EUR when TCGplayer has none)
- the cost to complete, which is the sum of the USD prices of the missing cards
- links to each card on TCGplayer and PriceCharting

Use the **All / Owned / Missing** buttons to show the whole set, just the cards you own, or just the ones you don't. The tab remembers the last set you opened and your filter choice.

By default, the page fetches set lists and prices from TCGdex's public API when you open a set. This works from `file://`. Results are cached in your browser for 3 days, and **Refresh prices** fetches them again. A large set takes a few seconds to load the first time.

To bake sets into the page so they open instantly and work offline, precompute them at build time:

```sh
python3 scripts/build.py --sets owned          # every set you own at least one card from
python3 scripts/build.py --sets sv03.5,base1   # specific TCGdex set ids
python3 scripts/build.py --sets none           # go back to fetching in the browser
```

The build remembers your choice in `data/cache/completion_sets.json`, so later builds reuse it. Precomputed prices are refreshed when they're more than 3 days old.

Limitations:

- A card counts as owned only when the build matched it to a TCGdex card. Cards matched only through the Pokémon TCG API, and Japanese cards, aren't counted.
- Prices are TCGdex's copies of TCGplayer and Cardmarket prices, not PriceCharting's. Cards with only a EUR price, or no price, are left out of the cost to complete. Very new sets often have no prices yet.
- Precomputing all ~220 sets (about 24,000 cards) would take a long time, so the build only precomputes the sets you ask for.

## Pricing

Each English card is priced at **its own condition and printing**, not with one blended number.

**Condition.** The `notes` column of your PriceCharting export is read for wear: `LP`, `MP`, `HP`, `DMG`, `NM` or the long names (`Lightly Played`, `moderate play`, ...). No note means Near Mint. A note with no wear word (say, "bought at a show") is treated as Near Mint and listed in the build report. A note naming two levels ("LP/MP") gets no TCGplayer price rather than a guess. `SP` (slightly played) counts as LP, which is what TCGplayer calls it.

**Printing.** Rows with no `[tag]` in the product name get the card's base printing (Normal, Holofoil, or Unlimited Holofoil on vintage cards, never 1st Edition). `[Holo]`, `[Reverse Holo]` and `[1st Edition]` pick that printing. Any other tag (`[Jumbo]`, `[Knockout Collection]`, `[Cosmos Holo]`, ...) is a different TCGplayer product that the price sources can't be trusted to tell apart, so those cards get no TCGplayer price unless you pin them (below). If a card's printing is still ambiguous, it gets no price and the report says why.

**Where prices come from.**

1. [TCGdex](https://tcgdex.dev/) supplies each card's TCGplayer product id.
2. [PkmnPrices](https://pkmnprices.com) name search is the rescue for cards TCGdex has no id for (many promos and 30th Celebration cards). It's used once per card, and the id is remembered.
3. [JustTCG](https://justtcg.com) gives the TCGplayer market price at each condition, by product id, in batches of 20 cards per request.

**Request limits.** JustTCG's free plan allows 10 requests a minute, 100 a day and 1,000 a month. A build sends at most 9 a minute (or, once JustTCG reports your plan, its per-minute limit less one), so a long first build just takes a few minutes. A per-minute 429 waits for `Retry-After` (or a minute) and tries again, up to 3 times. A daily or monthly 429 is never retried: the rest of the build is skipped, the message says which limit was hit, and the affected cards show "price pending" until a later build. PkmnPrices (60 a minute) is held to 55 a minute, and its daily credit limit isn't retried either.

**What a price can be.** Each row ends up in one of four states, shown on the card and in the zoom panel:

| State | Meaning |
| --- | --- |
| priced | JustTCG / TCGplayer market price, USD, at the card's condition and printing |
| PC price | no exact TCGplayer price, so PriceCharting's price from your CSV (row total ÷ quantity) is shown with a **PC price** label. It isn't adjusted for condition |
| PC price (non-English) | Japanese, Chinese and other non-English cards aren't priced from TCGplayer; they show PriceCharting's price with the same label |
| no price | no TCGplayer price and no PriceCharting price |

PriceCharting stays only as that labelled last resort: its price is for an ungraded card of unspecified wear, so it can't stand in for a condition-specific price without saying so. The header splits the total ("N rows priced per condition · M on PriceCharting ($X)"), and `data/cards.json` keeps each row's original PriceCharting price (`pcUnitCents`) next to the new one. Nothing is ever converted from another currency, and a missing LP price never becomes the NM price.

**Keys.** Put them in a `.env` file in the project folder (git ignores it) or in environment variables:

```
JUSTTCG_API_KEY=...
PKMNPRICES_API_KEY=...
```

`.env.example` shows the format. Without `JUSTTCG_API_KEY` the build runs normally and every card keeps its labelled PriceCharting price. Keys are only ever sent in a request header, and never printed or saved.

**Limits and caching.**

- JustTCG's free tier allows 100 requests a day and 1,000 a month. A full refresh of about 250 cards is roughly 13 requests. The build stops after `--max-justtcg-requests` (default 30).
- PkmnPrices allows 500 credits a day; each card is searched at most once (`--max-pkmnprices-requests`, default 100).
- Prices are cached for 24 hours in `data/cache/justtcg_prices.json`, so a second build the same day makes no price requests. The resolved TCGplayer id for each card is saved in `data/tcgplayer_ids.json`, so later builds make no id lookups at all.
- `--price-cache-only` prices from the cache and makes no price requests; `--pricecharting-only` skips the price APIs entirely.

**Coverage report.** Every build prints how many rows were priced, how many are missing and why, which were skipped as non-English, any notes that were assumed, and how many API calls it made.

**Pinning a card by hand.** To price a card the build can't (or to fix a wrong id), add it to `data/tcgplayer_ids.json`. The key is `pc:` plus the row's PriceCharting `id` from the CSV:

```json
{"cards": {"pc:1234567": {"id": "654321", "source": "manual", "printing": "Holofoil"}}}
```

`id` is the TCGplayer product id (the number at the end of the card's TCGplayer URL). `printing` is optional and must be one of `Normal`, `Holofoil`, `Reverse Holofoil`, `Unlimited`, `Unlimited Holofoil`, `1st Edition`, `1st Edition Holofoil`; it replaces the `[tag]` rule. Manual entries are never overwritten. Delete a card's entry from `misses` in that file to retry a failed lookup before the 7 days are up.

**For a future search feature.** The pricing code lives in `scripts/pricing/` and knows nothing about the CSV:

- `catalog.py`: `CardCatalog.search(name, set_name, number)` returns candidate cards with TCGplayer ids; `find_tcgplayer_id(CardRef)` resolves one card.
- `service.py`: `PricingService.price_many([PriceItem(card, condition, printing_want)])` returns a `PriceResult` for each (price, source, condition, printing, as-of date, or the reason there's none).
- `domain.py`: `Condition`, `Printing`, `parse_condition`, `parse_variant_tag`, `select_printing` and `PriceResult`.
- `collection.py` is the only part that touches CSV rows, and `scripts/build.py` wires it all together.

A search page would call `search()`, let the person pick a card, a condition and a printing, then call `price_many()` with one item.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The tests use made-up cards and make no network requests.

## Troubleshooting

- **`CERTIFICATE_VERIFY_FAILED`** during a build: Python can't verify HTTPS certificates. On macOS with Python from python.org, run **Install Certificates.command** in your `Applications/Python 3.x` folder. On Windows, Python uses the Windows certificate store, so this usually means the network intercepts HTTPS (some work or school networks do); build from another network.
- **"keeps failing; skipping it for the rest of this build"**: the Pokémon TCG API or TCGdex is down or rate-limiting you. The build carries on with the other source, and failed lookups aren't cached, so the next build tries again.
- **Odd characters in the build output** (such as `\u30df`) on a Windows console: that's a Japanese card name the console can't display. It doesn't affect the site. Run `$env:PYTHONUTF8=1` in PowerShell first to see the real characters.
- **Cards show "PC price" or "no price":** the card's `[tag]`, condition or id couldn't be priced exactly; hover the label or open the card to see why, and see the build's coverage report. A missing key or an exhausted JustTCG quota shows up there too.
- **The page looks out of date:** reload with **Ctrl+Shift+R** (Windows and Linux) or **Cmd+Shift+R** (macOS).

## Direct links

`index.html#pokedex` opens Kanto. `#pokedex-johto`, `#pokedex-hoenn` and so on through `#pokedex-paldea` open the other regions. `#binders` opens My Binders, `#value` opens Value and `#set-completion` opens Set Completion.

## Keep your data private

The files the build generates contain your collection and PriceCharting's prices:

- `binder-data.js`
- `data/cards.json`
- `data/picks.json`
- `data/binders.json`
- `data/history/`
- `data/cache/pc_*.json`
- `data/tcgplayer_ids.json` and `.env` (your API keys)

PriceCharting's data is licensed for personal use, so **don't publish your generated files or your CSV**. The included `.gitignore` already excludes them, along with every `*.csv` except the sample. To share your binder, share screenshots instead.

## Project layout

```
index.html          the page
app.js              rendering: set binder, Pokédex tabs, picks, image fallbacks, tab switching
binders.js          My Binders tab
value.js            Value tab (value over time)
completion.js       Set Completion tab
styles.css          binder look
themes.css          theme colors (Theme menu)
themes.js           Theme menu and saved choice
scripts/build.py    CSV -> binder-data.js (Python standard library only)
scripts/serve.py    local server: the page, the add / edit / remove API, and the rebuild after each change
scripts/manage/     collection CSV store, the search / add / edit / remove service (no HTTP; an API can wrap it later), set_aliases.json, background rebuild
add.js              Add cards tab and the edit / remove panel
scripts/pricing/    per-condition pricing: card catalog, pricing service, JustTCG client (see Pricing)
tests/              unit tests (python3 -m unittest discover -s tests)
data/sample-collection.csv   made-up example rows to try the site
```

## Data sources and credits

- [TCGdex](https://tcgdex.dev/): card data and images
- [Pokémon TCG API](https://pokemontcg.io/): card data and images
- [PokeAPI](https://pokeapi.co/): species names and official artwork, via the [PokeAPI sprites](https://github.com/PokeAPI/sprites) repo
- [JustTCG](https://justtcg.com) and [PkmnPrices](https://pkmnprices.com): per-condition TCGplayer prices and product ids. Free API keys, optional.
- [PriceCharting](https://www.pricecharting.com/): your collection export, prices, and product photos for cards the card databases don't have an image of. Photos are fetched politely, at most one request every 1.5 seconds, and cached.

## Disclaimer

This is an unofficial fan project. It isn't affiliated with, endorsed by, or sponsored by Nintendo, The Pokémon Company, Game Freak, Creatures, or PriceCharting. Pokémon and all related names and images are trademarks of their respective owners. Card images and data belong to their respective owners and are loaded from the sources above. They aren't redistributed in this repo.

## License

[MIT](LICENSE)
