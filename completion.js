// Set Completion: pick any TCGdex set and see what you own, what you're missing, and the missing
// cards from cheapest to priciest. Prices are TCGdex's market prices (TCGplayer, else Cardmarket);
// a card with no price shows "—". Sets precomputed with `build.py --sets` are embedded in
// binder-data.js; any other set is fetched from TCGdex on demand and cached in this browser.
(function () {
  "use strict";
  var VB = window.VB; if (!VB) return;
  var D = VB.D, $ = VB.$, esc = VB.esc, money = VB.money;
  var SETS = D.dexSets || [], OWNED = D.ownedDex || {}, PRE = D.completion || {};
  var SKEY = "virtualBinder.completionSet.v1", CKEY = "virtualBinder.setCache.v1.", TTL = 3 * 86400e3, API = "https://api.tcgdex.net/v2/en/";
  var VARIANTS = ["normal", "holofoil", "reverse-holofoil", "1st-edition-holofoil", "1st-edition-normal", "unlimited-holofoil", "unlimited"];
  var byId = {}; SETS.forEach(function (s) { byId[s.id] = s; });
  var ui = { set: null, showOwned: false, q: "", open: false, loading: null, err: null, data: {} };
  try { ui.set = localStorage.getItem(SKEY); ui.showOwned = localStorage.getItem(SKEY + ".owned") === "1"; } catch (err) {}
  if (!ui.set || !byId[ui.set]) {
    // default: the set you own the most cards from
    var best = null; Object.keys(OWNED).forEach(function (s) { var n = Object.keys(OWNED[s]).length; if (byId[s] && (!best || n > best.n)) best = { s: s, n: n }; });
    ui.set = best ? best.s : (SETS[0] || {}).id;
  }

  // Same rule as pick_price() in build.py.
  function pickPrice(pr) {
    var tp = (pr && pr.tcgplayer) || {}, vs = VARIANTS.filter(function (v) { return tp[v]; }).concat(Object.keys(tp).filter(function (v) { return VARIANTS.indexOf(v) < 0 && tp[v] && typeof tp[v] === "object"; }));
    for (var i = 0; i < vs.length; i++) { var mp = tp[vs[i]].marketPrice; if (typeof mp === "number" && mp > 0) return { c: Math.round(mp * 100), cur: "USD", src: "TCGplayer market", var: vs[i], pid: tp[vs[i]].productId, upd: String(tp.updated || "").slice(0, 10) }; }
    var cm = (pr && pr.cardmarket) || {};
    var ks = ["trend", "avg"];
    for (var j = 0; j < ks.length; j++) if (typeof cm[ks[j]] === "number" && cm[ks[j]] > 0) return { c: Math.round(cm[ks[j]] * 100), cur: "EUR", src: "Cardmarket " + ks[j], upd: String(cm.updated || "").slice(0, 10) };
    return null;
  }
  function cached(id) {
    try { var j = JSON.parse(localStorage.getItem(CKEY + id) || "null"); if (j && Date.now() - j.t < TTL && j.d && j.d.complete) return j.d; } catch (err) {}
    return null;
  }
  function store(id, d) {
    try { localStorage.setItem(CKEY + id, JSON.stringify({ t: Date.now(), d: d })); }
    catch (err) { // full: drop other cached sets and try once more
      try { Object.keys(localStorage).forEach(function (k) { if (k.indexOf(CKEY) === 0 && k !== CKEY + id) localStorage.removeItem(k); }); localStorage.setItem(CKEY + id, JSON.stringify({ t: Date.now(), d: d })); } catch (err2) {}
    }
  }
  function getJSON(url) { return fetch(url).then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); }); }
  // Fetch a set and each card's price from TCGdex (CORS-enabled, so this also works from file://).
  function fetchSet(id, force) {
    if (!force && PRE[id]) return Promise.resolve(PRE[id]);
    if (!force) { var c = cached(id); if (c) return Promise.resolve(c); }
    var tok = {}; ui.loading = { id: id, done: 0, total: 0, tok: tok }; render();
    return getJSON(API + "sets/" + encodeURIComponent(id)).then(function (s) {
      var cards = (s.cards || []).map(function (c) { return { id: c.id, n: c.localId, name: c.name, img: c.image || null, rarity: null, price: null }; });
      var d = { id: id, name: s.name, release: s.releaseDate, official: (s.cardCount || {}).official, fetched: new Date().toLocaleDateString("en-CA"), cards: cards, live: true };
      ui.data[id] = d; ui.loading.total = cards.length; render();
      var next = 0, failed = 0;
      function worker() {
        if (next >= cards.length) return Promise.resolve();
        var c = cards[next++];
        return getJSON(API + "cards/" + encodeURIComponent(c.id)).then(function (f) { c.rarity = f.rarity || null; c.price = pickPrice(f.pricing); }, function () { failed++; })
          .then(function () { ui.loading.done++; if (ui.loading.tok === tok && (ui.loading.done % 20 === 0)) render(); return worker(); });
      }
      var ws = []; for (var i = 0; i < 6; i++) ws.push(worker());
      return Promise.all(ws).then(function () { d.complete = failed === 0; d.failed = failed; if (d.complete) store(id, d); return d; });
    });
  }
  function select(id, force) {
    ui.set = id; ui.err = null; ui.open = false; ui.q = "";
    var inp = $("setSearch"); if (inp) { inp.value = ""; inp.blur(); }
    try { localStorage.setItem(SKEY, id); } catch (err) {}
    render();
    fetchSet(id, force).then(function (d) { ui.data[id] = d; if (ui.loading && ui.loading.id === id) ui.loading = null; if (ui.set === id) render(); },
      function (err) { if (ui.loading && ui.loading.id === id) ui.loading = null; if (ui.set === id) { ui.err = err.message || String(err); render(); } });
  }

  var priceTxt = function (p) { return p ? (p.cur === "USD" ? money(p.c) : "€" + (p.c / 100).toFixed(2)) : "—"; };
  var priceTitle = function (p) { return p ? p.src + (p.var ? " (" + p.var + ")" : "") + " price" + (p.upd ? ", updated " + p.upd : "") + ", via TCGdex" : "TCGdex has no market price for this card"; };
  function links(c, setName) {
    var q = encodeURIComponent(c.name + " " + setName);
    var tcg = c.price && c.price.pid ? "https://www.tcgplayer.com/product/" + encodeURIComponent(c.price.pid) : "https://www.tcgplayer.com/search/pokemon/product?productLineName=pokemon&q=" + q;
    var pc = "https://www.pricecharting.com/search-products?type=prices&q=" + encodeURIComponent(c.name + " " + c.n + " " + setName);
    return '<a href="' + esc(tcg) + '" target="_blank" rel="noopener">TCGplayer</a><a href="' + esc(pc) + '" target="_blank" rel="noopener">PriceCharting</a>';
  }
  function cardHTML(c, d, ownedIdx) {
    var own = ownedIdx && ownedIdx.length, e = own ? D.entries[ownedIdx[0]] : null;
    var img = c.img ? '<img src="' + esc(c.img + "/low.webp") + '" alt="" loading="lazy">' : '<div class="noimg"><b>' + esc(c.name) + "</b>No image</div>";
    return '<div class="ccard' + (own ? " own" : "") + '"><div class="cimg">' + img + "</div>" +
      '<div class="cn" title="' + esc(c.name) + '">' + esc(c.name) + '</div><div class="cs">#' + esc(c.n) + (d.official ? "/" + d.official : "") + (c.rarity ? " · " + esc(c.rarity) : "") + "</div>" +
      (own ? '<div class="cp mine" title="Your PriceCharting price, per card">You own ' + ownedIdx.reduce(function (a, i) { return a + D.entries[i].qty; }, 0) + " · " + money(e.unitCents) + "</div>"
        : '<div class="cp' + (c.price ? "" : " none") + '" title="' + esc(priceTitle(c.price)) + '">' + priceTxt(c.price) + (c.price ? ' <span class="src">' + (c.price.cur === "USD" ? "TCGplayer mkt" : esc(c.price.src) + ", EUR") + "</span>" : "") + "</div>") +
      '<div class="cl">' + links(c, d.name) + "</div></div>";
  }
  function pickerHTML() {
    var q = ui.q.toLowerCase(), list = SETS.filter(function (s) { return !q || (s.name + " " + s.id + " " + s.serie).toLowerCase().indexOf(q) >= 0; });
    var mine = list.filter(function (s) { return OWNED[s.id]; }), rest = list.filter(function (s) { return !OWNED[s.id]; });
    var opt = function (s) { var n = OWNED[s.id] ? Object.keys(OWNED[s.id]).length : 0; return '<button class="opt' + (s.id === ui.set ? " on" : "") + '" data-set="' + esc(s.id) + '"><span>' + esc(s.name) + '</span><small>' + esc(s.serie || "") + (s.total ? " · " + s.total + " cards" : "") + (n ? " · you own " + n : "") + (PRE[s.id] ? " · precomputed" : "") + "</small></button>"; };
    return ui.open ? '<div class="opts" role="listbox">' + (mine.length ? '<div class="og">Sets you own</div>' + mine.map(opt).join("") : "") +
      (rest.length ? '<div class="og">All sets, newest first</div>' + rest.slice(0, 400).map(opt).join("") : "") + (!list.length ? '<div class="og">No set matches.</div>' : "") + "</div>" : "";
  }
  function renderPicker() { var o = $("setOpts"); if (o) o.innerHTML = pickerHTML(); }
  var shell = false;
  function ensureShell() {
    if (shell) return;
    shell = true;
    $("completionView").innerHTML = '<section class="set"><div class="set-head"><h2>Set Completion</h2><span class="meta">Pick any set to see what you\'re missing, cheapest first.</span></div>' +
      '<div class="spick"><input id="setSearch" type="search" placeholder="Search ' + SETS.length + ' sets: name, id or series…" autocomplete="off" aria-label="Find a set"><div id="setOpts"></div></div><div id="cbody"></div></section>';
  }
  function render() {
    var s = byId[ui.set], d = ui.data[ui.set] || PRE[ui.set] || null;
    if (!SETS.length) { $("completionView").innerHTML = '<div class="bempty"><h2>Set Completion</h2><p>The set list from TCGdex wasn\'t available when this was built. Rebuild while online.</p></div>'; return; }
    ensureShell(); renderPicker();
    var html = "";
    if (!s) html += "";
    else if (ui.err && !d) html += '<div class="vnote"><b>Couldn\'t load ' + esc(s.name) + " from TCGdex</b> (" + esc(ui.err) + "). Check your connection and pick the set again, or precompute it with <code>python3 scripts/build.py --sets " + esc(s.id) + "</code> and reload.</div>";
    else if (!d) html += '<div class="vnote">Loading ' + esc(s.name) + " from TCGdex…</div>";
    else {
      var owned = OWNED[d.id] || {}, have = d.cards.filter(function (c) { return owned[c.id]; }), miss = d.cards.filter(function (c) { return !owned[c.id]; });
      var rank = function (c) { return !c.price ? 2 : c.price.cur === "USD" ? 0 : 1; };
      miss.sort(function (a, b) { return rank(a) - rank(b) || (a.price && b.price ? a.price.c - b.price.c : 0) || VB.numKey(a.n)[1] - VB.numKey(b.n)[1]; });
      have.sort(function (a, b) { return VB.numKey(a.n)[1] - VB.numKey(b.n)[1]; });
      var pct = d.cards.length ? Math.round(1000 * have.length / d.cards.length) / 10 : 0;
      var usd = miss.filter(function (c) { return c.price && c.price.cur === "USD"; }), eur = miss.filter(function (c) { return c.price && c.price.cur === "EUR"; });
      var noP = miss.length - usd.length - eur.length;
      var cost = usd.reduce(function (a, c) { return a + c.price.c; }, 0), val = have.reduce(function (a, c) { return a + owned[c.id].reduce(function (x, i) { return x + D.entries[i].valueCents; }, 0); }, 0);
      var loading = ui.loading && ui.loading.id === d.id;
      html += '<div class="chead"><h3>' + esc(d.name) + ' <small>' + esc(s.serie || "") + (d.release ? " · released " + esc(d.release) : "") + " · " + esc(d.id) + "</small></h3>" +
        '<div class="vstats"><div class="stat"><div class="k">Owned</div><div class="v">' + have.length + " / " + d.cards.length + '</div><div class="s">' + pct + "% · " + money(val) + " your value</div></div>" +
        '<div class="stat"><div class="k">Missing</div><div class="v">' + miss.length + '</div><div class="s">' + usd.length + " with a TCGplayer price" + (eur.length ? ", " + eur.length + " Cardmarket only" : "") + (noP ? ", " + noP + " no price" : "") + "</div></div>" +
        '<div class="stat"><div class="k">Cost to complete</div><div class="v">' + (loading ? "…" : money(cost)) + '</div><div class="s">TCGplayer market, ' + usd.length + " card" + (usd.length === 1 ? "" : "s") + (miss.length - usd.length ? "; excludes " + (miss.length - usd.length) + " not priced in USD" : "") + "</div></div></div>" +
        '<div class="progress big"><i style="width:' + pct + '%"></i></div>' +
        '<div class="cbar"><label><input type="checkbox" id="showOwned"' + (ui.showOwned ? " checked" : "") + "> Show the cards I own (" + have.length + ")</label>" +
        '<span class="cmeta">' + (loading ? "Loading prices from TCGdex: " + ui.loading.done + " / " + ui.loading.total + "…" : (PRE[d.id] && !d.live ? "Precomputed by build.py on " : "Fetched from TCGdex on ") + esc(d.fetched) + (d.failed ? " · " + d.failed + " card(s) failed to load, pick the set again to retry" : "")) + "</span>" +
        (loading ? "" : '<button class="btn sm" data-act="refresh" title="Fetch the card list and prices from TCGdex again">Refresh prices</button>') + "</div></div>" +
        '<h3 class="clh">Missing, cheapest first (' + miss.length + ")</h3>" +
        (miss.length ? '<div class="cgrid">' + miss.map(function (c) { return cardHTML(c, d, null); }).join("") + "</div>" : '<div class="vnote"><b>Complete!</b> You own every card in this set.</div>') +
        (ui.showOwned ? '<h3 class="clh">Owned (' + have.length + ")</h3>" + (have.length ? '<div class="cgrid">' + have.map(function (c) { return cardHTML(c, d, owned[c.id]); }).join("") + "</div>" : '<p class="vsub">None yet.</p>') : "") +
        '<p class="vsub">Missing-card prices are TCGdex\'s market prices: the TCGplayer market price in USD (normal print first, otherwise the first variant listed), or the Cardmarket trend in EUR when there\'s no TCGplayer price. Cards with no price show — and sort last. Owned cards show your own PriceCharting price. Owned cards are matched by TCGdex card id, so rows only matched in the Pokémon TCG API, or Japanese prints, aren\'t counted here.</p>';
    }
    $("cbody").innerHTML = html;
  }
  var v = $("completionView");
  v.addEventListener("focusin", function (ev) { if (ev.target.id === "setSearch" && !ui.open) { ui.open = true; renderPicker(); } });
  v.addEventListener("input", function (ev) { if (ev.target.id === "setSearch") { ui.q = ev.target.value; ui.open = true; renderPicker(); } });
  v.addEventListener("keydown", function (ev) {
    if (ev.target.id !== "setSearch") return;
    if (ev.key === "Escape") { ui.open = false; ui.q = ""; ev.target.value = ""; renderPicker(); }
    if (ev.key === "Enter") { var first = v.querySelector(".opts .opt"); if (first) select(first.getAttribute("data-set")); }
  });
  v.addEventListener("click", function (ev) {
    var o = ev.target.closest("[data-set]"); if (o) { select(o.getAttribute("data-set")); return; }
    if (ev.target.closest('[data-act="refresh"]')) { select(ui.set, true); return; }
    if (ui.open && !ev.target.closest(".spick")) { ui.open = false; renderPicker(); }
  });
  v.addEventListener("change", function (ev) {
    if (ev.target.id === "showOwned") { ui.showOwned = ev.target.checked; try { localStorage.setItem(SKEY + ".owned", ui.showOwned ? "1" : "0"); } catch (err) {} render(); }
  });
  document.addEventListener("click", function (ev) { if (ui.open && !v.contains(ev.target)) { ui.open = false; renderPicker(); } });
  var started = false;
  VB.registerTab("completion", "completionView", function () { if (!started) { started = true; select(ui.set); } else render(); }, "set-completion");
  VB.completion = { pickPrice: pickPrice, select: select, ui: ui };
})();
