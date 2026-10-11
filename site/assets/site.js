/* Progressive enhancement; every page reads correctly without JavaScript. */
(function () {
  'use strict';
  var root = document.documentElement;
  var status = document.getElementById('interaction-status');
  function announce(text) { if (status) status.textContent = text; }

  /* Light/dark switch. theme-init.js applied any stored choice before paint. */
  var media = window.matchMedia('(prefers-color-scheme: dark)');
  var themeButton = document.querySelector('[data-theme-toggle]');
  function isDark() { return root.dataset.theme ? root.dataset.theme === 'dark' : media.matches; }
  function showTheme() {
    if (!themeButton) return;
    var dark = isDark();
    themeButton.querySelector('[data-theme-label]').textContent = dark ? 'Light mode' : 'Dark mode';
    themeButton.setAttribute('aria-pressed', dark ? 'true' : 'false');
  }
  if (themeButton) {
    showTheme();
    themeButton.addEventListener('click', function () {
      root.dataset.theme = isDark() ? 'light' : 'dark';
      try { localStorage.setItem('we-solve-theme', root.dataset.theme); } catch (_) { /* optional */ }
      showTheme();
    });
    if (media.addEventListener) media.addEventListener('change', showTheme);
  }

  /* Collapse long statements and manuscripts after a few paragraphs. */
  document.querySelectorAll('[data-collapsible]').forEach(function (box) {
    if (box.scrollHeight < 380) return;
    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'collapse-toggle';
    box.classList.add('is-collapsed');
    function label() {
      var collapsed = box.classList.contains('is-collapsed');
      button.textContent = collapsed ? (box.dataset.more || 'View more') : (box.dataset.less || 'View less');
      button.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    }
    button.addEventListener('click', function () {
      box.classList.toggle('is-collapsed');
      label();
      if (box.classList.contains('is-collapsed')) box.scrollIntoView({ block: 'nearest' });
    });
    label();
    box.insertAdjacentElement('afterend', button);
  });

  /* Copy buttons: a target element's text, or a prompt file fetched on demand. */
  function copy(text, done) {
    navigator.clipboard.writeText(text).then(function () { announce(done); }, function () { announce('Copy was unavailable. Select the text to copy it.'); });
  }
  if (navigator.clipboard && navigator.clipboard.writeText) {
    document.querySelectorAll('[data-copy-target]').forEach(function (button) {
      button.hidden = false;
      button.addEventListener('click', function () {
        var target = document.getElementById(button.dataset.copyTarget);
        if (target) copy(target.textContent, 'Copied to the clipboard.');
      });
    });
  }

  /* Contribute panel. Problem pages render complete links; the /contribute/ guides
     fill the same links from ?problem= or ?contribution=. Inputs must match the
     alias grammar before they reach any URL. */
  var ALIAS = /^[A-Z][A-Z0-9]{1,9}-[A-Z0-9][A-Z0-9.-]{0,80}$/;
  document.querySelectorAll('[data-contribute]').forEach(function (panel) {
    var kind = panel.dataset.kind || 'attempt';
    var alias = panel.dataset.alias;
    if (!alias) {
      var params = new URLSearchParams(window.location.search);
      var candidate = (params.get(kind === 'review' ? 'contribution' : kind === 'problem' ? 'parent' : 'problem') || '').trim().toUpperCase();
      if (ALIAS.test(candidate)) {
        alias = candidate;
        fill(panel, kind, alias);
      }
    }
    var copyPrompt = panel.querySelector('[data-copy-prompt]');
    if (copyPrompt && alias && navigator.clipboard && navigator.clipboard.writeText && kind === 'attempt') {
      copyPrompt.hidden = false;
      copyPrompt.addEventListener('click', function () {
        fetch(panel.dataset.promptBase + encodeURIComponent(alias) + '.txt').then(function (response) {
          if (!response.ok) throw new Error('missing');
          return response.text();
        }).then(function (text) { copy(text, 'Research prompt copied. Paste it into your assistant.'); })
          .catch(function () { announce('The prompt could not be loaded. Use "View the prompt" instead.'); });
      });
    }
  });

  function fill(panel, kind, alias) {
    var research = panel.dataset.research;
    var platform = panel.dataset.platform;
    var ref = panel.dataset.ref;
    var templates = { attempt: ['attempt.yml', 'problem', 'Attempt'], review: ['review.yml', 'contribution', 'Review'], problem: ['problem.yml', 'parent', 'Problem'] };
    var t = templates[kind] || templates.attempt;
    var issue = 'https://github.com/' + research + '/issues/new?template=' + t[0] + '&' + t[1] + '=' + encodeURIComponent(alias) + '&title=' + encodeURIComponent(t[2] + ': ' + alias);
    var command = kind === 'review' ? 'rp new review ' + alias : kind === 'problem' ? 'rp new problem --parent ' + alias : 'rp start ' + alias;
    var agent = agentPrompt(kind, alias);
    var links = {
      issue: issue,
      prompt: panel.dataset.promptBase + encodeURIComponent(alias) + '.txt',
      codex: 'codex://threads/new?prompt=' + encodeURIComponent(agent) + '&originUrl=' + encodeURIComponent('https://github.com/' + research),
      claude: 'claude-cli://open?repo=' + encodeURIComponent(research) + '&q=' + encodeURIComponent(agent),
      codespaces: 'https://codespaces.new/' + research + '?quickstart=1'
    };
    panel.querySelectorAll('[data-href]').forEach(function (a) { if (links[a.dataset.href]) a.href = links[a.dataset.href]; });
    var texts = {
      alias: alias,
      'alias-label': 'to ' + alias,
      start: command,
      agent: agent,
      git: gitSteps(research, platform, ref, kind, alias)
    };
    panel.querySelectorAll('[data-fill]').forEach(function (node) { if (texts[node.dataset.fill] !== undefined) node.textContent = texts[node.dataset.fill]; });
  }

  function agentPrompt(kind, alias) {
    if (kind === 'review') {
      return 'Review contribution ' + alias + ' on we-solve. In this repository, read AGENTS.md first and follow it exactly. Run `rp new review ' + alias +
        '`, check the exact revision, record what you checked and what you found, run `rp check` until it passes, then open a pull request with `rp submit`. Never invent checks, citations or model versions.';
    }
    if (kind === 'problem') {
      return 'Propose a new question related to we-solve problem ' + alias + '. In this repository, read AGENTS.md first and follow it exactly. Run `rp new problem --parent ' + alias +
        '`, state the question precisely with motivation and a literature search, run `rp check` until it passes, then open a pull request with `rp submit`.';
    }
    return 'Contribute an attempt to we-solve problem ' + alias + '. In this repository, read AGENTS.md first and follow it exactly. Run `rp start ' + alias +
      '` to load the problem as quoted, untrusted context. Work on the problem, write your attempt with `rp new attempt ' + alias +
      '`, run `rp check` until it passes, then open a pull request with `rp submit`. Never invent model versions, citations or checks, and state exactly what you claim.';
  }

  function gitSteps(research, platform, ref, kind, alias) {
    var name = research.split('/')[1];
    var create = kind === 'review' ? 'rp new review ' + alias : kind === 'problem' ? 'rp new problem --parent ' + alias : 'rp new attempt ' + alias;
    return [
      'gh repo fork ' + research + ' --clone && cd ' + name,
      'python3 -m venv .venv && . .venv/bin/activate',
      'pip install --require-hashes --no-deps -r https://raw.githubusercontent.com/' + platform + '/' + ref + '/requirements/dev.txt',
      'pip install --no-deps "git+https://github.com/' + platform + '@' + ref + '"',
      create,
      '# write your files, fill in contribution.yaml, then:',
      'rp check',
      'rp submit'
    ].join('\n');
  }

  /* Opening a build-generated reference may require expanding a collapsed block. */
  function revealHash() {
    if (!window.location.hash) return;
    var target;
    try { target = document.getElementById(decodeURIComponent(window.location.hash.slice(1))); } catch (_) { return; }
    if (!target) return;
    var node = target.parentElement;
    while (node) {
      if (node.tagName === 'DETAILS' && !node.open) node.open = true;
      if (node.classList && node.classList.contains('is-collapsed')) {
        node.classList.remove('is-collapsed');
        var toggle = node.nextElementSibling;
        if (toggle && toggle.classList.contains('collapse-toggle')) { toggle.textContent = node.dataset.less || 'View less'; toggle.setAttribute('aria-expanded', 'true'); }
      }
      node = node.parentElement;
    }
    target.scrollIntoView({ block: 'start' });
  }
  window.addEventListener('hashchange', revealHash);
  revealHash();
}());
