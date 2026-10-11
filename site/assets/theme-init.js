/* Apply a remembered light/dark choice before the first paint. */
(function () {
  try {
    var theme = localStorage.getItem('we-solve-theme');
    if (theme === 'dark' || theme === 'light') document.documentElement.dataset.theme = theme;
  } catch (_) { /* Storage may be disabled; the system preference applies. */ }
}());
