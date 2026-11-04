// My Binders: custom binders you lay out yourself ("Eeveelutions", "Charizards", "Fire types", ...).
// Pockets hold a row key from build.py (same stable keys as Pokédex picks), a grayed species placeholder,
// or nothing. Everything is saved in localStorage; Export/Import moves it between browsers, and
// data/binders.json (an exported file) becomes the default set of binders on every browser.
(function () {
  "use strict";
  var VB = window.VB; if (!VB) return; // no binder-data.js yet
  var D = VB.D, $ = VB.$, esc = VB.esc, money = VB.money, DEX = VB.DEX;
  var SKEY = "virtualBinder.binders.v1";
  var TYPES = ["Grass", "Fire", "Water", "Lightning", "Psychic", "Fighting", "Darkness", "Metal", "Dragon", "Fairy", "Colorless"];
  var PRESETS = [
    { id: "eevee", name: "Eeveelutions", mode: "species", q: "Eevee, Vaporeon, Jolteon, Flareon, Espeon, Umbreon, Leafeon, Glaceon, Sylveon", layout: 3, placeholders: true },
    { id: "zard", name: "Charizards", mode: "name", q: "Charizard", layout: 3 },
    { id: "pika", name: "Pikachus", mode: "name", q: "Pikachu", layout: 4 },
    { id: "kanto-starters", name: "Kanto starters", mode: "species", q: "Bulbasaur, Ivysaur, Venusaur, Charmander, Charmeleon, Charizard, Squirtle, Wartortle, Blastoise", layout: 3, placeholders: true },
    { id: "fire", name: "Fire types", mode: "type", q: "Fire", layout: 4, needsTypes: true }
  ].filter(function (p) { return !p.needsTypes || D.hasTypes; });

  // ---- cards: one tray card per CSV row ----
  var setOrder = {}; D.sets.forEach(function (s, i) { setOrder[s.key] = i; });
  var speciesByName = {}; DEX.forEach(function (k) { speciesByName[k.name.toLowerCase()] = k.dex; });
  var cards = D.entries.map(function (e, i) {
    var s = VB.setsByKey[e.console];
    return { i: i, e: e, set: s ? s.name : e.console.replace(/^Pokemon /, ""),
      hay: [e.product, e.name, e.variant, e.number, "#" + e.number, s ? s.name : e.console, e.grade, (e.types || []).join(" "), (e.species || []).map(function (d) { return DEX[d - 1].name; }).join(" ")].join(" ").toLowerCase(),
      order: (setOrder[e.console] != null ? setOrder[e.console] : 999) * 1e4 + VB.numKey(e.number)[1] };
  });
  function entryIndex(k) {
    // Same stable row key as picks; if the row details changed in a new export, fall back to the same
    // PriceCharting product (preferring the same grade).
    var i = VB.byEntryKey[k];
    if (i != null) return i;
    var parts = String(k).split("|"), alts = VB.byPcId[parts[0]] || [];
    return alts.filter(function (j) { return D.entries[j].grade === parts[1]; })[0] != null ? alts.filter(function (j) { return D.entries[j].grade === parts[1]; })[0] : alts[0];
  }

  // ---- storage ----
  var store, storageOK = true;
  function blank() { return { version: 1, active: null, binders: [] }; }
  function clean(b) {
    var n = b.layout === 4 ? 4 : 3, size = n * n;
    var pages = (Array.isArray(b.pages) ? b.pages : []).map(function (pg) {
      var out = [];
      for (var i = 0; i < size; i++) {
        var x = pg && pg[i];
        out.push(x && typeof x.k === "string" ? { k: x.k } : x && +x.dex >= 1 && +x.dex <= DEX.length ? { dex: +x.dex } : null);
      }
      return out;
    });
    if (!pages.length) pages.push(emptyPage(n));
    return { id: String(b.id || uid()), name: String(b.name || "Untitled binder").slice(0, 80), layout: n, pages: pages };
  }
  function load() {
    var raw = null;
    try { raw = localStorage.getItem(SKEY); } catch (err) { storageOK = false; }
    var j = null;
    try { j = raw ? JSON.parse(raw) : null; } catch (err) { j = null; }
    if (!j) j = { binders: D.defaultBinders || [] };
    var s = blank();
    s.binders = (j.binders || []).map(clean);
    s.active = s.binders.some(function (b) { return b.id === j.active; }) ? j.active : (s.binders[0] || {}).id || null;
    return s;
  }
  function save() {
    try { localStorage.setItem(SKEY, JSON.stringify(store)); storageOK = localStorage.getItem(SKEY) !== null; } catch (err) { storageOK = false; }
  }
  function uid() { return "b" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6); }
  function emptyPage(n) { var a = []; for (var i = 0; i < n * n; i++) a.push(null); return a; }
  function cur() { return store.binders.filter(function (b) { return b.id === store.active; })[0] || null; }
  store = load();

  // ---- binder operations ----
  function flat(b) { return [].concat.apply([], b.pages); }
  function repaginate(b, slots) {
    var size = b.layout * b.layout;
    while (slots.length && slots[slots.length - 1] == null) slots.pop();
    b.pages = [];
    for (var i = 0; i < Math.max(slots.length, 1); i += size) {
      var pg = slots.slice(i, i + size); while (pg.length < size) pg.push(null); b.pages.push(pg);
    }
  }
  function create(name, layout) {
    var b = clean({ id: uid(), name: name, layout: layout || 3, pages: [] });
    store.binders.push(b); store.active = b.id; save(); return b;
  }
  function keysIn(b) { var o = {}; flat(b).forEach(function (x) { if (x && x.k) o[x.k] = (o[x.k] || 0) + 1; }); return o; }
  function addSlots(b, list) {
    // Fill empty pockets first (in page order), then add pages as needed.
    var slots = flat(b), j = 0;
    list.forEach(function (x) {
      while (j < slots.length && slots[j] != null) j++;
      if (j < slots.length) slots[j] = x; else slots.push(x);
      j++;
    });
    var size = b.layout * b.layout, keep = slots.slice();
    b.pages = [];
    for (var i = 0; i < keep.length; i += size) { var pg = keep.slice(i, i + size); while (pg.length < size) pg.push(null); b.pages.push(pg); }
    if (!b.pages.length) b.pages.push(emptyPage(b.layout));
  }
  function parseSpecies(q) {
    var bad = [], out = [];
    q.split(/[,\n]+/).map(function (x) { return x.trim(); }).filter(Boolean).forEach(function (x) {
      var d = /^#?\d+$/.test(x) ? +x.replace("#", "") : speciesByName[x.toLowerCase()];
      if (d >= 1 && d <= DEX.length) { if (out.indexOf(d) < 0) out.push(d); } else bad.push(x);
    });
    return { dex: out, bad: bad };
  }
  // Quick-fill rules. Returns {slots, note}; cards already in the binder are skipped.
  function fillRule(b, mode, q, opts) {
    var have = keysIn(b), slots = [], note = "";
    var byValue = function (a, c) { return c.e.unitCents - a.e.unitCents || a.order - c.order; };
    var bySet = function (a, c) { return a.order - c.order; };
    if (mode === "species") {
      var sp = parseSpecies(q);
      if (sp.bad.length) note = "Not a Pokémon name: " + sp.bad.join(", ") + ". ";
      var placedDex = {};
      flat(b).forEach(function (x) { if (x && x.dex) placedDex[x.dex] = 1; if (x && x.k) { var i = entryIndex(x.k); if (i != null) (D.entries[i].species || []).forEach(function (d) { placedDex[d] = 1; }); } });
      sp.dex.forEach(function (d) {
        var own = DEX[d - 1].cards.filter(function (i) { return !have[D.entries[i].key]; });
        if (opts.onePer) own = placedDex[d] ? [] : own.slice(0, 1); // cards are most valuable first
        own.forEach(function (i) { slots.push({ k: D.entries[i].key }); have[D.entries[i].key] = 1; });
        if (!DEX[d - 1].cards.length && opts.placeholders && !placedDex[d]) slots.push({ dex: d });
      });
    } else {
      var needle = q.trim().toLowerCase();
      if (!needle) return { slots: [], note: "Type something to match first." };
      var hits = cards.filter(function (c) {
        if (have[c.e.key]) return false;
        if (mode === "type") return (c.e.types || []).some(function (t) { return t.toLowerCase() === needle; });
        return c.e.name.toLowerCase().indexOf(needle) >= 0 || c.e.product.toLowerCase().indexOf(needle) >= 0;
      }).sort(opts.sort === "value" ? byValue : bySet);
      slots = hits.map(function (c) { return { k: c.e.key }; });
    }
    return { slots: slots, note: note };
  }

  // ---- view state ----
  var ui = { q: "", set: "", type: "", hideUsed: true, tray: "cards", sort: "value", sel: null, fill: { mode: "species", q: PRESETS[0] ? PRESETS[0].q : "", preset: PRESETS[0] ? PRESETS[0].id : "", placeholders: true, onePer: false, sort: "set" } };
  var built = false;

  function slotHTML(x, p, s) {
    var at = ' data-p="' + p + '" data-s="' + s + '"';
    if (!x) return '<div class="pocket empty bslot"' + at + '><span class="plus">+</span></div>';
    var sel = ui.sel && ui.sel.from === "pocket" && ui.sel.p === p && ui.sel.s === s ? " sel" : "";
    var rm = '<button class="brm" data-rm="1" title="Remove from this binder" aria-label="Remove">×</button>';
    if (x.dex) {
      var k = DEX[x.dex - 1], owned = k.cards.length;
      return '<div class="pocket bslot kslot missing ph' + sel + '" draggable="true"' + at + '><img class="art" src="' + esc(k.art) + '" alt="">' + rm +
        '<span class="tag grade">#' + String(k.dex).padStart(3, "0") + "</span>" +
        '<div class="caption"><div class="n" title="' + esc(k.name) + '">' + esc(k.name) + '</div><div class="row"><span>' + (owned ? "you own " + owned + " · drop one here" : "not owned yet") + "</span></div></div></div>";
    }
    var i = entryIndex(x.k);
    if (i == null) {
      return '<div class="pocket bslot missing gone' + sel + '" draggable="true"' + at + ">" + rm + '<div class="noimg"><b>No longer in your collection</b>This row isn\'t in the current export.</div></div>';
    }
    var e = D.entries[i], art = e.species && e.species[0] ? DEX[e.species[0] - 1].art : null;
    return '<div class="pocket bslot filled' + VB.pcCls(e.images) + sel + '" draggable="true"' + at + ' data-i="' + i + '">' +
      VB.imgTag(e.images, { alt: e.name, art: art, fbHtml: "<b>" + esc(e.name) + "</b>#" + esc(e.number) }) + rm +
      '<span class="tag grade' + (e.graded ? " graded" : "") + '">' + esc(e.grade) + "</span>" +
      '<div class="caption"><div class="n" title="' + esc(e.product) + '">' + esc(e.name) + (e.variant ? ' <span style="color:var(--ink-3)">· ' + esc(e.variant) + "</span>" : "") + "</div>" +
      '<div class="row"><span class="setn">' + esc(e.console.replace(/^Pokemon /, "")) + " #" + esc(e.number) + '</span><span class="v">' + money(e.unitCents) + "</span></div></div></div>";
  }
  function stats(b) {
    var f = flat(b), filled = 0, ph = 0, val = 0, gone = 0;
    f.forEach(function (x) { if (!x) return; if (x.dex) { ph++; return; } var i = entryIndex(x.k); if (i == null) { gone++; return; } filled++; val += D.entries[i].unitCents; });
    return { total: f.length, filled: filled, ph: ph, gone: gone, val: val };
  }
  function trayItems(b) {
    var used = b ? keysIn(b) : {};
    var items;
    if (ui.tray === "species") {
      var q = ui.q;
      items = DEX.filter(function (k) { return !k.cards.length && (!q || (k.name + " #" + k.dex).toLowerCase().indexOf(q) >= 0); }).slice(0, 300).map(function (k) {
        return '<div class="tcard ph' + (ui.sel && ui.sel.from === "tray" && ui.sel.slot.dex === k.dex ? " sel" : "") + '" draggable="true" data-dex="' + k.dex + '"><img src="' + esc(k.art) + '" alt="" loading="lazy">' +
          '<div class="tn">' + esc(k.name) + '</div><div class="ts">#' + String(k.dex).padStart(3, "0") + " · not owned</div></div>";
      });
    } else {
      var list = cards.filter(function (c) {
        return (!ui.q || c.hay.indexOf(ui.q) >= 0) && (!ui.set || c.e.console === ui.set) &&
          (!ui.type || (ui.type === "Trainer" || ui.type === "Energy" ? c.e.category === ui.type : (c.e.types || []).indexOf(ui.type) >= 0)) &&
          (!ui.hideUsed || !used[c.e.key]);
      });
      list.sort(ui.sort === "name" ? function (a, c) { return a.e.name.localeCompare(c.e.name) || a.order - c.order; } :
        ui.sort === "set" ? function (a, c) { return a.order - c.order; } : function (a, c) { return c.e.unitCents - a.e.unitCents || a.order - c.order; });
      items = list.map(function (c) {
        var e = c.e, th = e.images && e.images[0] ? e.images[0].thumb : (e.species && e.species[0] ? DEX[e.species[0] - 1].art : "");
        return '<div class="tcard' + (used[e.key] ? " used" : "") + (ui.sel && ui.sel.from === "tray" && ui.sel.slot.k === e.key ? " sel" : "") + '" draggable="true" data-k="' + esc(e.key) + '" title="' + esc(e.product + " · " + c.set + (e.qty > 1 ? " · x" + e.qty : "")) + '">' +
          (th ? '<img src="' + esc(th) + '" alt="" loading="lazy">' : '<div class="tnoimg"></div>') +
          '<div class="tn">' + esc(e.name) + (e.variant ? " · " + esc(e.variant) : "") + '</div><div class="ts">' + esc(c.set) + " #" + esc(e.number) + '</div><div class="tv">' + money(e.unitCents) +
          (e.grade !== "Raw" ? " · " + esc(e.grade) : "") + (used[e.key] ? ' · <span class="inb">in binder</span>' : "") + "</div></div>";
      });
    }
    return { items: items, count: items.length + (ui.tray === "species" ? " unowned species" : " cards") + " · drag into a pocket, or click then click a pocket. Drop a pocket here to remove it." };
  }
  function trayHTML(b) {
    var ti = trayItems(b);
    var setOpts = '<option value="">All sets</option>' + D.sets.map(function (s) { return '<option value="' + esc(s.key) + '"' + (ui.set === s.key ? " selected" : "") + ">" + esc(s.name) + "</option>"; }).join("");
    var typeOpts = D.hasTypes ? '<select data-f="type"><option value="">All types</option>' + TYPES.concat(["Trainer", "Energy"]).map(function (t) { return '<option' + (ui.type === t ? " selected" : "") + ">" + t + "</option>"; }).join("") + "</select>" : "";
    return '<div class="tray-head"><div class="seg"><button data-tray="cards" class="' + (ui.tray === "cards" ? "on" : "") + '">My cards</button><button data-tray="species" class="' + (ui.tray === "species" ? "on" : "") + '">Unowned species</button></div>' +
      '<input type="search" data-f="q" placeholder="' + (ui.tray === "species" ? "Pokémon name or dex #" : "Name, set, number, type…") + '" value="' + esc(ui.q) + '" autocomplete="off">' +
      (ui.tray === "cards" ? '<div class="tray-filters"><select data-f="set">' + setOpts + "</select>" + typeOpts +
        '<select data-f="sort"><option value="value"' + (ui.sort === "value" ? " selected" : "") + '>Most valuable</option><option value="set"' + (ui.sort === "set" ? " selected" : "") + '>Set order</option><option value="name"' + (ui.sort === "name" ? " selected" : "") + ">Name</option></select>" +
        '<label><input type="checkbox" data-f="hideUsed"' + (ui.hideUsed ? " checked" : "") + "> Hide cards in this binder</label></div>" : "") +
      '<div class="tray-count">' + esc(ti.count) + "</div></div>" +
      '<div class="tray-list">' + (ti.items.join("") || '<p class="tray-empty">No cards match.</p>') + "</div>";
  }
  function fillHTML() {
    var f = ui.fill;
    return '<details class="fill"' + (ui.fillOpen ? " open" : "") + "><summary>Quick fill</summary><div class=\"fill-row\">" +
      '<select data-fill="preset"><option value="">Preset…</option>' + PRESETS.map(function (p) { return '<option value="' + p.id + '"' + (f.preset === p.id ? " selected" : "") + ">" + esc(p.name) + "</option>"; }).join("") + "</select>" +
      '<select data-fill="mode"><option value="species"' + (f.mode === "species" ? " selected" : "") + '>Species in a list</option><option value="name"' + (f.mode === "name" ? " selected" : "") + ">Name contains</option>" +
      (D.hasTypes ? '<option value="type"' + (f.mode === "type" ? " selected" : "") + ">Pokémon type</option>" : "") + "</select>" +
      (f.mode === "type" ? '<select data-fill="q">' + TYPES.map(function (t) { return "<option" + (f.q === t ? " selected" : "") + ">" + t + "</option>"; }).join("") + "</select>" :
        '<input data-fill="q" type="text" value="' + esc(f.q) + '" placeholder="' + (f.mode === "species" ? "Eevee, Vaporeon, Jolteon…" : "Charizard") + '">') +
      (f.mode === "species" ? '<label><input type="checkbox" data-fill="onePer"' + (f.onePer ? " checked" : "") + "> One card per species</label>" +
        '<label><input type="checkbox" data-fill="placeholders"' + (f.placeholders ? " checked" : "") + "> Grayed placeholders for species I don't own</label>" :
        '<select data-fill="sort"><option value="set"' + (f.sort === "set" ? " selected" : "") + '>Set order</option><option value="value"' + (f.sort === "value" ? " selected" : "") + ">Most valuable first</option></select>") +
      '<button class="btn primary" data-act="fill">Add matching cards</button></div><div class="fill-note" id="fillNote"></div></details>';
  }
  function render() {
    var v = $("bindersView"), b = cur();
    var scrollTray = v.querySelector(".tray-list") ? v.querySelector(".tray-list").scrollTop : 0;
    var focus = document.activeElement && v.contains(document.activeElement) ? document.activeElement.getAttribute("data-f") : null;
    if (!b) {
      v.innerHTML = '<div class="bempty"><h2>My Binders</h2><p>Make your own binders, like Eeveelutions, Charizards or Fire types, and drag your cards into the pockets you want.</p>' +
        '<div class="bempty-row"><button class="btn primary" data-act="new">New empty binder</button>' +
        PRESETS.map(function (p) { return '<button class="btn" data-preset-new="' + p.id + '">' + esc(p.name) + "</button>"; }).join("") + "</div>" +
        '<p class="hint">Binders save in this browser. <button class="btn sm" data-act="import">Import binders.json</button></p>' + fileInput() + warn() + "</div>";
      return;
    }
    var st = stats(b), n = b.layout, pages = "";
    b.pages.forEach(function (pg, p) {
      pages += '<div class="page"><div class="grid' + (n === 4 ? " g4" : "") + '">' + pg.map(function (x, s) { return slotHTML(x, p, s); }).join("") +
        '</div><span class="page-no">' + (p + 1) + (b.pages.length > 1 ? ' <button class="pgrm" data-delpage="' + p + '" title="Delete this page">delete page</button>' : "") + "</span></div>";
    });
    var selName = ui.sel ? (ui.sel.from === "tray" ? (ui.sel.slot.k ? D.entries[entryIndex(ui.sel.slot.k)].product : DEX[ui.sel.slot.dex - 1].name + " placeholder") : "pocket " + (ui.sel.s + 1) + " on page " + (ui.sel.p + 1)) : "";
    v.innerHTML = '<div class="bbar">' +
      '<select id="binderPick" aria-label="Binder">' + store.binders.map(function (x) { return '<option value="' + esc(x.id) + '"' + (x === b ? " selected" : "") + ">" + esc(x.name) + "</option>"; }).join("") + "</select>" +
      '<button class="btn" data-act="new">New</button><button class="btn" data-act="rename">Rename</button><button class="btn" data-act="delete">Delete</button>' +
      '<span class="seg layout" role="group" aria-label="Page layout"><button data-layout="3" class="' + (n === 3 ? "on" : "") + '">3×3</button><button data-layout="4" class="' + (n === 4 ? "on" : "") + '">4×4</button></span>' +
      '<button class="btn" data-act="addpage">Add page</button><button class="btn" data-act="compact" title="Move cards up to fill gaps">Close gaps</button>' +
      '<span class="spacer"></span><button class="btn" data-act="export">Export binders</button><button class="btn" data-act="import">Import</button>' + fileInput() + "</div>" +
      '<div class="bwrap"><section class="bpages"><div class="set-head"><h2>' + esc(b.name) + '</h2><span class="meta">' + st.filled + " card" + (st.filled === 1 ? "" : "s") +
      (st.ph ? " · " + st.ph + " placeholder" + (st.ph === 1 ? "" : "s") : "") + (st.gone ? " · " + st.gone + " no longer owned" : "") + " · " + (st.total - st.filled - st.ph - st.gone) + " empty · " +
      b.pages.length + " page" + (b.pages.length === 1 ? "" : "s") + ' · <span class="val">' + money(st.val) + "</span> per-card value</span>" + warn() + "</div>" +
      fillHTML() +
      (ui.sel ? '<div class="selbar">Placing: <b>' + esc(selName) + "</b>. Click a pocket" + (ui.sel.from === "pocket" ? ' to move it there, or <button class="btn sm" data-act="selrm">Remove from binder</button>' : "") + ' <button class="btn sm" data-act="selcancel">Cancel</button></div>' : "") +
      '<div class="pages">' + pages + "</div></section>" +
      '<aside class="tray" id="tray">' + trayHTML(b) + "</aside></div>";
    var tl = v.querySelector(".tray-list"); if (tl) tl.scrollTop = scrollTray;
    if (focus) { var f = v.querySelector('[data-f="' + focus + '"]'); if (f) { f.focus(); if (f.setSelectionRange && f.type === "search") f.setSelectionRange(f.value.length, f.value.length); } }
  }
  function renderTray() {
    // Only the list and count change, so the search box keeps focus while typing.
    var t = $("tray"), b = cur(); if (!t || !b) return render();
    var ti = trayItems(b);
    t.querySelector(".tray-list").innerHTML = ti.items.join("") || '<p class="tray-empty">No cards match.</p>';
    t.querySelector(".tray-count").textContent = ti.count;
  }
  function fileInput() { return '<input type="file" id="bindersFile" accept=".json,application/json" hidden>'; }
  function warn() { return storageOK ? "" : '<div class="warn">This browser isn\'t saving binders for local files. Use Export binders, save the file as data/binders.json and rebuild.</div>'; }
  function commit() { save(); render(); }

  // ---- placing / moving ----
  function slotAt(b, p, s) { return b.pages[p] ? b.pages[p][s] : undefined; }
  function place(src, p, s) {
    var b = cur(); if (!b || slotAt(b, p, s) === undefined) return;
    if (src.from === "tray") b.pages[p][s] = src.slot.k ? { k: src.slot.k } : { dex: src.slot.dex };
    else if (src.from === "pocket") {
      if (src.p === p && src.s === s) return;
      var a = slotAt(b, src.p, src.s); if (a === undefined) return;
      b.pages[src.p][src.s] = b.pages[p][s]; b.pages[p][s] = a; // swap (moving onto an empty pocket just moves)
    }
    ui.sel = null; commit();
  }
  function removeAt(p, s) { var b = cur(); if (b && slotAt(b, p, s) !== undefined) { b.pages[p][s] = null; ui.sel = null; commit(); } }

  // ---- events ----
  var v = $("bindersView");
  v.addEventListener("click", function (ev) {
    var t = ev.target, b = cur(), a;
    if ((a = t.closest("[data-preset-new]"))) { var pr = PRESETS.filter(function (x) { return x.id === a.getAttribute("data-preset-new"); })[0]; newFromPreset(pr); return; }
    if ((a = t.closest("[data-tray]"))) { ui.tray = a.getAttribute("data-tray"); ui.q = ""; ui.sel = null; render(); return; }
    if ((a = t.closest("[data-layout]"))) { setLayout(+a.getAttribute("data-layout")); return; }
    if ((a = t.closest("[data-delpage]"))) {
      var pi = +a.getAttribute("data-delpage"), used = b.pages[pi].filter(Boolean).length;
      if (used && !confirm("Delete page " + (pi + 1) + " and the " + used + " pocket(s) on it?")) return;
      b.pages.splice(pi, 1); if (!b.pages.length) b.pages.push(emptyPage(b.layout)); ui.sel = null; commit(); return;
    }
    if ((a = t.closest("[data-act]"))) { act(a.getAttribute("data-act")); return; }
    var pk = t.closest(".bslot");
    if (pk) {
      var p = +pk.getAttribute("data-p"), s = +pk.getAttribute("data-s");
      if (t.closest("[data-rm]")) { removeAt(p, s); return; }
      if (ui.sel) { place(ui.sel, p, s); return; }
      if (slotAt(b, p, s)) { ui.sel = { from: "pocket", p: p, s: s }; render(); }
      return;
    }
    var tc = t.closest(".tcard");
    if (tc) {
      var slot = tc.hasAttribute("data-k") ? { k: tc.getAttribute("data-k") } : { dex: +tc.getAttribute("data-dex") };
      var same = ui.sel && ui.sel.from === "tray" && (ui.sel.slot.k ? ui.sel.slot.k === slot.k : ui.sel.slot.dex === slot.dex);
      ui.sel = same ? null : { from: "tray", slot: slot }; render();
    }
  });
  v.addEventListener("dblclick", function (ev) {
    var pk = ev.target.closest(".bslot.filled[data-i]"); if (!pk) return;
    var e = D.entries[+pk.getAttribute("data-i")];
    VB.setZoomImg(e.images, e.species && e.species[0] ? DEX[e.species[0] - 1].art : null);
    $("zoomInfo").innerHTML = "<h3>" + esc(e.name) + "</h3><div>" + esc(e.console.replace(/^Pokemon /, "")) + " · #" + esc(e.number) + (e.variant ? " · " + esc(e.variant) : "") + "</div><dl>" +
      "<dt>Grade</dt><dd>" + esc(e.grade) + "</dd><dt>Quantity</dt><dd>" + e.qty + "</dd><dt>Per card</dt><dd>" + money(e.unitCents) + "</dd>" +
      ((e.types || []).length ? "<dt>Type</dt><dd>" + esc(e.types.join(", ")) + "</dd>" : "") + "</dl>";
    ui.sel = null; render(); $("zoom").hidden = false;
  });
  v.addEventListener("input", function (ev) {
    var f = ev.target.getAttribute("data-f"), fl = ev.target.getAttribute("data-fill");
    if (f === "q") { ui.q = ev.target.value.trim().toLowerCase(); renderTray(); }
    if (fl === "q" && ev.target.tagName === "INPUT") { ui.fill.q = ev.target.value; ui.fill.preset = ""; }
  });
  v.addEventListener("change", function (ev) {
    var t = ev.target, f = t.getAttribute("data-f"), fl = t.getAttribute("data-fill");
    if (t.id === "binderPick") { store.active = t.value; ui.sel = null; commit(); return; }
    if (t.id === "bindersFile") { importFile(t.files[0]); return; }
    if (f === "set" || f === "type" || f === "sort") { ui[f] = t.value; renderTray(); return; }
    if (f === "hideUsed") { ui.hideUsed = t.checked; renderTray(); return; }
    if (fl) {
      ui.fillOpen = true;
      if (fl === "preset") {
        var pr = PRESETS.filter(function (x) { return x.id === t.value; })[0];
        ui.fill.preset = t.value; if (pr) { ui.fill.mode = pr.mode; ui.fill.q = pr.q; ui.fill.placeholders = !!pr.placeholders; }
      } else if (fl === "mode") { ui.fill.mode = t.value; ui.fill.preset = ""; ui.fill.q = t.value === "type" ? "Fire" : ""; }
      else if (fl === "onePer" || fl === "placeholders") ui.fill[fl] = t.checked;
      else ui.fill[fl] = t.value;
      render();
    }
  });
  v.addEventListener("toggle", function (ev) { if (ev.target.classList && ev.target.classList.contains("fill")) ui.fillOpen = ev.target.open; }, true);

  // HTML5 drag and drop. Payload: {from: "tray", slot} or {from: "pocket", p, s}.
  var drag = null;
  v.addEventListener("dragstart", function (ev) {
    var tc = ev.target.closest && ev.target.closest(".tcard"), pk = ev.target.closest && ev.target.closest(".bslot[draggable]");
    if (tc) drag = { from: "tray", slot: tc.hasAttribute("data-k") ? { k: tc.getAttribute("data-k") } : { dex: +tc.getAttribute("data-dex") } };
    else if (pk) drag = { from: "pocket", p: +pk.getAttribute("data-p"), s: +pk.getAttribute("data-s") };
    else return;
    ev.dataTransfer.effectAllowed = "move";
    try { ev.dataTransfer.setData("text/plain", JSON.stringify(drag)); } catch (err) {}
    document.body.classList.add("dragging"); if (drag.from === "pocket") document.body.classList.add("dragging-pocket");
  });
  function endDrag() { drag = null; document.body.classList.remove("dragging", "dragging-pocket"); v.querySelectorAll(".over").forEach(function (x) { x.classList.remove("over"); }); }
  document.addEventListener("dragend", endDrag);
  document.addEventListener("dragover", function (ev) {
    if (!drag || $("bindersView").hidden) return;
    var pk = ev.target.closest && ev.target.closest(".bslot");
    // Pockets accept anything; while dragging a pocket, anywhere else is a "drag out to remove" target.
    if (pk || drag.from === "pocket") { ev.preventDefault(); ev.dataTransfer.dropEffect = "move"; }
    v.querySelectorAll(".over").forEach(function (x) { if (x !== pk) x.classList.remove("over"); });
    if (pk) pk.classList.add("over");
  });
  document.addEventListener("drop", function (ev) {
    if (!drag || $("bindersView").hidden) return;
    ev.preventDefault();
    var src = drag, pk = ev.target.closest && ev.target.closest(".bslot");
    endDrag();
    if (pk) place(src, +pk.getAttribute("data-p"), +pk.getAttribute("data-s"));
    else if (src.from === "pocket") removeAt(src.p, src.s);
  });

  function act(name) {
    var b = cur();
    if (name === "new") {
      var nm = prompt("Name for the new binder:", "New binder"); if (!nm || !nm.trim()) return;
      create(nm.trim(), 3); ui.sel = null; render();
    } else if (name === "rename") {
      var r = prompt("Rename binder:", b.name); if (!r || !r.trim()) return; b.name = r.trim().slice(0, 80); commit();
    } else if (name === "delete") {
      if (!confirm('Delete the binder "' + b.name + '"? This can\'t be undone (export first to keep a copy).')) return;
      store.binders = store.binders.filter(function (x) { return x !== b; }); store.active = (store.binders[0] || {}).id || null; ui.sel = null; commit();
    } else if (name === "addpage") { b.pages.push(emptyPage(b.layout)); commit(); }
    else if (name === "compact") { repaginate(b, flat(b).filter(Boolean)); commit(); }
    else if (name === "fill") {
      var res = fillRule(b, ui.fill.mode, ui.fill.q, ui.fill);
      addSlots(b, res.slots); ui.fillOpen = true; commit();
      var nEl = $("fillNote"); if (nEl) nEl.textContent = res.note + (res.slots.length ? "Added " + res.slots.length + " pocket(s)." : "Nothing new to add.");
    } else if (name === "selcancel") { ui.sel = null; render(); }
    else if (name === "selrm") { if (ui.sel && ui.sel.from === "pocket") removeAt(ui.sel.p, ui.sel.s); }
    else if (name === "export") {
      var blob = new Blob([JSON.stringify({ version: 1, exported: new Date().toISOString(), binders: store.binders }, null, 2) + "\n"], { type: "application/json" });
      var a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "binders.json";
      document.body.appendChild(a); a.click(); setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
    } else if (name === "import") $("bindersFile").click();
  }
  function setLayout(n) {
    var b = cur(); if (!b || b.layout === n) return;
    var slots = flat(b); b.layout = n; repaginate(b, slots); ui.sel = null; commit();
  }
  function newFromPreset(pr) {
    if (!pr) return;
    var b = create(pr.name, pr.layout);
    addSlots(b, fillRule(b, pr.mode, pr.q, { placeholders: !!pr.placeholders, onePer: false, sort: "set" }).slots);
    ui.fill.mode = pr.mode; ui.fill.q = pr.q; ui.fill.preset = pr.id; commit();
  }
  function importFile(file) {
    if (!file) return;
    var fr = new FileReader();
    fr.onload = function () {
      try {
        var j = JSON.parse(fr.result), list = Array.isArray(j) ? j : j && j.binders;
        if (!Array.isArray(list)) throw new Error("no binders list");
        var byId = {}; store.binders.forEach(function (x, i) { byId[x.id] = i; });
        list.map(clean).forEach(function (x) { if (byId[x.id] != null) store.binders[byId[x.id]] = x; else store.binders.push(x); });
        if (!store.active && store.binders[0]) store.active = store.binders[0].id;
        commit(); alert("Imported " + list.length + " binder(s). Binders with the same id were replaced.");
      } catch (err) { alert("That file is not a valid binders.json: " + err.message); }
    };
    fr.readAsText(file);
  }

  VB.registerTab("binders", "bindersView", function () { if (!built) { built = true; } render(); }, "binders");
  VB.binders = { store: function () { return store; }, entryIndex: entryIndex, fillRule: fillRule }; // for tests / console use
})();
