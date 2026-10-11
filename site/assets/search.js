/* Pagefind is loaded only on the search route and requests its local index on demand. */
(function () {
  'use strict';
  var container = document.getElementById('search');
  if (!container) return;
  var status = document.getElementById(container.dataset.searchStatus);
  if (!window.PagefindUI) {
    if (status) status.textContent = 'Search could not load. Browse the discipline catalogues below.';
    return;
  }
  try {
    var search = new window.PagefindUI({
      element: '#search',
      bundlePath: container.dataset.pagefindBase,
      showSubResults: true,
      showImages: false,
      pageSize: 15,
      resetStyles: false,
      autofocus: true,
      translations: { placeholder: 'Search problems, contributions, and reviews' },
      showEmptyFilters: false
    });
    if (status) status.textContent = 'Use the filters to narrow your results.';
    var query = new URLSearchParams(window.location.search).get('q');
    if (query) search.triggerSearch(query);
    var formInput = container.querySelector('input[type="text"], input[type="search"]');
    if (formInput) formInput.addEventListener('input', function () {
      var current = new URL(window.location.href);
      if (formInput.value) current.searchParams.set('q', formInput.value);
      else current.searchParams.delete('q');
      window.history.replaceState(null, '', current.pathname + current.search + current.hash);
    });
  } catch (_) {
    if (status) status.textContent = 'Search could not load. Browse the discipline catalogues below.';
  }
}());
