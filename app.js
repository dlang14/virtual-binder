(function () {
  "use strict";
  var D = window.BINDER_DATA;
  if (!D) {
    // No generated data yet (fresh clone): explain how to build it instead of showing a broken page.
    var nav = document.querySelector(".controls"); if (nav) nav.style.display = "none";
    document.getElementById("binder").innerHTML = '<div class="empty-msg"><h2>Run the build first</h2>' +
      "<p>This page reads <code>binder-data.js</code>, which is generated from your PriceCharting collection export and isn't included in the repo.</p>" +
      "<ol><li>Export your collection from PriceCharting as a CSV and save it as <code>data/collection.csv</code>.</li>" +
      "<li>Run <code>python3 scripts/build.py</code> (on Windows: <code>py scripts\\build.py</code>). To try it with the example data instead, run <code>python3 scripts/build.py data/sample-collection.csv</code>.</li>" +
      "<li>Reload this page.</li></ol></div>";
    return;
  }

  var $ = function (id) { return document.getElementById(id); };
  var money = function (c) { return "$" + (c / 100).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); };
  var esc = function (s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (ch) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]; }); };
  var numKey = function (n) { var m = /^([A-Za-z]*)(\d+)/.exec(String(n || "")); return m ? [m[1].toUpperCase(), +m[2]] : ["~", 1e9]; };

  var state = { set: "__all", sort: "set", q: "", missing: {} , missingAll: false };

  // ---- group CSV rows into pockets (one pocket per distinct card + variant + grade) ----
  var setsByKey = {};
  D.sets.forEach(function (s) { setsByKey[s.key] = s; s.slotIndex = {}; (s.completeList || []).forEach(function (c, i) { if (!(c.slot in s.slotIndex)) s.slotIndex[c.slot] = i; }); });

  // ---- images: card database image first, then PriceCharting's photo, then artwork / a labeled sleeve ----
  // srcs = e.images from build.py ([{img, thumb, source: "db" | "pc"}]). If a URL fails to load, the
  // document-level error handler below moves on to the next source, then to the fallback.
  function imgTag(srcs, opts) {
    opts = opts || {};
    var list = (srcs || []).map(function (x) { return { u: opts.large ? x.img : (x.thumb || x.img), s: x.source }; });
    var fbArt = opts.art ? ' data-fb-art="' + esc(opts.art) + '"' : "";
    var fbHtml = opts.fbHtml ? ' data-fb-html="' + esc(opts.fbHtml) + '"' : "";
    if (!list.length) return opts.art ? '<img class="art owned-art" src="' + esc(opts.art) + '" alt="">' : '<div class="noimg">' + (opts.fbHtml || "") + "</div>";
    return '<img' + (opts.lazy ? ' loading="lazy"' : "") + ' src="' + esc(list[0].u) + '" alt="' + esc(opts.alt || "") + '" data-srcs="' + esc(JSON.stringify(list)) + '" data-i="0"' + fbArt + fbHtml + ">" +
      '<span class="tag pcmark" title="Photo from PriceCharting (no card-database image)">PC photo</span>';
  }
  var firstSrc = function (srcs) { return srcs && srcs[0] ? srcs[0].source : null; };
  var pcCls = function (srcs) { return firstSrc(srcs) === "pc" ? " src-pc" : ""; };
  document.addEventListener("error", function (ev) {
    var im = ev.target;
    if (!im || im.tagName !== "IMG" || !im.hasAttribute("data-srcs")) return;
    var list = JSON.parse(im.getAttribute("data-srcs")), i = +im.getAttribute("data-i") + 1;
    var holder = im.closest(".pocket") || im.parentNode;
    if (i < list.length) {
      im.setAttribute("data-i", i); if (holder) holder.classList.toggle("src-pc", list[i].s === "pc"); im.src = list[i].u; return;
    }
    im.removeAttribute("data-srcs"); if (holder) holder.classList.remove("src-pc");
    var art = im.getAttribute("data-fb-art");
    if (art) { im.className = "art owned-art"; im.src = art; return; }
    if (im.id === "zoomImg") { im.style.display = "none"; return; }
    var d = document.createElement("div"); d.className = "noimg"; d.innerHTML = im.getAttribute("data-fb-html") || "Image unavailable"; im.replaceWith(d);
  }, true);
  function setZoomImg(srcs, art) {
    var z = $("zoomImg"), list = (srcs || []).map(function (x) { return { u: x.img, s: x.source }; });
    z.removeAttribute("data-srcs"); z.removeAttribute("data-fb-art");
    z.parentNode.classList.toggle("src-pc", firstSrc(srcs) === "pc");
    if (list.length) {
      z.setAttribute("data-srcs", JSON.stringify(list)); z.setAttribute("data-i", "0");
      if (art) z.setAttribute("data-fb-art", art);
      z.src = list[0].u; z.style.display = "";
    } else if (art) { z.src = art; z.style.display = ""; }
    else { z.src = ""; z.style.display = "none"; }
  }

  var pockets = {};
  D.entries.forEach(function (e) {
    if (!e.match) return;
    var k = e.console + "|" + e.match.id + "|" + (e.variant || "") + "|" + e.grade;
    var p = pockets[k];
    if (!p) {
      p = pockets[k] = { key: k, set: e.console, name: e.name, variant: e.variant, number: e.number, grade: e.grade, graded: e.graded,
        images: e.images || [], match: e.match, slot: e.slot, qty: 0, valueCents: 0, rows: [] };
    }
    p.qty += e.qty; p.valueCents += e.valueCents; p.rows.push(e);
  });
  pockets = Object.keys(pockets).map(function (k) { return pockets[k]; });
  pockets.forEach(function (p) {
    p.unitCents = p.qty ? Math.round(p.valueCents / p.qty) : p.valueCents;
    var s = setsByKey[p.set];
    p.order = s && p.slot in s.slotIndex ? s.slotIndex[p.slot] : 1e6 + numKey(p.number)[1];
    p.hay = [p.name, p.variant, "#" + p.number, p.number, s ? s.name : p.set, p.grade, p.match.apiName].join(" ").toLowerCase();
  });

  // ---- header ----
  var T = D.totals;
  var mvp = pockets.slice().sort(function (a, b) { return b.unitCents - a.unitCents; })[0];
  var costRows = D.entries.filter(function (e) { return e.costCents > 0; });
  var gain = costRows.reduce(function (a, e) { return a + e.valueCents - e.costCents; }, 0);
  var setCount = D.sets.length;
  $("subtitle").textContent = "From PriceCharting export " + D.source + " · built " + D.generated;
  $("stats").innerHTML =
    stat("Collection value", money(T.valueCents), "sum of PriceCharting prices") +
    stat("Cards", T.cards.toLocaleString(), T.rows + " entries · " + setCount + " sets") +
    '<div class="stat mvp">' + (mvp.images.length ? '<img src="' + esc(mvp.images[0].thumb) + '" alt="">' : "") +
    '<div><div class="k">Most valuable card</div><div class="v">' + money(mvp.unitCents) + '</div><div class="s">' + esc(mvp.name) +
    (mvp.variant ? " [" + esc(mvp.variant) + "]" : "") + " #" + esc(mvp.number) + " · " + esc(mvp.set.replace(/^Pokemon /, "")) + "</div></div></div>";
  function stat(k, v, s) { return '<div class="stat"><div class="k">' + k + '</div><div class="v">' + v + '</div><div class="s">' + s + "</div></div>"; }

  // ---- controls ----
  var sel = $("setSelect");
  sel.innerHTML = '<option value="__all">All sets (' + setCount + ")</option>" + D.sets.map(function (s) {
    return '<option value="' + esc(s.key) + '">' + esc(s.name) + " (" + s.ownedCount + ")</option>";
  }).join("");
  sel.addEventListener("change", function () { state.set = sel.value; render(); window.scrollTo({ top: 0 }); });
  document.querySelectorAll(".seg.sort button").forEach(function (b) {
    b.addEventListener("click", function () {
      state.sort = b.getAttribute("data-sort");
      document.querySelectorAll(".seg.sort button").forEach(function (x) { x.classList.toggle("on", x === b); });
      render();
    });
  });
  $("search").addEventListener("input", function (e) { state.q = e.target.value.trim().toLowerCase(); render(); });
  $("missingAll").addEventListener("change", function (e) { state.missingAll = e.target.checked; state.missing = {}; render(); });

  // ---- rendering ----
  // Caption strip under a card: line 1 = name (+variant) and price, line 2 = chips and muted details.
  function capHTML(o) {
    var chips = (o.chips || []).filter(Boolean).join("");
    return '<div class="caption"><div class="l1"><span class="n" title="' + esc(o.title || o.name) + '">' + esc(o.name) +
      (o.variant ? ' <span class="var">· ' + esc(o.variant) + "</span>" : "") + "</span>" +
      (o.price != null ? '<span class="v">' + o.price + "</span>" : "") + "</div>" +
      '<div class="l2">' + chips + (o.pc ? '<span class="chip pcchip" title="Photo from PriceCharting (no card-database image)">PC photo</span>' : "") +
      '<span class="d" title="' + esc(o.line2 || "") + '">' + esc(o.line2 || "") + "</span></div></div>";
  }
  var chip = function (text, cls, title) { return '<span class="chip' + (cls ? " " + cls : "") + '"' + (title ? ' title="' + esc(title) + '"' : "") + ">" + text + "</span>"; };
  var gradeChip = function (e) { return e.graded ? chip(esc(e.grade), "graded") : ""; };
  function pocketHTML(p) {
    var cap = capHTML({ name: p.name, variant: p.variant, price: money(p.unitCents), pc: true,
      chips: [gradeChip(p), p.qty > 1 ? chip("×" + p.qty, "qty") : ""],
      line2: "#" + p.number + (p.qty > 1 ? " · " + money(p.valueCents) + " total" : "") });
    var img = imgTag(p.images, { lazy: true, alt: p.name, fbHtml: "<b>" + esc(p.name) + "</b>#" + esc(p.number) + "<br>No image in the card databases yet" });
    return '<div class="pocket' + pcCls(p.images) + '" data-k="' + esc(p.key) + '">' + img +
      cap + "</div>";
  }
  function missingHTML(c) {
    return '<div class="pocket missing">' + (c.thumb ? '<img loading="lazy" src="' + esc(c.thumb) + '" alt="">' : "") +
      capHTML({ name: c.name, line2: "#" + c.number + " · missing" }) + "</div>";
  }
  function pagesHTML(items) {
    var out = "", pg = 0;
    for (var i = 0; i < items.length; i += 9) {
      var chunk = items.slice(i, i + 9);
      while (chunk.length < 9) chunk.push('<div class="pocket empty"></div>');
      out += '<div class="page"><div class="grid">' + chunk.join("") + '</div><span class="page-no">' + (++pg) + "</span></div>";
    }
    return '<div class="pages">' + out + "</div>";
  }
  var bySort = function (a, b) { return state.sort === "value" ? (b.unitCents - a.unitCents) || (a.order - b.order) : (a.order - b.order) || (b.unitCents - a.unitCents); };

  function render() {
    var q = state.q;
    var visible = pockets.filter(function (p) { return !q || p.hay.indexOf(q) >= 0; });
    var html = "";
    if (state.set === "__all" && state.sort === "value") {
      var all = visible.slice().sort(bySort);
      var v = all.reduce(function (a, p) { return a + p.valueCents; }, 0);
      html = all.length ? '<section class="set"><div class="set-head"><h2>Whole collection, most valuable first</h2><span class="meta">' +
        all.length + ' pockets · <span class="val">' + money(v) + "</span></span></div>" + pagesHTML(all.map(pocketHTML)) + "</section>" : "";
    } else {
      D.sets.forEach(function (s) {
        if (state.set !== "__all" && state.set !== s.key) return;
        var mine = visible.filter(function (p) { return p.set === s.key; }).sort(bySort);
        var showMissing = !!s.completeList && (state.missing[s.key] != null ? state.missing[s.key] : state.missingAll);
        if (!mine.length && !(showMissing && !q)) return;
        var ownedSlots = {};
        pockets.forEach(function (p) { if (p.set === s.key && p.slot in s.slotIndex) ownedSlots[p.slot] = 1; });
        var have = Object.keys(ownedSlots).length;
        var val = mine.reduce(function (a, p) { return a + p.valueCents; }, 0);
        var qty = mine.reduce(function (a, p) { return a + p.qty; }, 0);
        var items;
        if (showMissing) {
          // every card in set order; owned ones fill their pocket, the rest are greyed
          var bySlot = {};
          mine.forEach(function (p) { (bySlot[p.slot] = bySlot[p.slot] || []).push(p); });
          items = [];
          s.completeList.forEach(function (c) {
            if (bySlot[c.slot]) { bySlot[c.slot].forEach(function (p) { items.push(pocketHTML(p)); }); delete bySlot[c.slot]; }
            else if (!q || (c.name + " #" + c.number).toLowerCase().indexOf(q) >= 0) items.push(missingHTML(c));
          });
          Object.keys(bySlot).forEach(function (k) { bySlot[k].forEach(function (p) { items.push(pocketHTML(p)); }); });
        } else {
          items = mine.map(pocketHTML);
        }
        var pct = s.completeList ? Math.round(1000 * have / s.completeList.length) / 10 : null;
        html += '<section class="set" id="set-' + esc(s.key) + '"><div class="set-head"><h2>' + esc(s.name) + '</h2><span class="meta">' +
          qty + " card" + (qty === 1 ? "" : "s") + ' · <span class="val">' + money(val) + "</span>" +
          (s.release ? " · released " + esc(s.release.replace(/\//g, "-")) : "") +
          (pct != null ? " · " + have + " / " + s.completeList.length + " unique (" + pct + "%)" : "") + "</span>" +
          '<span class="spacer"></span>' +
          (s.completeList ? '<label><input type="checkbox" data-missing="' + esc(s.key) + '"' + (showMissing ? " checked" : "") + "> Show missing cards</label>" : "") +
          (pct != null ? '<div class="progress"><i style="width:' + pct + '%"></i></div>' : "") +
          "</div>" + pagesHTML(items) + "</section>";
      });
    }
    $("binder").innerHTML = html || '<p class="empty-msg">Nothing matches that search.</p>';
    document.querySelectorAll("[data-missing]").forEach(function (cb) {
      cb.addEventListener("change", function () { state.missing[cb.getAttribute("data-missing")] = cb.checked; render(); });
    });
  }

  // ---- zoom on click ----
  var byKey = {}; pockets.forEach(function (p) { byKey[p.key] = p; });
  $("binder").addEventListener("click", function (ev) {
    var el = ev.target.closest(".pocket[data-k]"); if (!el) return;
    var p = byKey[el.getAttribute("data-k")]; if (!p) return;
    setZoomImg(p.images, null);
    var m = p.match, s = setsByKey[p.set];
    $("zoomInfo").innerHTML = "<h3>" + esc(p.name) + "</h3><div>" + esc(s ? s.name : p.set) + " · #" + esc(p.number) + (p.variant ? " · " + esc(p.variant) : "") + "</div><dl>" +
      "<dt>Grade</dt><dd>" + esc(p.grade) + "</dd>" +
      "<dt>Quantity</dt><dd>" + p.qty + "</dd>" +
      "<dt>Per card</dt><dd>" + money(p.unitCents) + "</dd>" +
      (p.qty > 1 || p.rows.length > 1 ? "<dt>Total</dt><dd>" + money(p.valueCents) + (p.rows.length > 1 ? " (" + p.rows.map(function (r) { return "x" + r.qty + " · " + money(r.valueCents); }).join(", ") + ")" : "") + "</dd>" : "") +
      (p.rows.some(function (r) { return r.notes; }) ? "<dt>Notes</dt><dd>" + esc(p.rows.map(function (r) { return r.notes; }).filter(Boolean).join(", ")) + "</dd>" : "") +
      (p.rows.some(function (r) { return r.folder; }) ? "<dt>Folder</dt><dd>" + esc(p.rows.map(function (r) { return r.folder; }).filter(Boolean).join(", ")) + "</dd>" : "") +
      (m.rarity ? "<dt>Rarity</dt><dd>" + esc(m.rarity) + "</dd>" : "") +
      "<dt>Matched</dt><dd>" + esc(m.source) + " " + esc(m.id) + " · " + Math.round(m.confidence * 100) + "% · " + esc(m.method) + "</dd>" +
      (firstSrc(p.images) === "pc" ? '<dt>Image</dt><dd>PriceCharting photo (no card-database image)' + (p.images[0].page ? ' · <a href="' + esc(p.images[0].page) + '" target="_blank" rel="noopener">product page</a>' : "") + "</dd>" : "") + "</dl>";
    $("zoom").hidden = false;
  });
  $("zoom").addEventListener("click", function () { $("zoom").hidden = true; });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") $("zoom").hidden = true; });

  // ---- unmatched + footer ----
  var un = D.entries.filter(function (e) { return !e.match; });
  if (un.length) {
    $("unmatched").innerHTML = "<h2>Not matched (" + un.length + ")</h2><p>These rows are in the export but weren't found in the Pokémon TCG API or TCGdex yet, usually because the cards are too new.</p>" +
      '<table><thead><tr><th></th><th>Card</th><th>Set</th><th class="r">Qty</th><th class="r">Value</th></tr></thead><tbody>' +
      un.map(function (e) { return '<tr><td class="uimg">' + (e.images && e.images.length ? '<span class="src-pc">' + imgTag(e.images, { lazy: true, alt: e.product }) + "</span>" : "") + "</td><td>" + esc(e.product) + "</td><td>" + esc(e.console.replace(/^Pokemon /, "")) + '</td><td class="r">' + e.qty + '</td><td class="r">' + money(e.valueCents) + "</td></tr>"; }).join("") +
      "</tbody></table>";
  }
  $("foot").textContent = "Values are PriceCharting's prices from the export. Each row's price already covers every copy in it, so per-card price = row price ÷ quantity; nothing is re-priced here. Card images and set lists come from the Pokémon TCG API and TCGdex. " +
    (costRows.length ? "Cost basis is tracked on " + costRows.length + " entries: " + (gain >= 0 ? "+" : "−") + money(Math.abs(gain)) + " against current value." : "");

  render();

  // ---- Pokédex tabs: one 4x4 binder per region, in National Dex order, one face card per species ----
  // Face card = your saved pick if it is still in the collection, otherwise the most valuable per card.
  // Picks are keyed by National Dex number -> entry.key (PriceCharting id + row details from build.py),
  // so they survive reloads, rebuilds, and new exports, and old Kanto picks carry over unchanged.
  var DEX = D.dex || [], REG = D.regions || [];
  var regByKey = {}; REG.forEach(function (r) { regByKey[r.key] = r; });
  var curReg = REG[0];
  var PKEY = "pokemonBinder.kantoPicks.v1"; // name kept so picks saved before the region tabs still load
  var byEntryKey = {}, byPcId = {};
  D.entries.forEach(function (e, i) { byEntryKey[e.key] = i; (byPcId[e.pcId] = byPcId[e.pcId] || []).push(i); });
  var defaults = D.defaultPicks || {};
  var saved = {}, storageOK = true;
  try { saved = JSON.parse(localStorage.getItem(PKEY) || "{}") || {}; } catch (err) { storageOK = false; }
  var has = function (o, k) { return Object.prototype.hasOwnProperty.call(o, k); };
  function rawPick(dex) { return has(saved, dex) ? saved[dex] : defaults[dex]; }
  function resolve(k) {
    var key = rawPick(k.dex);
    if (key) {
      var i = byEntryKey[key];
      if (i == null || k.cards.indexOf(i) < 0) {
        // Row details changed in a new export: fall back to the same PriceCharting product for this species.
        var pc = String(key).split("|")[0];
        i = (byPcId[pc] || []).filter(function (j) { return k.cards.indexOf(j) >= 0; })[0];
      }
      if (i != null && k.cards.indexOf(i) >= 0 && i !== k.cards[0]) return { idx: i, manual: true };
    }
    return { idx: k.cards[0], manual: false }; // no pick, or picked card is gone: most valuable, silently
  }
  function persist() {
    try { localStorage.setItem(PKEY, JSON.stringify(saved)); storageOK = localStorage.getItem(PKEY) !== null; } catch (err) { storageOK = false; }
  }
  function setPick(dex, idx) {
    var k = DEX[dex - 1];
    if (idx == null || idx === k.cards[0]) { if (defaults[dex]) saved[dex] = ""; else delete saved[dex]; }
    else saved[dex] = D.entries[idx].key;
    persist(); refreshDex();
  }
  function effectivePicks() {
    var out = {};
    DEX.forEach(function (k) { if (k.cards.length) { var r = resolve(k); if (r.manual) out[k.dex] = D.entries[r.idx].key; } });
    return out;
  }
  function regionStats(r) {
    var ks = DEX.slice(r.start - 1, r.end), got = 0, val = 0, manual = 0;
    ks.forEach(function (k) { if (k.cards.length) { var x = resolve(k); got++; val += D.entries[x.idx].unitCents; if (x.manual) manual++; } });
    return { n: ks.length, got: got, val: val, manual: manual, pct: Math.round(1000 * got / ks.length) / 10 };
  }
  var PIN = '<svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true"><path fill="currentColor" d="M16 3l5 5-3 1-4 4 1 5-2 2-4-4-5 5-1-1 5-5-4-4 2-2 5 1 4-4z"/></svg>';
  var pad3 = function (n) { return "#" + String(n).padStart(3, "0"); };
  function slotHTML(k, sub) {
    var dexNo = pad3(k.dex), subTag = sub ? chip(esc(sub), "subreg") : "";
    if (!k.cards.length) {
      return '<div class="pocket kslot missing"><img class="art" src="' + esc(k.art) + '" alt="">' +
        capHTML({ name: k.name, chips: [chip(dexNo, "dexno"), subTag], line2: "missing" }) + "</div>";
    }
    var r = resolve(k), e = D.entries[r.idx], m = e.match;
    var img = imgTag(e.images, { alt: e.name, art: k.art });
    var others = k.cards.length - 1;
    return '<div class="pocket kslot' + (r.manual ? " picked" : "") + pcCls(e.images) + '" data-dex="' + k.dex + '">' + img +
      (others ? '<button class="cyc prev" data-cycle="-1" title="Previous card" aria-label="Previous card">‹</button>' +
        '<button class="cyc next" data-cycle="1" title="Next card" aria-label="Next card">›</button>' : "") +
      capHTML({ name: e.name, variant: e.variant, price: money(e.unitCents), pc: true,
        chips: [chip(dexNo, "dexno"), subTag, r.manual ? chip(PIN, "pin", "Your pick (not the most valuable)") : "", gradeChip(e), others ? chip("+" + others, "qty", others + " other card" + (others === 1 ? "" : "s")) : ""],
        line2: e.console.replace(/^Pokemon /, "") + " #" + e.number }) + "</div>";
  }
  function summaryHTML() {
    var all = { got: 0, n: 0, val: 0 };
    var cells = REG.map(function (r) {
      var s = regionStats(r); all.got += s.got; all.n += s.n; all.val += s.val;
      return '<button class="reg' + (r === curReg ? " on" : "") + '" data-region="' + r.key + '" title="' + esc(r.name + " · #" + r.start + "–" + r.end + (r.note ? " · " + r.note : "")) + '">' +
        '<span class="rn">' + esc(r.name) + '</span><span class="rc">' + s.got + " / " + s.n + '</span><span class="bar"><i style="width:' + s.pct + '%"></i></span></button>';
    }).join("");
    return '<div class="regions" role="tablist" aria-label="Region">' + cells +
      '<div class="reg all"><span class="rn">All regions</span><span class="rc">' + all.got + " / " + all.n + '</span><span class="rv">' + money(all.val) + "</span></div></div>";
  }
  function regionHTML(r) {
    var s = regionStats(r), sub = r.sub;
    var slots = DEX.slice(r.start - 1, r.end).map(function (k) { return slotHTML(k, sub && k.dex >= sub.start && k.dex <= sub.end ? sub.name : ""); });
    var pages = "", pg = 0;
    for (var i = 0; i < slots.length; i += 16) {
      var chunk = slots.slice(i, i + 16);
      while (chunk.length < 16) chunk.push('<div class="pocket empty"></div>');
      pages += '<div class="page"><div class="grid g4">' + chunk.join("") + '</div><span class="page-no">' + (++pg) + " · #" + (r.start + i) + "–" + Math.min(r.start + i + 15, r.end) + "</span></div>";
    }
    return summaryHTML() + '<section class="set"><div class="set-head"><h2>' + esc(r.name) + ' Pokédex</h2><span class="meta"><b style="color:var(--ink)">' + s.got +
      " / " + s.n + "</b> collected (" + s.pct + "%) · #" + r.start + "–" + r.end + ' · cards in binder <span class="val">' + money(s.val) + "</span> · " +
      (s.manual ? s.manual + " pinned pick" + (s.manual === 1 ? "" : "s") + ", rest most valuable" : "most valuable card per species") + ", per-card price" +
      (r.note ? ' · <span class="rnote">' + esc(r.note) + "</span>" : "") + "</span>" +
      '<span class="kactions"><button class="btn" data-act="export" title="Download your picks (all regions) as picks.json">Export picks</button>' +
      '<button class="btn" data-act="import" title="Load a picks.json file">Import picks</button>' +
      '<input type="file" id="picksFile" accept=".json,application/json" hidden></span>' +
      (storageOK ? "" : '<div class="warn">This browser is not saving picks for local files. Use Export picks, then drop the file at data/picks.json and rebuild.</div>') +
      '<div class="progress"><i style="width:' + s.pct + '%"></i></div></div><div class="pages">' + pages + "</div></section>";
  }
  var openDex = null, dexBuilt = false;
  function refreshDex() { $("dexView").innerHTML = regionHTML(curReg); dexBuilt = true; if (openDex) openSlot(openDex); }
  function showRegion(key, scroll) {
    curReg = regByKey[key] || REG[0]; refreshDex();
    try { history.replaceState(null, "", curReg === REG[0] ? "#pokedex" : "#pokedex-" + curReg.key); } catch (err) {}
    if (scroll) window.scrollTo({ top: 0 });
  }
  function openSlot(dex) {
    openDex = dex;
    var k = DEX[dex - 1], r = resolve(k), e = D.entries[r.idx];
    setZoomImg(e.images, k.art);
    $("zoomInfo").innerHTML = '<div class="swap"><h3>' + pad3(k.dex) + " " + esc(k.name) + "</h3><div>In binder: " + esc(e.product) + " · " + esc(e.console.replace(/^Pokemon /, "")) +
      (r.manual ? ' <span class="pinned">' + PIN + " your pick</span>" : " (most valuable)") +
      (firstSrc(e.images) === "db" ? "" : firstSrc(e.images) === "pc" ? "<br><small>No card-database image; PriceCharting photo shown.</small>" : "<br><small>No card image yet; official artwork shown.</small>") + "</div>" +
      (r.manual ? '<button class="btn" data-reset="1">Reset to most valuable</button>' : "") +
      '<table class="others"><thead><tr><th>Card</th><th>Set</th><th class="r">Per card</th><th></th></tr></thead><tbody>' +
      k.cards.map(function (i, n) {
        var c = D.entries[i], cur = i === r.idx;
        return "<tr" + (cur ? ' class="pick"' : "") + "><td>" + esc(c.product) + (c.qty > 1 ? " ×" + c.qty : "") + (n === 0 ? ' <small class="mv">most valuable</small>' : "") +
          (c.species.length > 1 ? ' <small class="mv">also ' + c.species.filter(function (d) { return d !== k.dex; }).map(function (d) { return esc(DEX[d - 1].name); }).join(", ") + "</small>" : "") +
          "</td><td>" + esc(c.console.replace(/^Pokemon /, "")) + '</td><td class="r">' + money(c.unitCents) + '</td><td class="r">' +
          (cur ? '<span class="inb">In binder</span>' : '<button class="btn sm" data-use="' + i + '">Use this card</button>') + "</td></tr>";
      }).join("") + "</tbody></table>" +
      '<div class="hint">Picks save in this browser automatically. Click outside to close.</div></div>';
    $("zoom").hidden = false;
  }
  $("zoomInfo").addEventListener("click", function (ev) {
    if (!ev.target.closest(".swap")) return;
    ev.stopPropagation(); // keep the swap panel open
    var u = ev.target.closest("[data-use]"), rs = ev.target.closest("[data-reset]");
    if (u) setPick(openDex, +u.getAttribute("data-use"));
    else if (rs) setPick(openDex, null);
  });
  $("zoom").addEventListener("click", function () { openDex = null; });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") openDex = null; });
  $("dexView").addEventListener("click", function (ev) {
    var reg = ev.target.closest("[data-region]");
    if (reg) { showRegion(reg.getAttribute("data-region"), false); return; }
    var act = ev.target.closest("[data-act]");
    if (act) {
      if (act.getAttribute("data-act") === "export") {
        var blob = new Blob([JSON.stringify({ version: 1, exported: new Date().toISOString(), source: D.source, picks: effectivePicks() }, null, 2) + "\n"], { type: "application/json" });
        var a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "picks.json";
        document.body.appendChild(a); a.click(); setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
      } else $("picksFile").click();
      return;
    }
    var el = ev.target.closest(".kslot[data-dex]"); if (!el) return;
    var dex = +el.getAttribute("data-dex"), cyc = ev.target.closest("[data-cycle]");
    if (cyc) {
      var k = DEX[dex - 1], pos = k.cards.indexOf(resolve(k).idx), n = k.cards.length;
      setPick(dex, k.cards[(pos + +cyc.getAttribute("data-cycle") + n) % n]);
      return;
    }
    openSlot(dex);
  });
  $("dexView").addEventListener("change", function (ev) {
    if (ev.target.id !== "picksFile" || !ev.target.files[0]) return;
    var fr = new FileReader();
    fr.onload = function () {
      try {
        var j = JSON.parse(fr.result), p = (j && j.picks) || j || {};
        var next = {};
        Object.keys(defaults).forEach(function (d) { next[d] = ""; });
        Object.keys(p).forEach(function (d) { if (typeof p[d] === "string" && +d >= 1 && +d <= DEX.length) next[d] = p[d]; });
        saved = next; persist(); refreshDex();
        alert("Imported " + Object.keys(p).length + " pick(s).");
      } catch (err) { alert("That file is not a valid picks.json: " + err.message); }
    };
    fr.readAsText(ev.target.files[0]);
  });
  // ---- tabs: each tab owns one or more <main> views; feature scripts register more through VB.registerTab ----
  var VIEWS = { sets: ["binder", "unmatched"], dex: ["dexView"] }, EXT = {};
  function showTab(tab, regionKey, scroll) {
    if (!VIEWS[tab]) tab = "sets";
    document.querySelectorAll(".tabs button").forEach(function (x) { x.classList.toggle("on", x.getAttribute("data-tab") === tab); });
    Object.keys(VIEWS).forEach(function (t) { VIEWS[t].forEach(function (id) { if ($(id)) $(id).hidden = t !== tab; }); });
    document.querySelectorAll(".sets-only").forEach(function (x) { x.style.display = tab === "sets" ? "" : "none"; });
    if (tab === "dex") showRegion(regionKey || curReg.key, false);
    else if (EXT[tab]) { EXT[tab].show(); try { history.replaceState(null, "", "#" + EXT[tab].hash); } catch (err) {} }
    else try { history.replaceState(null, "", "#"); } catch (err) {}
    if (scroll) window.scrollTo({ top: 0 });
  }
  document.querySelector(".tabs").addEventListener("click", function (ev) {
    var b = ev.target.closest("button[data-tab]"); if (b) showTab(b.getAttribute("data-tab"), null, true);
  });

  // Shared helpers for the feature scripts (binders.js, ...), which load after this file.
  window.VB = {
    capHTML: capHTML, chip: chip, gradeChip: gradeChip,
    D: D, $: $, money: money, esc: esc, numKey: numKey, imgTag: imgTag, pcCls: pcCls, firstSrc: firstSrc, setZoomImg: setZoomImg,
    DEX: DEX, byEntryKey: byEntryKey, byPcId: byPcId, setsByKey: setsByKey, showTab: showTab,
    registerTab: function (tab, viewId, show, hash) { VIEWS[tab] = [viewId]; EXT[tab] = { show: show, hash: hash || tab }; }
  };

  // #pokedex = Kanto (kept from the Kanto-only version), #pokedex-johto, ...; other tabs use their own hash (#binders, ...).
  // Runs on DOMContentLoaded, i.e. after the feature scripts below this one have registered their tabs.
  function route() {
    var hm = /^#pokedex(?:-([a-z]+))?$/.exec(location.hash);
    if (hm) { showTab("dex", hm[1] && regByKey[hm[1]] ? hm[1] : REG[0].key, false); return; }
    var h = location.hash.slice(1);
    Object.keys(EXT).forEach(function (t) { if (EXT[t].hash === h) showTab(t, null, false); });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", route); else setTimeout(route, 0);
})();
