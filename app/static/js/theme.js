// Loaded in <head> before the page paints, so dark mode never flashes white.
(function () {
  var saved = null;
  try { saved = localStorage.getItem("wt-theme"); } catch (e) { /* storage blocked */ }
  var dark = saved ? saved === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.setAttribute("data-bs-theme", dark ? "dark" : "light");
})();
