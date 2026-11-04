# Virtual Binder

Virtual Binder turns a [PriceCharting](https://www.pricecharting.com/) collection export into a Pokémon card binder you can browse in your browser. It's a small static site: no server, no account, no API keys. You run one Python script and open `index.html`.

## Features

- **Set binder:** your cards in 3×3 binder pages, grouped by set in release order. Each pocket shows the card image, variant, grade, quantity and PriceCharting price. You can filter by set, sort by set order or value, and search. A **Show missing cards** toggle fills in the cards from a set you don't own as faded placeholders.
- **Region Pokédex tabs:** one 4×4 binder per region, from Kanto to Paldea (National Dex #1–1025), in dex order.
  - Each species shows your most valuable card of that Pokémon from any set.
  - Species you don't have appear as grayed-out official artwork.
  - Each region shows "X / N collected", a progress bar and a value total. An "All regions" summary adds them up.
- **Swap the card in a slot:** click a Pokédex slot to see every card you own of that species, then choose **Use this card**. You can also cycle with the ‹ › arrows. Your choices are pinned, saved in the browser, and can be exported or imported as `picks.json`.
- **My Binders:** make your own binders, like "Eeveelutions", "Charizards" or "Fire types". See [My Binders](#my-binders).
- **Value over time:** every build saves a snapshot of your collection's value, so the Value tab can chart it and list your biggest gainers and losers since the last export. PriceCharting doesn't keep that history for you. See [Value over time](#value-over-time).
- **Set Completion:** pick any of TCGdex's English sets to see which cards you own, which you're missing (cheapest first, with TCGplayer market prices) and what it would cost to finish the set. See [Set Completion](#set-completion).
- **Image fallbacks:** card images come from TCGdex or the Pokémon TCG API. If neither has an image, the PriceCharting product photo is used and tagged **PC photo**. If that's missing too, the binder shows official artwork or a labeled sleeve. Images that fail to load fall back to the next source automatically.
- **Prices from your export only:** nothing is re-priced. A PriceCharting row's price is the row total, so the per-card price is price ÷ quantity.

## Requirements

- Python 3.8 or newer. The build uses only the standard library, so there's nothing to `pip install`.
- A modern browser. Chrome, Edge or Firefox are recommended; see [Saved picks](#saved-picks) for Safari.
- An internet connection for the first build, which fetches set lists and images. After that, results are cached.

## Quick start

```bash
git clone https://github.com/dlang14/virtual-binder.git
cd virtual-binder

# Try it with the made-up example data:
python3 scripts/build.py data/sample-collection.csv
open index.html          # macOS. On Windows: start index.html. On Linux: xdg-open index.html
```

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

### What the build does

`scripts/build.py` reads the CSV and matches each row to a card in the Pokémon TCG API, with TCGdex as the fallback, using the set name, card number and card name. It writes two files:

- `data/cards.json`: the full matched data
- `binder-data.js`: the same data as a JavaScript global, so the page works when opened straight from a file (`file://`)

API responses are cached in `data/cache/`. Delete that folder to refresh after a new set comes out.

Supported sets are listed in `SET_MAP` at the top of `build.py`. To add a set, add its PriceCharting set name (the `console-name` column) with its Pokémon TCG API and TCGdex set ids. Rows that can't be matched are listed under **Not matched** at the bottom of the page, and their prices still count toward the total.

### How cards map to Pokédex species

Species are found from the card name. The 1,025 species names come from [PokeAPI](https://pokeapi.co/) at build time.

- **Longest names first:** "Mr. Mime" isn't read as "Mime Jr.", "Porygon-Z" isn't read as "Porygon", and "Iron Valiant", "Tapu Koko" and "Chien-Pao" stay whole.
- **Extra words are ignored:** prefixes and suffixes don't change the species. For example, "Team Rocket's Weezing", "Alolan Exeggutor ex", "Mega Charizard X EX", "Radiant Greninja" and "Dialga LV.X" all count as the base species.
- **Tag teams count for each Pokémon:** "Moltres & Zapdos & Articuno GX" fills three slots.
- **Hisui:** the Hisuian Pokémon (#899–905) are shown in the Galar tab with a "Hisui" tag. Meltan and Melmetal are shown in Alola.

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

Each build saves a snapshot to `data/history/<csv name>/<date>.json`, for example `data/history/collection/2026-11-03.json`. A snapshot holds the date, total value, card and row counts, and each row's PriceCharting price, keyed by the same stable row key as picks and binders.

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

Prices are only ever PriceCharting's prices from your exports; nothing is estimated between snapshots.

## Set Completion

The Set Completion tab has a search box covering every English set on [TCGdex](https://tcgdex.dev), with the sets you own listed first. For the set you pick, it shows:

- how many of its cards you own, and the value of those cards
- every missing card, cheapest first, with its TCGplayer market price (or the Cardmarket price in EUR when TCGplayer has none)
- the cost to complete, which is the sum of the USD prices of the missing cards
- links to each card on TCGplayer and PriceCharting

Tick **Show the cards I own** to see the whole set. The tab remembers the last set you opened.

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

PriceCharting's data is licensed for personal use, so **don't publish your generated files or your CSV**. The included `.gitignore` already excludes them, along with every `*.csv` except the sample. To share your binder, share screenshots instead.

## Project layout

```
index.html          the page
app.js              rendering: set binder, Pokédex tabs, picks, image fallbacks, tab switching
binders.js          My Binders tab
value.js            Value tab (value over time)
completion.js       Set Completion tab
styles.css          binder look
scripts/build.py    CSV -> binder-data.js (Python standard library only)
data/sample-collection.csv   made-up example rows to try the site
```

## Data sources and credits

- [TCGdex](https://tcgdex.dev/): card data and images
- [Pokémon TCG API](https://pokemontcg.io/): card data and images
- [PokeAPI](https://pokeapi.co/): species names and official artwork, via the [PokeAPI sprites](https://github.com/PokeAPI/sprites) repo
- [PriceCharting](https://www.pricecharting.com/): your collection export, prices, and product photos for cards the card databases don't have an image of. Photos are fetched politely, at most one request every 1.5 seconds, and cached.

## Disclaimer

This is an unofficial fan project. It isn't affiliated with, endorsed by, or sponsored by Nintendo, The Pokémon Company, Game Freak, Creatures, or PriceCharting. Pokémon and all related names and images are trademarks of their respective owners. Card images and data belong to their respective owners and are loaded from the sources above. They aren't redistributed in this repo.

## License

[MIT](LICENSE)
