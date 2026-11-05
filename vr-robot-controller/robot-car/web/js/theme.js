/*
  theme.js - light / dark mode for every page.

  Loaded as a plain script in each page's <head>, BEFORE the page draws, so
  there's no flash of the wrong colours. It sets <html data-theme="dark|light">,
  which css/site.css uses to pick its colours.

  The choice is saved per device (in this browser's localStorage), so the
  laptop and the headset can differ:
      "auto"   follow the device's own light/dark setting (the default)
      "light" / "dark"   always that
  Any element with class "theme-toggle" becomes a sun / moon button.
*/
(function () {
  var KEY = "page-theme";
  var media = window.matchMedia ? window.matchMedia("(prefers-color-scheme: light)") : null;

  /** The saved choice: "auto", "light" or "dark". */
  function choice() {
    try { return localStorage.getItem(KEY) || "auto"; } catch (e) { return "auto"; }
  }

  /** The theme actually in use: "light" or "dark". */
  function current() {
    var c = choice();
    if (c === "light" || c === "dark") return c;
    return media && media.matches ? "light" : "dark";
  }

  /** Apply the current theme to the page and refresh the toggle buttons. */
  function apply() {
    document.documentElement.dataset.theme = current();
    var buttons = document.querySelectorAll(".theme-toggle");
    for (var i = 0; i < buttons.length; i++) drawButton(buttons[i]);
    document.dispatchEvent(new CustomEvent("themechange", { detail: current() }));
  }

  /** Save a choice ("auto", "light" or "dark") and apply it. */
  function set(c) {
    try { localStorage.setItem(KEY, c); } catch (e) { /* private mode: just apply */ }
    apply();
  }

  // Sun (switch to light) or moon (switch to dark), drawn inline so there
  // are no image files to load.
  var SUN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
  var MOON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>';

  /** Show the icon for what a click will switch TO. */
  function drawButton(b) {
    var dark = current() === "dark";
    b.innerHTML = dark ? SUN : MOON;
    b.setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode");
    b.title = b.getAttribute("aria-label");
  }

  // Follow the device's setting live while the choice is "auto".
  if (media && media.addEventListener)
    media.addEventListener("change", function () { if (choice() === "auto") apply(); });

  // Clicking a toggle picks the opposite of what's showing now (and stops
  // following the device until "auto" is chosen again on the settings page).
  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest(".theme-toggle");
    if (b) set(current() === "dark" ? "light" : "dark");
  });
  document.addEventListener("DOMContentLoaded", apply);

  window.Theme = { choice: choice, current: current, set: set, apply: apply };
  document.documentElement.dataset.theme = current();   // right away, before drawing
})();
