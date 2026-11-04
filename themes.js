// Theme switcher. The inline script in index.html applies the saved theme before first paint;
// this file builds the dropdown and saves changes. localStorage can fail (Safari on file://), so
// every access is guarded and the theme then just lasts until the page is closed.
(function () {
  var THEMES = [
    ["Looks", [
      ["original", "Original"],
      ["auto", "Auto (system light/dark)"],
      ["classic", "Classic binder"],
      ["dark", "Dark mode"],
      ["pokedex", "Pokédex red"],
      ["holo", "Holo foil shimmer"],
      ["gameboy", "Retro Game Boy"],
      ["galaxy", "Night Sky / Galaxy"],
      ["trainer", "Trainer Card poster"],
      ["contrast", "High contrast"],
    ]],
    ["Pokémon types", [
      ["type-fire", "Fire"], ["type-water", "Water"], ["type-grass", "Grass"],
      ["type-electric", "Electric"], ["type-psychic", "Psychic"], ["type-ice", "Ice"],
      ["type-dragon", "Dragon"], ["type-ghost", "Ghost"], ["type-dark", "Dark"],
      ["type-fighting", "Fighting"],
    ]],
  ];
  var KEY = "vb-theme";
  var ids = {};
  THEMES.forEach(function (g) { g[1].forEach(function (t) { ids[t[0]] = 1; }); });
  var mq = window.matchMedia ? window.matchMedia("(prefers-color-scheme: light)") : null;

  function resolve(choice) {
    if (choice === "auto") return mq && mq.matches ? "classic" : "dark";
    return choice;
  }
  function apply(choice) {
    if (!ids[choice]) choice = "original";
    var t = resolve(choice);
    var html = document.documentElement;
    if (t === "original") html.removeAttribute("data-theme"); else html.setAttribute("data-theme", t);
    html.setAttribute("data-theme-choice", choice);
    window.dispatchEvent(new CustomEvent("themechange", { detail: { theme: t, choice: choice } }));
  }
  function saved() {
    try { return localStorage.getItem(KEY) || "original"; } catch (e) { return "original"; }
  }

  var current = document.documentElement.getAttribute("data-theme-choice") || saved();
  apply(current);
  if (mq) {
    var onChange = function () { if (current === "auto") apply("auto"); };
    if (mq.addEventListener) mq.addEventListener("change", onChange); else if (mq.addListener) mq.addListener(onChange);
  }

  var host = document.querySelector(".cover-inner");
  if (!host) return;
  var label = document.createElement("label");
  label.className = "theme-pick";
  label.innerHTML = "<span>Theme</span>";
  var sel = document.createElement("select");
  sel.id = "themeSelect";
  sel.setAttribute("aria-label", "Theme");
  THEMES.forEach(function (g) {
    var og = document.createElement("optgroup");
    og.label = g[0];
    g[1].forEach(function (t) {
      var o = document.createElement("option");
      o.value = t[0]; o.textContent = t[1];
      og.appendChild(o);
    });
    sel.appendChild(og);
  });
  sel.value = ids[current] ? current : "original";
  sel.addEventListener("change", function () {
    current = sel.value;
    try { localStorage.setItem(KEY, current); } catch (e) { /* storage blocked: keep it for this visit */ }
    apply(current);
  });
  label.appendChild(sel);
  host.insertBefore(label, host.firstChild);
})();
