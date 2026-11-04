# Virtual Binder

Virtual Binder turns a [PriceCharting](https://www.pricecharting.com/) collection export into a Pokémon card binder you can browse in your browser. It's a small static site: no server, no account, no API keys. You run one Python script and open `index.html`.

## Features

- **Set binder:** your cards in 3×3 binder pages, grouped by set in release order. Each pocket shows the card image, variant, grade, quantity and PriceCharting price. You can filter by set, sort by set order or value, and search. A **Show missing cards** toggle fills in the cards from a set you don't own as faded placeholders.
- **Region Pokédex tabs:** one 4×4 binder per region, from Kanto to Paldea (National Dex #1–1025), in dex order.
  - Each species shows your most valuable card of that Pokémon from any set.
  - Species you don't have appear as grayed-out official artwork.
  - Each region shows "X / N collected", a progress bar and a value total. An "All regions" summary adds them up.
- **Swap the card in a slot:** click a Pokédex slot to see every card you own of that species, then choose **Use this card**. You can also cycle with the ‹ › arrows. Your choices are pinned, saved in the browser, and can be exported or imported as `picks.json`.
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
   The build prints a summary: card count, total value, matched and unmatched rows, rows with no species, and rows with no image.
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

## Direct links

`index.html#pokedex` opens Kanto. `#pokedex-johto`, `#pokedex-hoenn` and so on through `#pokedex-paldea` open the other regions.

## Keep your data private

The files the build generates contain your collection and PriceCharting's prices:

- `binder-data.js`
- `data/cards.json`
- `data/picks.json`
- `data/cache/pc_*.json`

PriceCharting's data is licensed for personal use, so **don't publish your generated files or your CSV**. The included `.gitignore` already excludes them, along with every `*.csv` except the sample. To share your binder, share screenshots instead.

## Project layout

```
index.html          the page
app.js              rendering: set binder, Pokédex tabs, picks, image fallbacks
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
