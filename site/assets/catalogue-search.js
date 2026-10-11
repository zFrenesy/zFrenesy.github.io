/* The complete economics index is local and loaded only when a reader searches. */
(function () {
  'use strict';
  var root = document.getElementById('economics-catalogue-search');
  if (!root) return;
  var form = root.querySelector('form');
  var input = root.querySelector('input');
  var clear = root.querySelector('[type="reset"]');
  var status = document.getElementById('catalogue-search-status');
  var staticRecords = document.getElementById('catalogue-static-records');
  var results = document.getElementById('catalogue-search-results');
  var heading = document.getElementById('catalogue-results-heading');
  var list = results.querySelector('ul');
  var empty = results.querySelector('.catalogue-search-empty');
  var pagination = results.querySelector('nav');
  var previous = results.querySelector('[data-search-previous]');
  var next = results.querySelector('[data-search-next]');
  var pageLabel = results.querySelector('[data-search-page]');
  var initialStatus = status.textContent;
  var basePath = root.dataset.basePath || '';
  var jelPrefix = (root.dataset.jelCode || '').toUpperCase();
  var pageSize = 30;
  var page = 0;
  var matches = [];
  var request = null;
  var searchVersion = 0;

  function normalized(value) {
    return String(value || '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  }

  function problemHref(value) {
    // Index records contain site-relative problem paths, never external URLs.
    if (typeof value !== 'string' || !/^\/problems\/[A-Za-z0-9][A-Za-z0-9_.-]*\/$/.test(value)) return null;
    return basePath + value;
  }

  function loadIndex() {
    if (request) return request;
    request = Promise.resolve().then(function () {
      var indexURL = new URL(root.dataset.indexUrl, window.location.href);
      if (indexURL.origin !== window.location.origin || !indexURL.pathname.startsWith(basePath + '/')) {
        throw new Error('Invalid catalogue index path');
      }
      return fetch(indexURL.href, { credentials: 'same-origin' });
    }).then(function (response) {
      if (!response.ok) throw new Error('Catalogue unavailable');
      return response.json();
    }).then(function (data) {
      if (!data || !Array.isArray(data.problems)) throw new Error('Invalid catalogue index');
      return data.problems.filter(function (record) {
        return record && typeof record.alias === 'string' && typeof record.title === 'string' && problemHref(record.url);
      }).map(function (record) {
        var jel = Array.isArray(record.jel) ? record.jel.filter(function (item) {
          return item && typeof item.code === 'string' && typeof item.name === 'string';
        }) : [];
        return {
          alias: record.alias,
          title: record.title,
          href: problemHref(record.url),
          jel: jel,
          rank: Number.isInteger(record.rank) && record.rank > 0 ? record.rank : null,
          status: typeof record.status === 'string' ? record.status : '',
          llmStatus: typeof record.llm_status === 'string' ? record.llm_status : '',
          attempts: Number.isInteger(record.attempts) && record.attempts >= 0 ? record.attempts : 0,
          searchText: normalized([record.alias, record.title, record.search_terms || ''].concat(jel.map(function (item) {
            return item.code + ' ' + item.name;
          })).join(' '))
        };
      }).filter(function (record) {
        return !jelPrefix || record.jel.some(function (item) { return item.code.toUpperCase().startsWith(jelPrefix); });
      });
    }).catch(function (error) {
      request = null; // A subsequent search can retry without reloading the page.
      throw error;
    });
    return request;
  }

  function element(tag, className, value) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined) node.textContent = value;
    return node;
  }

  function resultRow(record) {
    var row = element('li', 'row');
    var alias = element('a', 'identifier', record.alias);
    alias.href = record.href;
    var title = element('a', 'row-title', record.title);
    title.href = record.href;
    var metadata = [];
    if (record.rank !== null) metadata.push('Rank ' + record.rank);
    if (record.jel.length) metadata.push('JEL ' + record.jel.map(function (item) {
      return item.code + ' — ' + item.name;
    }).join('; '));
    if (record.status) metadata.push(record.status);
    if (record.llmStatus) metadata.push('LLM status: ' + record.llmStatus);
    metadata.push(record.attempts + (record.attempts === 1 ? ' attempt' : ' attempts'));
    row.append(alias, title, element('span', 'row-meta', metadata.join(' · ')));
    return row;
  }

  function render(focusHeading) {
    var start = page * pageSize;
    var fragment = document.createDocumentFragment();
    matches.slice(start, start + pageSize).forEach(function (record) { fragment.appendChild(resultRow(record)); });
    list.replaceChildren(fragment);
    empty.hidden = matches.length !== 0;
    list.hidden = matches.length === 0;
    pagination.hidden = matches.length <= pageSize;
    previous.disabled = page === 0;
    next.disabled = start + pageSize >= matches.length;
    pageLabel.textContent = 'Page ' + (page + 1) + ' of ' + Math.max(1, Math.ceil(matches.length / pageSize));
    status.textContent = matches.length.toLocaleString() + (matches.length === 1 ? ' matching problem' : ' matching problems') +
      (matches.length ? ' · Showing ' + (start + 1) + '–' + Math.min(start + pageSize, matches.length) : '') + '.';
    staticRecords.hidden = true;
    results.hidden = false;
    if (focusHeading) heading.focus();
  }

  function search(updateURL) {
    var query = input.value.trim();
    var version = ++searchVersion;
    page = 0;
    clear.disabled = !input.value;
    if (updateURL) {
      var current = new URL(window.location.href);
      if (query) current.searchParams.set('q', query);
      else current.searchParams.delete('q');
      window.history.replaceState(null, '', current.pathname + current.search + current.hash);
    }
    if (!query) {
      results.hidden = true;
      staticRecords.hidden = false;
      status.textContent = initialStatus;
      return;
    }
    status.textContent = 'Searching economics…';
    loadIndex().then(function (records) {
      if (version !== searchVersion) return;
      var terms = normalized(query).split(/\s+/);
      if (terms.length > 1) terms = terms.filter(function (term) { return term !== 'jel'; });
      matches = records.filter(function (record) {
        return terms.every(function (term) {
          if (/^[a-z]\d{1,2}$/.test(term) || terms.length === 1 && /^[a-z]$/.test(term)) {
            return record.jel.some(function (item) { return item.code.toLowerCase().startsWith(term); });
          }
          return record.searchText.includes(term);
        });
      });
      render(false);
    }).catch(function () {
      if (version !== searchVersion) return;
      results.hidden = true;
      staticRecords.hidden = false;
      status.textContent = 'Search could not load. Browse the catalogue and JEL classification links, or try searching again.';
    });
  }

  input.addEventListener('input', function () { search(true); });
  form.addEventListener('submit', function (event) { event.preventDefault(); search(true); });
  form.addEventListener('reset', function (event) {
    event.preventDefault();
    input.value = '';
    search(true);
    input.focus();
  });
  previous.addEventListener('click', function () {
    if (page > 0) { page -= 1; render(true); }
  });
  next.addEventListener('click', function () {
    if ((page + 1) * pageSize < matches.length) { page += 1; render(true); }
  });
  window.addEventListener('popstate', function () {
    input.value = new URLSearchParams(window.location.search).get('q') || '';
    search(false);
  });
  root.hidden = false;
  input.value = new URLSearchParams(window.location.search).get('q') || '';
  if (input.value.trim()) search(false);
}());
