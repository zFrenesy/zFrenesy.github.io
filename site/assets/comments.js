/* Giscus is requested only when the reader chooses to load comments. */
(function () {
  'use strict';
  var panel = document.querySelector('[data-comments]');
  if (!panel) return;
  var button = panel.querySelector('[data-load-comments]');
  var status = panel.querySelector('[data-comments-status]');
  var container = panel.querySelector('.giscus');
  var origin = 'https://giscus.app';
  var media = window.matchMedia('(prefers-color-scheme: dark)');
  function theme() {
    return document.documentElement.dataset.theme || (media.matches ? 'dark' : 'light');
  }
  function updateTheme() {
    var frame = container.querySelector('iframe.giscus-frame');
    if (frame && frame.contentWindow) frame.contentWindow.postMessage({giscus: {setConfig: {theme: theme()}}}, origin);
  }
  button.hidden = false;
  button.addEventListener('click', function () {
    button.disabled = true;
    status.textContent = 'Loading comments…';
    var script = document.createElement('script');
    script.src = origin + '/client.js';
    ['repo', 'repoId', 'category', 'categoryId', 'term'].forEach(function (key) { script.dataset[key] = panel.dataset[key]; });
    Object.assign(script.dataset, {mapping: 'specific', strict: '1', reactionsEnabled: '1', emitMetadata: '1', inputPosition: 'top', theme: theme(), lang: 'en'});
    script.crossOrigin = 'anonymous';
    script.async = true;
    script.onerror = function () {
      script.remove(); button.disabled = false;
      status.textContent = 'Comments could not load. Try again or open the discussion on GitHub.';
    };
    script.onload = function () { button.hidden = true; status.textContent = ''; };
    container.appendChild(script);
  });
  window.addEventListener('message', function (event) {
    var frame = container.querySelector('iframe.giscus-frame');
    if (event.origin !== origin || !frame || event.source !== frame.contentWindow) return;
    var data = event.data && event.data.giscus;
    if (!data) return;
    if (data.error && !/discussion not found/i.test(data.error)) status.textContent = 'Comments are temporarily unavailable. Open the discussion on GitHub.';
    var link = data.discussion && data.discussion.url;
    if (typeof link === 'string' && link.startsWith('https://github.com/' + panel.dataset.repo + '/discussions/')) panel.querySelector('[data-discussion-link]').href = link;
  });
  new MutationObserver(updateTheme).observe(document.documentElement, {attributes: true, attributeFilter: ['data-theme']});
  if (media.addEventListener) media.addEventListener('change', updateTheme);
})();
