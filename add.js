// Add cards: search TCGdex, pick printing, condition and quantity, save to data/collection.csv through scripts/serve.py.
// Also adds an edit / remove block to the card zoom panel. Needs the local server; on a plain file:// page it says so.
// The server prices and rebuilds the page data after each change; the banner follows that build, then offers a reload.
(function () {
  "use strict";
  var VB = window.VB; if (!VB) return; // no binder-data.js yet
  var $ = VB.$, esc = VB.esc;
  var CONDS = [["NM", "Near Mint"], ["LP", "Lightly Played"], ["MP", "Moderately Played"], ["HP", "Heavily Played"], ["DMG", "Damaged"]];
  var view = $("addView"), up = false, drawn = null, changes = 0, shown = [], build = null, timer = null;

  function api(method, path, body) {
    return fetch(path, { method: method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined })
      .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || "request failed"); return j; }); });
  }
  function condOptions(sel) {
    return (sel ? "" : '<option value="" selected>?</option>') + CONDS.map(function (c) {
      return '<option value="' + c[0] + '"' + (c[0] === sel ? " selected" : "") + ">" + c[0] + " · " + c[1] + "</option>";
    }).join("");
  }
  function banner() {
    if (!changes) return "";
    var busy = !build || build.state === "running", done = !busy && build.ok;
    return '<p class="add-note" role="status">' + changes + " change" + (changes > 1 ? "s" : "") + " saved to your collection file. " +
      (busy ? "Pricing them and updating your pages…" :
        !done ? "Updating your pages failed (" + esc(build.message) + "); run <code>python3 scripts/build.py</code> to see why." :
        "Your pages are up to date." + (build.pending ? " " + build.pending + " card" + (build.pending > 1 ? "s show" : " shows") +
          " “price pending”: the price service's limit or an outage stopped the lookup, and the next add or rebuild retries it." : "")) +
      (done ? ' <button type="button" class="link" id="reload">Reload to see it</button>' : "") + "</p>";
  }
  function changed() {  // a change was saved: show the banner and follow the rebuild the server started
    changes++; build = null; clearTimeout(timer); track();
  }
  function track() {
    if ($("addBanner")) $("addBanner").innerHTML = banner();
    api("GET", "/api/build/status").then(function (s) {
      build = s;
      if ($("addBanner")) $("addBanner").innerHTML = banner();
      if (s.state === "running") timer = setTimeout(track, 1500);
    }).catch(function () { timer = setTimeout(track, 3000); });
  }
  function show() { if (drawn !== up) shell(); }  // keep the search results when you come back to the tab
  function shell() {
    drawn = up;
    view.innerHTML = '<section class="add"><h2>Add cards</h2>' +
      (up ? '<form id="addForm" class="add-form"><label>Card name<input name="q" required minlength="2" placeholder="Pikachu" autocomplete="off"></label>' +
        '<label>Set (optional)<input name="set" placeholder="Base Set" autocomplete="off"></label>' +
        '<label>Number (optional)<input name="number" placeholder="58" autocomplete="off"></label><button type="submit">Search</button></form>' +
        '<div id="addBanner">' + banner() + '</div><div id="addStatus" class="add-status"></div><div id="addResults" class="add-grid"></div>'
        : '<div class="empty-msg"><p>Adding cards needs the local server. Run <code>python3 scripts/serve.py</code> and open <code>http://127.0.0.1:8123</code>.</p></div>') +
      "</section>";
    if (up) $("addForm").addEventListener("submit", function (ev) { ev.preventDefault(); search(0); });
  }
  function search(offset) {
    var f = $("addForm"), qs = ["q", "set", "number"].map(function (k) { return k + "=" + encodeURIComponent(f.elements[k].value); }).join("&");
    if (!offset) { shown = []; $("addResults").innerHTML = ""; }
    $("addStatus").textContent = "Searching…";
    api("GET", "/api/catalog/search?" + qs + "&offset=" + offset).then(function (out) {
      shown = shown.concat(out.results);
      $("addResults").insertAdjacentHTML("beforeend", out.results.map(resultHTML).join(""));
      $("addStatus").innerHTML = !out.total ? "No cards found." : "Showing " + shown.length + " of " + out.total + (shown.length < out.total ?
        ' · add a set or number to narrow it, or <button type="button" class="link" id="more">show more</button>' : "");
      if ($("more")) $("more").addEventListener("click", function () { search(shown.length); });
    }).catch(function (e) { $("addStatus").textContent = e.message; });
  }
  function resultHTML(c) {
    return '<div class="add-card" data-id="' + esc(c.id) + '">' +
      (c.image ? '<img loading="lazy" src="' + esc(c.image) + '" alt="' + esc(c.name) + '">' : '<div class="noimg">No image</div>') +
      "<div><h3>" + esc(c.name) + "</h3><div class=\"meta\">" + esc(c.set) + " · #" + esc(c.number) + (c.rarity ? " · " + esc(c.rarity) : "") + "</div>" +
      '<div class="meta">' + (c.tcgplayerId ? "TCGplayer ID " + esc(c.tcgplayerId) : "No TCGplayer ID in TCGdex yet; the build will look for one") + "</div>" +
      '<div class="add-ctl"><select aria-label="Printing" data-f="printing">' + c.printings.map(function (p) {
        return '<option value="' + esc(p.key) + '">' + esc(p.label) + "</option>"; }).join("") + '</select>' +
      '<select aria-label="Condition" data-f="condition">' + condOptions("NM") + '</select><input type="number" aria-label="Quantity" data-f="qty" min="1" max="999" value="1">' +
      '<input type="text" aria-label="Notes" data-f="notes" placeholder="Notes (optional)" maxlength="200"><button type="button" data-add>Add</button></div>' +
      '<div class="add-msg" role="status"></div></div></div>';
  }
  function added(card, r) { changed(); card.querySelector(".add-msg").textContent = "Added ×" + r.qty + " " + r.condition + " · " + r.printing + "."; }

  if (view) view.addEventListener("click", function (ev) {
    if (ev.target.id === "reload") return location.reload();
    var b = ev.target.closest("button[data-add]"); if (!b) return;
    var card = b.closest(".add-card"), f = function (n) { return card.querySelector('[data-f="' + n + '"]').value; }, msg = card.querySelector(".add-msg");
    b.disabled = true;
    api("POST", "/api/collection/entries", { cardId: card.getAttribute("data-id"), printing: f("printing"), condition: f("condition"), qty: parseInt(f("qty"), 10), notes: f("notes") })
      .then(function (r) { added(card, r); })
      .catch(function (e) { msg.textContent = e.message; })
      .then(function () { b.disabled = false; });
  });

  // ---- edit / remove, in the card zoom panel (the rows of the clicked card) ----
  function editHTML(e) {
    var label = "×" + e.qty + (e.folder ? " · " + esc(e.folder) : "") + (e.notes ? " · " + esc(e.notes) : "");
    return '<div class="edit-row" data-key="' + esc(e.key) + '"><span>' + label + "</span>" +
      (e.graded ? "<i>graded</i>" : '<select aria-label="Condition">' + condOptions((e.price || {}).cond) + "</select>") +
      '<input type="number" aria-label="Quantity" min="1" max="999" value="' + e.qty + '"><button type="button" data-save>Save</button>' +
      '<button type="button" data-remove class="danger">Remove</button><span class="edit-msg" role="status"></span></div>';
  }
  function decorate(panel, rows) {
    if (!up) return;
    panel.insertAdjacentHTML("beforeend", '<div class="edit"><h4>Edit your collection</h4>' + rows.map(editHTML).join("") + "</div>");
    var box = panel.lastElementChild;
    box.addEventListener("click", function (ev) {
      ev.stopPropagation(); // the zoom panel closes on any click that reaches it
      var row = ev.target.closest(".edit-row"), save = ev.target.closest("[data-save]"), rm = ev.target.closest("[data-remove]");
      if (!row || !(save || rm)) return;
      var msg = row.querySelector(".edit-msg"), key = encodeURIComponent(row.getAttribute("data-key")), sel = row.querySelector("select");
      var req = rm ? (confirm("Remove this row from your collection file?") ? api("DELETE", "/api/collection/entries/" + key) : null)
        : api("PATCH", "/api/collection/entries/" + key, { qty: parseInt(row.querySelector("input").value, 10), condition: sel && sel.value ? sel.value : undefined });
      if (!req) return;
      req.then(function () {
        changed();
        row.innerHTML = "<span>" + (rm ? "Removed." : "Saved.") + " The page data is updating; reload in a moment to see it.</span>";
      }).catch(function (e) { msg.textContent = e.message; });
    });
  }

  VB.manage = { decorate: decorate };
  VB.registerTab("add", "addView", show, "add");
  api("GET", "/api/health").then(function () { up = true; }).catch(function () {}).then(function () { if (!view.hidden) show(); });
})();
