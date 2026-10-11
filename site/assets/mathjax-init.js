/* Wrap the preserved legacy configuration without changing its extracted source. */
(function (root) {
  'use strict';
  var script = document.currentScript;
  var engineSource = script && script.dataset.mathjaxSrc;
  var containers = Array.prototype.slice.call(document.querySelectorAll('.tex-content.mathjax-process'));
  if (!containers.length || !engineSource || !root.MathJax) return;
  var config = root.MathJax;
  var failedExpressions = new Set();

  function sourceBox(source, display) {
    // A span remains valid inside paragraphs even when it is styled as a block.
    var box = document.createElement('span');
    box.className = 'tex-source-box mathjax-ignore' + (display ? '' : ' tex-source-box-inline');
    box.setAttribute('role', 'note');
    var caption = document.createElement('span');
    caption.className = 'tex-source-caption';
    caption.textContent = 'Math source (display unavailable)';
    var code = document.createElement('code');
    code.textContent = source;
    box.appendChild(caption);
    box.appendChild(code);
    return box;
  }

  function replaceErrors() {
    var mathDocument = root.MathJax.startup && root.MathJax.startup.document;
    if (!mathDocument || !mathDocument.getMathItemsWithin) return;
    mathDocument.getMathItemsWithin(containers).forEach(function (item) {
      var output = item.typesetRoot;
      if (!output || !output.parentNode) return;
      var failed = failedExpressions.has(item.math) ||
        (item.inputData && item.inputData.error) || (item.outputData && item.outputData.error) ||
        (output.querySelector && output.querySelector('mjx-merror, merror, [data-mjx-error]'));
      if (failed) output.replaceWith(sourceBox(item.math, item.display));
    });
  }

  function sizeWideMath() {
    containers.forEach(function (container) {
      container.querySelectorAll('mjx-container').forEach(function (output) {
        var math = output.querySelector('mjx-math');
        var display = output.getAttribute('display') === 'true';
        var wide = display ? output.scrollWidth > output.clientWidth + 1 :
          math && math.getBoundingClientRect().width > container.clientWidth;
        output.classList.toggle('tex-wide-math', !display && Boolean(wide));
        if (wide) {
          output.setAttribute('tabindex', '0');
          output.setAttribute('aria-label', 'Wide equation; scroll horizontally');
          output.dataset.scrollableMath = 'true';
        } else if (output.dataset.scrollableMath) {
          output.removeAttribute('tabindex');
          output.removeAttribute('aria-label');
          delete output.dataset.scrollableMath;
        }
      });
    });
  }

  function showLoadFailure() {
    replaceErrors();
    containers.forEach(function (container) {
      container.dataset.mathStatus = 'source';
      if (container.querySelector('.math-status-note')) return;
      var notice = document.createElement('p');
      notice.className = 'math-status-note mathjax-ignore';
      notice.setAttribute('role', 'status');
      notice.textContent = 'Mathematical display could not load. The original notation remains available below and in the source files.';
      container.prepend(notice);
    });
  }

  // Undefined commands must enter the same explicit fallback as parser errors.
  // The legacy noerrors/noundefined extensions otherwise conceal those failures.
  config.tex.packages['[+]'] = config.tex.packages['[+]'].filter(function (name) { return name !== 'noerrors' && name !== 'noundefined'; });
  config.tex.packages['[-]'] = ['noerrors', 'noundefined'];
  config.loader.load = config.loader.load.filter(function (name) { return name !== '[tex]/noerrors'; });
  if (config.loader.load.indexOf('a11y/assistive-mml') === -1) config.loader.load.push('a11y/assistive-mml');
  config.tex.formatError = function (jax, error) {
    failedExpressions.add(jax.latex);
    return jax.formatError(error);
  };
  // Only allow extensions included in the pinned, self-hosted distribution.
  var extensions = ['action', 'ams', 'amscd', 'autoload', 'bbox', 'boldsymbol', 'braket', 'bussproofs', 'cancel', 'cases', 'centernot', 'color', 'colorv2', 'colortbl', 'configmacros', 'empheq', 'enclose', 'extpfeil', 'gensymb', 'html', 'mathtools', 'mhchem', 'newcommand', 'physics', 'require', 'tagformat', 'textcomp', 'textmacros', 'unicode', 'upgreek', 'verb'];
  var allow = {};
  extensions.forEach(function (name) { allow[name] = true; });
  config.tex.require = { allow: allow, defaultAllow: false };
  config.options.enableAssistiveMml = true;
  // The bundled context menu can enable SRE speech and fetch unvendored locale
  // maps from a CDN. Keep accessibility through assistive MathML without that UI.
  config.options.enableMenu = false;
  config.options.compileError = function (mathDocument, item, error) {
    failedExpressions.add(item.math);
    mathDocument.compileError(item, error);
  };
  config.options.typesetError = function (mathDocument, item, error) {
    failedExpressions.add(item.math);
    mathDocument.typesetError(item, error);
  };
  config.startup.typeset = false;
  config.startup.ready = function () {
    root.MathJax.startup.defaultReady();
    root.MathJax.startup.promise = root.MathJax.startup.promise.then(function () {
      return root.MathJax.typesetPromise(containers);
    }).then(function () {
      replaceErrors();
      sizeWideMath();
      if (root.ResizeObserver) {
        var observer = new root.ResizeObserver(sizeWideMath);
        containers.forEach(function (container) { observer.observe(container); });
      } else root.addEventListener('resize', sizeWideMath);
      containers.forEach(function (container) { container.dataset.mathStatus = 'ready'; });
      // Browser navigation may have preceded equation layout. Revisit an existing
      // anchor after typesetting without generating or rewriting reference links.
      if (root.location.hash) {
        var target;
        try { target = document.getElementById(decodeURIComponent(root.location.hash.slice(1))); } catch (_) { return; }
        if (target) target.scrollIntoView({ block: 'start' });
      }
    }).catch(showLoadFailure);
  };
  config.loader.failed = showLoadFailure;
  var engine = document.createElement('script');
  engine.src = engineSource;
  engine.async = true;
  engine.addEventListener('error', showLoadFailure, { once: true });
  document.head.appendChild(engine);
}(window));
