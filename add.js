// Add cards: search TCGdex, pick condition and quantity, save to data/collection.csv through scripts/serve.py.
// Also adds an edit / remove block to the card zoom panel. Needs the local server; on a plain file:// page it says so.
// Saved changes show up (and get priced) after the next `python3 scripts/build.py`.
(function () {
  "use strict";
  var VB = window.VB; if (!VB) return; // no binder-data.js yet
  var $ = VB.$, esc = VB.esc;
  var CONDS = [["NM", "Near Mint"], ["LP", "Lightly Played"], ["MP", "Moderately Played"], ["HP", "Heavily Played"], ["DMG", "Damaged"]];
  var view = $("addView"), up = false, drawn = null, changes = 0, shown = [];

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
    return changes ? '<p class="add-note">' + changes + " change" + (changes > 1 ? "s" : "") + " saved to your collection file. Run <code>python3 scripts/build.py</code>, then reload this page to see " +
      "and price them.</p>" : "";
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
      '<div class="add-ctl"><select aria-label="Condition">' + condOptions("NM") + '</select><input type="number" aria-label="Quantity" min="1" max="999" value="1">' +
      '<input type="text" aria-label="Notes" placeholder="Notes (optional)" maxlength="200"><button type="button" data-add>Add</button></div>' +
      '<div class="add-msg" role="status"></div></div></div>';
  }
  function added(card, c, qty) { changes++; $("addBanner").innerHTML = banner(); card.querySelector(".add-msg").textContent = "Added ×" + qty + " " + c + "."; }

  if (view) view.addEventListener("click", function (ev) {
    var b = ev.target.closest("button[data-add]"); if (!b) return;
    var card = b.closest(".add-card"), q = card.querySelectorAll(".add-ctl select, .add-ctl input"), msg = card.querySelector(".add-msg");
    b.disabled = true;
    api("POST", "/api/collection/entries", { cardId: card.getAttribute("data-id"), condition: q[0].value, qty: parseInt(q[1].value, 10), notes: q[2].value })
      .then(function (r) { added(card, r.condition, r.qty); })
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
        changes++; if ($("addBanner")) $("addBanner").innerHTML = banner();
        row.innerHTML = "<span>" + (rm ? "Removed." : "Saved.") + " Rebuild (<code>python3 scripts/build.py</code>) and reload to update the binder.</span>";
      }).catch(function (e) { msg.textContent = e.message; });
    });
  }

  VB.manage = { decorate: decorate };
  VB.registerTab("add", "addView", show, "add");
  api("GET", "/api/health").then(function () { up = true; }).catch(function () {}).then(function () { if (!view.hidden) show(); });
})();
