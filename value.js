// Value tab: collection value over time from the snapshots build.py saves in data/history/.
// Every price here is PriceCharting's price from one of your exports; nothing is estimated.
(function () {
  "use strict";
  var VB = window.VB; if (!VB) return;
  var D = VB.D, $ = VB.$, esc = VB.esc, money = VB.money, H = D.history;
  var signed = function (c) { return (c > 0 ? "+" : c < 0 ? "−" : "±") + money(Math.abs(c)); };
  var pct = function (now, was) { if (!was) return now ? "new" : "0%"; var p = 100 * (now - was) / was; return (p > 0 ? "+" : p < 0 ? "−" : "") + Math.abs(p).toFixed(Math.abs(p) < 10 ? 1 : 0) + "%"; };
  var cls = function (c) { return c > 0 ? "up" : c < 0 ? "down" : ""; };
  var fmtDate = function (d) { var t = new Date(d + "T12:00:00"); return isNaN(t) ? d : t.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }); };

  // Inline SVG line chart (no libraries). pts = [{date, y}], fmt formats y values.
  function chart(pts, fmt, label) {
    var W = 640, Hh = 240, L = 62, R = 20, T = 18, B = 36;
    var ts = pts.map(function (p) { return Date.parse(p.date + "T12:00:00"); });
    var t0 = ts[0], t1 = ts[ts.length - 1], span = t1 - t0 || 1;
    var ys = pts.map(function (p) { return p.y; }), lo = Math.min.apply(null, ys), hi = Math.max.apply(null, ys);
    if (hi === lo) { hi += Math.max(1, hi * 0.05); lo = Math.max(0, lo - Math.max(1, lo * 0.05)); }
    var padY = (hi - lo) * 0.1; lo = Math.max(0, lo - padY); hi += padY;
    var X = function (t) { return pts.length === 1 ? L + (W - L - R) / 2 : L + (W - L - R) * (t - t0) / span; };
    var Y = function (y) { return T + (Hh - T - B) * (1 - (y - lo) / (hi - lo)); };
    var grid = "", i;
    for (i = 0; i <= 4; i++) {
      var gy = lo + (hi - lo) * i / 4;
      grid += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + Y(gy).toFixed(1) + '" y2="' + Y(gy).toFixed(1) + '" class="gl"/>' +
        '<text x="' + (L - 8) + '" y="' + (Y(gy) + 4).toFixed(1) + '" class="ya">' + esc(fmt(gy)) + "</text>";
    }
    var step = Math.max(1, Math.ceil(pts.length / 8)), xl = "";
    pts.forEach(function (p, j) { if (j % step === 0 || j === pts.length - 1) xl += '<text x="' + X(ts[j]).toFixed(1) + '" y="' + (Hh - 12) + '" class="xa">' + esc(fmtDate(p.date)) + "</text>"; });
    var path = pts.map(function (p, j) { return (j ? "L" : "M") + X(ts[j]).toFixed(1) + " " + Y(p.y).toFixed(1); }).join(" ");
    var area = pts.length > 1 ? '<path class="area" d="' + path + " L" + X(t1).toFixed(1) + " " + (Hh - B) + " L" + X(t0).toFixed(1) + " " + (Hh - B) + ' Z"/>' : "";
    var dots = pts.map(function (p, j) { return '<circle cx="' + X(ts[j]).toFixed(1) + '" cy="' + Y(p.y).toFixed(1) + '" r="4"><title>' + esc(fmtDate(p.date) + ": " + fmt(p.y)) + "</title></circle>"; }).join("");
    return '<svg class="vchart" viewBox="0 0 ' + W + " " + Hh + '" role="img" aria-label="' + esc(label) + '">' + grid + area + '<path class="line" d="' + path + '"/>' + dots + xl + "</svg>";
  }

  // Pair this build's rows with the previous snapshot's by stable row key; rows whose details changed
  // between exports are paired by PriceCharting id + grade so they don't show up as removed + new.
  function diff() {
    var prev = H.prev.items, now = {}, out = { changed: [], added: [], removed: [] };
    D.entries.forEach(function (e) { now[e.key] = { u: e.unitCents, v: e.valueCents, q: e.qty, pc: e.pcId, g: e.grade, n: e.product, s: e.console, e: e }; });
    var lp = Object.keys(prev).filter(function (k) { return !now[k]; }), ln = Object.keys(now).filter(function (k) { return !prev[k]; });
    var pairs = Object.keys(now).filter(function (k) { return prev[k]; }).map(function (k) { return [prev[k], now[k]]; });
    var pool = {};
    lp.forEach(function (k) { var id = prev[k].pc + "|" + prev[k].g; (pool[id] = pool[id] || []).push(prev[k]); });
    ln.forEach(function (k) {
      var x = now[k], id = x.pc + "|" + x.g;
      if (pool[id] && pool[id].length) pairs.push([pool[id].shift(), x]); else out.added.push(x);
    });
    Object.keys(pool).forEach(function (id) { out.removed = out.removed.concat(pool[id]); });
    out.changed = pairs.map(function (p) { return { was: p[0], now: p[1], d: p[1].u - p[0].u }; }).filter(function (c) { return c.d !== 0; });
    return out;
  }
  function thumb(x) {
    var e = x.e;
    return e && e.images && e.images[0] ? '<img src="' + esc(e.images[0].thumb) + '" alt="" loading="lazy">' : "";
  }
  function moverRows(list) {
    if (!list.length) return '<tr><td colspan="5" class="none">None.</td></tr>';
    return list.map(function (c) {
      return '<tr><td class="th">' + thumb(c.now) + "</td><td>" + esc(c.now.n) + '<div class="sub">' + esc(c.now.s.replace(/^Pokemon /, "")) + (c.now.g !== "Raw" ? " · " + esc(c.now.g) : "") + "</div></td>" +
        '<td class="r">' + money(c.was.u) + " → " + money(c.now.u) + '</td><td class="r ' + cls(c.d) + '">' + signed(c.d) + '</td><td class="r ' + cls(c.d) + '">' + pct(c.now.u, c.was.u) + "</td></tr>";
    }).join("");
  }
  function listRows(list, showThumb) {
    if (!list.length) return '<tr><td colspan="4" class="none">None.</td></tr>';
    return list.slice().sort(function (a, b) { return b.v - a.v; }).map(function (x) {
      return '<tr><td class="th">' + (showThumb ? thumb(x) : "") + "</td><td>" + esc(x.n) + '<div class="sub">' + esc(String(x.s).replace(/^Pokemon /, "")) + (x.g && x.g !== "Raw" ? " · " + esc(x.g) : "") + "</div></td>" +
        '<td class="r">' + (x.q > 1 ? "×" + x.q : "") + '</td><td class="r">' + money(x.v) + "</td></tr>";
    }).join("");
  }
  function render() {
    var v = $("valueView");
    if (!H || !H.series || !H.series.length) {
      v.innerHTML = '<div class="bempty"><h2>Value over time</h2><p>This build didn\'t save a value snapshot (it was run with <code>--no-history</code>). Run <code>python3 scripts/build.py</code> to start tracking.</p></div>';
      return;
    }
    var S = H.series, last = S[S.length - 1], curIdx = S.map(function (x) { return x.date; }).indexOf(H.current);
    var cur = S[curIdx], prevS = curIdx > 0 ? S[curIdx - 1] : null, first = S[0];
    var stat = function (k, val, sub, c) { return '<div class="stat"><div class="k">' + k + '</div><div class="v ' + (c || "") + '">' + val + '</div><div class="s">' + sub + "</div></div>"; };
    var head = '<div class="vstats">' +
      stat("Value on " + esc(fmtDate(cur.date)), money(cur.totalCents), cur.cards + " cards · " + cur.rows + " rows") +
      (prevS ? stat("Since " + esc(fmtDate(prevS.date)), signed(cur.totalCents - prevS.totalCents), pct(cur.totalCents, prevS.totalCents) + " · cards " + (cur.cards - prevS.cards >= 0 ? "+" : "−") + Math.abs(cur.cards - prevS.cards), cls(cur.totalCents - prevS.totalCents)) : "") +
      (S.length > 2 ? stat("Since " + esc(fmtDate(first.date)), signed(cur.totalCents - first.totalCents), pct(cur.totalCents, first.totalCents) + " · first snapshot", cls(cur.totalCents - first.totalCents)) : "") +
      stat("Snapshots", S.length, S.length > 1 ? esc(fmtDate(first.date)) + " – " + esc(fmtDate(last.date)) : "one so far") + "</div>";
    var html = '<section class="set"><div class="set-head"><h2>Value over time</h2><span class="meta">One snapshot per build day, saved in <code>data/history/' + esc(H.folder) + "/</code>. Prices are PriceCharting's from each export.</span></div>" + head;
    if (curIdx !== S.length - 1) html += '<div class="warn">This build was filed under ' + esc(cur.date) + ", but newer snapshots exist; changes are shown against " + (prevS ? esc(prevS.date) : "nothing") + ".</div>";
    html += '<div class="vcharts"><div class="vbox"><h3>Total value</h3>' + chart(S.map(function (x) { return { date: x.date, y: x.totalCents }; }), function (c) { return "$" + Math.round(c / 100).toLocaleString("en-US"); }, "Total value over time") + "</div>" +
      '<div class="vbox"><h3>Card count</h3>' + chart(S.map(function (x) { return { date: x.date, y: x.cards }; }), function (n) { return Math.round(n).toLocaleString("en-US"); }, "Card count over time") + "</div></div>";
    if (S.length === 1 || !H.prev) {
      html += '<div class="vnote"><b>This is your first snapshot.</b> Rebuild after your next PriceCharting export to see how your collection\'s value changed, your biggest gainers and losers, and which cards were added or removed. Rebuilding on the same day replaces that day\'s snapshot.</div>';
    } else {
      var d = diff();
      var up = d.changed.filter(function (c) { return c.d > 0; }).sort(function (a, b) { return b.d - a.d; }).slice(0, 10);
      var down = d.changed.filter(function (c) { return c.d < 0; }).sort(function (a, b) { return a.d - b.d; }).slice(0, 10);
      var unchanged = D.entries.length - d.added.length - d.changed.length;
      html += '<p class="vsub">Changes per card since ' + esc(fmtDate(H.prev.date)) + ": " + d.changed.length + " price change" + (d.changed.length === 1 ? "" : "s") + ", " + unchanged + " unchanged, " +
        d.added.length + " new, " + d.removed.length + " removed. Per-card price = row price ÷ quantity.</p>" +
        '<div class="vtables"><div class="vbox"><h3>Biggest gainers</h3><table class="vt"><thead><tr><th></th><th>Card</th><th class="r">Per card</th><th class="r">$</th><th class="r">%</th></tr></thead><tbody>' + moverRows(up) + "</tbody></table></div>" +
        '<div class="vbox"><h3>Biggest losers</h3><table class="vt"><thead><tr><th></th><th>Card</th><th class="r">Per card</th><th class="r">$</th><th class="r">%</th></tr></thead><tbody>' + moverRows(down) + "</tbody></table></div>" +
        '<div class="vbox"><h3>New cards (' + d.added.length + ')</h3><table class="vt"><thead><tr><th></th><th>Card</th><th class="r">Qty</th><th class="r">Value</th></tr></thead><tbody>' + listRows(d.added, true) + "</tbody></table></div>" +
        '<div class="vbox"><h3>Removed cards (' + d.removed.length + ')</h3><table class="vt"><thead><tr><th></th><th>Card</th><th class="r">Qty</th><th class="r">Value then</th></tr></thead><tbody>' + listRows(d.removed, false) + "</tbody></table></div></div>";
    }
    html += '<div class="vbox"><h3>Snapshots</h3><table class="vt snaps"><thead><tr><th>Date</th><th class="r">Value</th><th class="r">Change</th><th class="r">Cards</th><th class="r">Rows</th></tr></thead><tbody>' +
      S.slice().reverse().map(function (x, j, arr) {
        var p = arr[j + 1];
        return "<tr" + (x.date === H.current ? ' class="cur"' : "") + "><td>" + esc(fmtDate(x.date)) + (x.date === H.current ? " (this build)" : "") + '</td><td class="r">' + money(x.totalCents) + '</td><td class="r ' + (p ? cls(x.totalCents - p.totalCents) : "") + '">' + (p ? signed(x.totalCents - p.totalCents) + " (" + pct(x.totalCents, p.totalCents) + ")" : "—") +
          '</td><td class="r">' + x.cards + '</td><td class="r">' + x.rows + "</td></tr>";
      }).join("") + "</tbody></table></div></section>";
    v.innerHTML = html;
  }
  VB.registerTab("value", "valueView", render, "value");
})();
