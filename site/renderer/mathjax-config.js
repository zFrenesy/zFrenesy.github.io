// MathJax 3 configuration. The tex block (packages, delimiters, equation tags and
// macros) is copied unchanged from the legacy site (docs/problem.html @ b1f6331).
// Changes: self-hosted loader path, no automatic page-wide typesetting (each page
// typesets only its manuscript or statement container), assistive MathML, source
// boxes excluded, and a failed expression falls back to its source text.
(function (root) {
    var base = (document.currentScript && document.currentScript.dataset.mathjaxBase) || '/assets/vendor/mathjax-3.2.2/es5';
    root.MathJax = {
            loader: { load: ['[tex]/mathtools', '[tex]/noerrors', 'ui/safe'], paths: { mathjax: base } },
            tex: {
                packages: { '[+]': ['mathtools'] },
                inlineMath: [['$', '$'], ['\\(', '\\)']],
                displayMath: [['$$', '$$'], ['\\[', '\\]']],
                processEscapes: true,
                processEnvironments: true,
                tags: 'ams',
                macros: {
                    'H': ['{\\text{H}}', 0],
                    'R': '{\\mathbb{R}}',
                    'C': '{\\mathbb{C}}',
                    'N': '{\\mathbb{N}}',
                    'Z': '{\\mathbb{Z}}',
                    'Q': '{\\mathbb{Q}}',
                    'F': '{\\mathbb{F}}',
                    'RR': '{\\mathbb{R}}',
                    'CC': '{\\mathbb{C}}',
                    'NN': '{\\mathbb{N}}',
                    'ZZ': '{\\mathbb{Z}}',
                    'QQ': '{\\mathbb{Q}}',
                    'FF': '{\\mathbb{F}}',
                    'PP': '{\\mathbb{P}}',
                    'HH': '{\\mathbb{H}}',
                    'Qbar': '{\\overline{\\mathbb{Q}}}',
                    'GQ': '{\\mathrm{Gal}(\\Qbar/\\mathbb{Q})}',
                    'Mgn': ['{\\mathcal{M}_{#1,#2}}', 2],
                    'Mg': ['{\\mathcal{M}_{#1}}', 1],
                    'poly': '{\\operatorname{poly}}',
                    'coloneqq': '{\\mathrel{:=}}',
                    'diam': '{\\operatorname{diam}}',
                    'Sha': '{\\unicode{x0428}}',
                    'ex': '{\\operatorname{ex}}',
                    'binomc': ['{\\binom{#1}{#2}}', 2],
                    'sp': '^',
                    'sb': '_',
                    '*': '{\\ast}',
                    'ensuremath': ['{#1}', 1],
                    'cL': '{\\mathcal{L}}',
                    'Ga': '{\\mathbb{G}_a}',
                    'Gm': '{\\mathbb{G}_m}',
                    'Aone': '{\\mathbb{A}^1}',
                    'Fp': '{\\mathbb{F}_p}',
                    'Bbb': ['{\\mathbb{#1}}', 1],
                    'normp': ['{\\|#1\\|_{#2}}', 2],
                    'norm': ['{\\|#1\\|}', 1],
                    'abs': ['{|#1|}', 1],
                    'ceil': ['{\\lceil#1\\rceil}', 1],
                    'floor': ['{\\lfloor#1\\rfloor}', 1],
                    'inner': ['{\\langle#1,#2\\rangle}', 2],
                    'set': ['{\\{#1\\}}', 1],
                    'qed': '{\\square}',
                    'eps': '{\\varepsilon}',
                    'overd': '{\\overline{d}}',
                    'underd': '{\\underline{d}}',
                    'ol': ['{\\overline{#1}}', 1],
                    'ul': ['{\\underline{#1}}', 1],
                    'wh': ['{\\widehat{#1}}', 1],
                    'wt': ['{\\widetilde{#1}}', 1],
                    'E': '{\\mathbb{E}}',
                    'ind': '{\\mathbf{1}}',
                    'Var': '{\\operatorname{Var}}',
                    'Cov': '{\\operatorname{Cov}}',
                    'supp': '{\\operatorname{supp}}',
                    'argmin': '{\\operatorname*{arg\\,min}}',
                    'argmax': '{\\operatorname*{arg\\,max}}'
                }
            },
            options: {
                skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code'],
                ignoreHtmlClass: 'mathjax-ignore|tex-source-box',
                processHtmlClass: 'mathjax-process',
                // External sources belong in prose links, which the formatter
                // validates. Do not let mathematical macros introduce URLs.
                safeOptions: { allow: { URLs: 'none' } },
                enableEnrichment: false,
                menuOptions: { settings: { assistiveMml: true, explorer: false } }
            },
            startup: {
                typeset: false,
                ready: function () {
                    root.MathJax.startup.defaultReady();
                    var containers = document.querySelectorAll('.mathjax-process');
                    root.MathJax.typesetPromise(Array.prototype.slice.call(containers)).then(function () {
                        if (root.ProblemHunting && root.ProblemHunting.initTeXReferences) {
                            root.ProblemHunting.initTeXReferences(document, null);
                        }
                    });
                }
            }
    };
    // noerrors: an expression that fails to parse is shown as its TeX source.
    root.MathJax.tex.packages['[+]'].push('noerrors');
})(window);
