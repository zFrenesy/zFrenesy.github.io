// formatTeX, extracted unchanged from mehmetmars7/Erdosproblems-llm-hunter
// @ b1f633121074e16579fa7fd05314e5f504d29bae, docs/problem.html (Apache-2.0).
// Only this wrapper is new: it exposes the function on the global object so the
// build-time runner and the browser can both call it. See PROVENANCE.json.
(function (root) {
        function formatTeX(text, preserveCollection = false, inferInlineMath = true) {
            if (!text) return '';

            // Complete articles include a preamble that is not browser content.
            // Require document markers on their own lines so examples in fragments survive.
            const documentStart = /^[ \t]*\\begin\{document\}[ \t]*\r?$/m.exec(text);
            // A collection may contain several complete TeX documents and
            // fragments. Do not discard earlier versions or attribution when
            // a later reused source starts its own document environment.
            if (documentStart && !preserveCollection) {
                text = text.slice(documentStart.index + documentStart[0].length);
                text = text.replace(/^[ \t]*\\end\{document\}[ \t]*\r?$/m, '');
                text = text.replace(/^[ \t]*\{\\(LARGE|large)\s+(.+)\}(?:\\\\(?:\[[^\]]*\])?)?[ \t]*\r?$/gm, function(match, size, title) {
                    const tag = size === 'LARGE' ? 'h2' : 'h3';
                    return `<${tag}>${title}</${tag}>`;
                });
                text = text.replace(/^[ \t]*\\small[ \t]*(?:\r?\n|$)/gm, '');
            }

            // Keep mathematical notation and literal source/code text out of the
            // prose formatter. In particular, a TeX star is not Markdown emphasis.
            const protectedFragments = [];
            function protectHTML(html) {
                const token = `\uE000TEX${protectedFragments.length}\uE001`;
                protectedFragments.push(html);
                return token;
            }
            function escapeHTML(value) {
                return value.replace(/&/g, '&amp;').replace(/</g, '&lt;')
                    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
            }
            function proseEscapes(value, preserveSpacing = false) {
                const unescaped = value.replace(/\\([#%&_{}$])/g, '$1');
                return preserveSpacing ? unescaped : unescaped.replace(/\\ /g, ' ').replace(/\\,/g, '\u2009');
            }
            function normalizeSourceURL(url) {
                return proseEscapes(url, true).replace(/\\~(?:\{\})?/g, '~').trim();
            }
            function sourceLink(url, label) {
                const destination = normalizeSourceURL(url);
                if (label === url || label === proseEscapes(url)) label = destination;
                if (!/^https?:\/\//i.test(destination)) return escapeHTML(label);
                return `<a href="${escapeHTML(destination)}" target="_blank" rel="noopener noreferrer">${escapeHTML(label)}</a>`;
            }
            function referenceScope(input, offset) {
                return (input.slice(0, offset).match(/% BEGIN REUSED SOURCE:/g) || []).length;
            }
            function referenceLabel(key, scope, kind = 'prose') {
                return `<span class="tex-label" data-tex-label="${escapeHTML(key)}" data-tex-scope="${scope}" data-tex-label-kind="${kind}"></span>`;
            }
            function linkPlainURLs(input) {
                return input.replace(/https?:\/\/[^\s<>"{}|\\^\[\]`]+/g, function(candidate) {
                    let url = candidate.replace(/[.,;:!?]+$/, '');
                    // A sentence's closing parenthesis is not part of its URL;
                    // balanced parentheses inside a URL (e.g. Wikipedia) are.
                    while (url.endsWith(')') && (url.match(/\)/g) || []).length > (url.match(/\(/g) || []).length) {
                        url = url.slice(0, -1);
                    }
                    return protectHTML(sourceLink(url, url)) + candidate.slice(url.length);
                });
            }
            text = text.replace(/\\begin\{(verbatim\*?|Verbatim|Code)\}(?:\[[^\]]*\])?([\s\S]*?)\\end\{\1\}/g,
                (match, environment, content) => protectHTML(`<pre>${escapeHTML(content)}</pre>`));
            text = text.replace(/\\verb\*?([^\w\s])([^\n]*?)\1/g,
                (match, delimiter, content) => protectHTML(`<code>${escapeHTML(content)}</code>`));
            // Comment lines are source metadata, not visible content. Literal
            // code is already protected; retain collection boundaries until
            // labels and references have been assigned their source scopes.
            text = text.replace(/^[ \t]*%(?! BEGIN REUSED SOURCE:)[^\r\n]*(?:\r?\n|$)/gm, '');
            // A browser table has no page breaks or repeated page headers.
            // Use the same HTML table renderer as ordinary tabular material.
            text = text.replace(/\\begin\{longtable\}(?:\[[^\]]*\])?([\s\S]*?)\\end\{longtable\}/g,
                (match, body) => '\\begin{tabular}' + body.replace(/\\end(?:firsthead|head|foot|lastfoot)\b/g, '') + '\\end{tabular}');
            // This fallback only defines the already-supported end-of-proof mark;
            // its definition is metadata, while later \qed uses remain visible.
            text = replaceTwoArgCommand(text, 'providecommand', (command, body) =>
                command.trim() === '\\qed' ? '' : `\\providecommand{${command}}{${body}}`);
            // Some fragments put an HTML-style text table inside display math.
            // Unwrap only a display consisting entirely of that tabular block.
            text = text.replace(/\\\[\s*(\\begin\{tabular\}[\s\S]*?\\end\{tabular\})\s*\\\]/g, '$1');
            text = text.replace(/(?<!\\)\$\$\s*(\\begin\{tabular\}[\s\S]*?\\end\{tabular\})\s*\$\$/g, '$1');

            function normalizeBlockquotes(input) {
                const lines = input.split('\n');
                const out = [];
                let inQuote = false;

                for (const line of lines) {
                    const match = line.match(/^\s*>\s?(.*)$/);
                    if (match) {
                        if (!inQuote) {
                            out.push('\\begin{quote}');
                            inQuote = true;
                        }
                        out.push(match[1]);
                    } else {
                        if (inQuote) {
                            out.push('\\end{quote}');
                            inQuote = false;
                        }
                        out.push(line);
                    }
                }

                if (inQuote) {
                    out.push('\\end{quote}');
                }

                return out.join('\n');
            }

            // A displayed inequality can have a continuation line beginning >.
            // Protect those expressions before interpreting Markdown quote lines.
            text = text.replace(/(^|\n)[ \t]*\[(?=\n|$)/g, '$1\\[');
            text = text.replace(/(^|\n)[ \t]*\](?=\n|$)/g, '$1\\]');
            text = protectMath(text, true);
            text = normalizeBlockquotes(text);

            // First, convert alternate LaTeX delimiters to MathJax-compatible ones
            // Convert display math lines: only lines that contain just [ or ]
            text = text.replace(/(^|\n)[ \t]*\[(?=\n|$)/g, '$1\\[');
            text = text.replace(/(^|\n)[ \t]*\](?=\n|$)/g, '$1\\]');

            // Convert inline math (...) to \(...\) with a balanced parser (handles nested parentheses).
            function convertInlineMath(input) {
                const inlineStart = '\\(';
                const inlineEnd = '\\)';
                const displayStart = '\\[';
                const displayEnd = '\\]';
                const verbatimStart = '\\begin{verbatim}';
                const verbatimEnd = '\\end{verbatim}';
                const mathCommandRe = /\\[a-zA-Z]+/;

                function isMathSegment(segment) {
                    if (segment.trim() === '\\*') return false;
                    if (/^\s*\\(?:emph|textbf|textit|texttt|underline|textrm|textsf|textsc|url|href|cite[pt]?)(?:\{|\[)/.test(segment)) return false;
                    if (/^\s*(?:\*\*)?#\d+\s*(?:⇒|→|=>|->)\s*#\d+(?:\*\*)?\s*$/.test(segment)) return false;
                    const hasCommand = mathCommandRe.test(segment);
                    const hasMathOps = /[_^=<>+\-*/]/.test(segment) || /\d/.test(segment);
                    let cleaned = segment;
                    cleaned = cleaned.replace(/\\[a-zA-Z]+\s*\{[^{}]*\}/g, '');
                    cleaned = cleaned.replace(/\\[a-zA-Z]+/g, '');
                    cleaned = cleaned.replace(/[{}]/g, '');
                    const hasWord = /[A-Za-z]{2,}/.test(cleaned);
                    return (hasCommand || hasMathOps) && !hasWord;
                }
                let out = '';
                let i = 0;

                while (i < input.length) {
                    if (input.slice(i, i + verbatimStart.length) === verbatimStart) {
                        const endIdx = input.indexOf(verbatimEnd, i + verbatimStart.length);
                        if (endIdx !== -1) {
                            out += input.slice(i, endIdx + verbatimEnd.length);
                            i = endIdx + verbatimEnd.length;
                            continue;
                        }
                    }
                    if (input.slice(i, i + displayStart.length) === displayStart) {
                        const endIdx = input.indexOf(displayEnd, i + displayStart.length);
                        if (endIdx !== -1) {
                            out += input.slice(i, endIdx + displayEnd.length);
                            i = endIdx + displayEnd.length;
                            continue;
                        }
                    }
                    if (input.slice(i, i + inlineStart.length) === inlineStart) {
                        const endIdx = input.indexOf(inlineEnd, i + inlineStart.length);
                        if (endIdx !== -1) {
                            out += input.slice(i, endIdx + inlineEnd.length);
                            i = endIdx + inlineEnd.length;
                            continue;
                        }
                    }
                    if (input[i] === '$' && (i === 0 || input[i - 1] !== '\\')) {
                        const isDisplay = input[i + 1] === '$';
                        const delim = isDisplay ? '$$' : '$';
                        const endIdx = input.indexOf(delim, i + delim.length);
                        if (endIdx !== -1) {
                            out += input.slice(i, endIdx + delim.length);
                            i = endIdx + delim.length;
                            continue;
                        }
                    }

                    const ch = input[i];
                    if (ch === '(' && (i === 0 || input[i - 1] !== '\\')) {
                        if (isSizingCommandBeforeParen(input, i)) {
                            out += ch;
                            i += 1;
                            continue;
                        }
                        let depth = 1;
                        let j = i + 1;

                        while (j < input.length) {
                            const c = input[j];
                            if (c === '(' && input[j - 1] !== '\\') {
                                depth += 1;
                            } else if (c === ')' && input[j - 1] !== '\\') {
                                depth -= 1;
                                if (depth === 0) {
                                    const segment = input.slice(i + 1, j);
                                    if (isMathSegment(segment)) {
                                        out += '\\(' + segment + '\\)';
                                    } else {
                                        out += '(' + convertInlineMath(segment) + ')';
                                    }
                                    i = j + 1;
                                    break;
                                }
                            }
                            j += 1;
                        }

                        if (depth === 0) {
                            continue;
                        }
                    }

                    out += ch;
                    i += 1;
                }

                return out;
            }

            function isSizingCommandBeforeParen(input, idx) {
                const lookback = input.slice(Math.max(0, idx - 12), idx);
                return /\\(left|right|bigl|bigr|Bigl|Bigr|big|Big|bigg|Bigg|biggl|Biggl|biggr|Biggr)\s*$/.test(lookback);
            }

            function normalizeEquationTags(math) {
                // AMS inner environments cannot own equation tags. Move each
                // tag beyond the enclosing inner block, retaining its alignment.
                const inner = new Set(['aligned', 'alignedat', 'gathered', 'split']);
                const stack = [];
                const blocks = [];
                const tokens = /\\(?:begin\{([^}]+)\}|end\{([^}]+)\}|tag(\*)?(?![a-zA-Z])|[\\{}])/g;
                let token;
                while ((token = tokens.exec(math))) {
                    if (token[1]) {
                        const block = { environment: token[1], tags: [] };
                        stack.push(block);
                        blocks.push(block);
                    } else if (token[2]) {
                        if (stack.at(-1)?.environment !== token[2]) return math;
                        stack.pop().end = tokens.lastIndex;
                    } else if (/^\\tag/.test(token[0])) {
                        let start = tokens.lastIndex;
                        while (/\s/.test(math[start] || '') && start < math.length) start += 1;
                        const argument = parseBracedArg(math, start);
                        if (!argument) continue;
                        // Nested inner blocks must share the outermost owner;
                        // a numbered align/equation between them ends that scope.
                        let owner;
                        for (let i = stack.length - 1; i >= 0 && inner.has(stack[i].environment); i -= 1) owner = stack[i];
                        if (owner) owner.tags.push({ start: token.index, end: argument.end,
                            value: math.slice(token.index, argument.end) });
                        tokens.lastIndex = argument.end;
                    }
                }
                if (stack.length) return math;
                const edits = [];
                for (const block of blocks) {
                    // Multiple row tags need a numbered outer environment;
                    // don't turn them into duplicate tags on a single equation.
                    if (block.tags.length !== 1) continue;
                    const tag = block.tags[0];
                    edits.push({ start: tag.start, end: tag.end, value: '' },
                        { start: block.end, end: block.end, value: tag.value });
                }
                for (const edit of edits.sort((a, b) => b.start - a.start)) {
                    math = math.slice(0, edit.start) + edit.value + math.slice(edit.end);
                }
                return math;
            }

            function normalizeMath(math) {
                // Fixed-size delimiters may intentionally span alignment rows.
                // Converting them to left/right makes otherwise valid TeX fail.
                const spansRows = /\\[Bb]igg?l[\s\S]*?\\\\[\s\S]*?\\[Bb]igg?r/.test(math);
                let normalized = normalizeEquationTags(math)
                    .replace(/\\label\{[^}]+\}/g, '')
                    .replace(/\\(eqref|ref|cref|Cref)\{([^}]+)\}/g, (match, kind, key) => {
                        const visible = key.replace(/[\\{}%#_$&]/g, '\\$&');
                        return kind === 'eqref' ? `\\text{(${visible})}` : `\\text{${visible}}`;
                    })
                    .replace(/\\qedhere\b|\\qed\b/g, '\\square')
                    .replace(/\\(begin|end)\{psmallmatrix\}/g, '\\$1{pmatrix}');
                if (!spansRows) normalized = normalized
                    .replace(/\\[Bb]igg?l\s*([(\[{|])/g, '\\left$1')
                    .replace(/\\[Bb]igg?r\s*([)\]}|])/g, '\\right$1')
                    .replace(/\\[Bb]igg?l\s*\\\{/g, '\\left\\{')
                    .replace(/\\[Bb]igg?r\s*\\\}/g, '\\right\\}')
                    .replace(/\\[Bb]igg?[lr]/g, '');
                return normalized
                    .replace(/\\left\{/g, '\\left\\{')
                    .replace(/\\right\}/g, '\\right\\}')
                    .replace(/\\\(|\\\)/g, '$');
            }
            // Environments may be used without surrounding dollar delimiters.
            // Match them together with explicit delimiters so nesting stays intact.
            function protectMath(input, beforeQuotes = false) {
                return input.replace(/\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|(?<!\\)\$\$[\s\S]*?(?<!\\)\$\$|(?<!\\)\$(?!\$)(?:(?!\n\s*\n|\\(?:item\b|(?:sub)*section\b|paragraph\b|(?:begin|end)\{(?:itemize|enumerate|quote|theorem|lemma|proof|document)\}))(?:\\[\s\S]|[^$\\]))*?\$|\\begin\{((?:equation|align|alignat|gather|multline|flalign|eqnarray|math|displaymath)\*?)\}[\s\S]*?\\end\{\1\}/g,
                    function(math, environment, offset) {
                        // Markdown's > prefixes must be removed from quoted math
                        // first; all other math can be shielded immediately.
                        const lineStart = input.lastIndexOf('\n', offset - 1) + 1;
                        if (beforeQuotes && /^\s*>\s*$/.test(input.slice(lineStart, offset))) return math;
                        const scope = referenceScope(input, offset);
                        const labels = [...math.matchAll(/\\label\{([^}]+)\}/g)]
                            .map(match => referenceLabel(match[1], scope, 'math')).join('');
                        return protectHTML(labels + escapeHTML(normalizeMath(math)));
                    });
            }
            text = protectMath(text);
            text = replaceLatexCommand(text, 'texttt', function(content) {
                content = proseEscapes(content);
                const markdownLink = content.match(/^\[([^\]]+)\]\((https?:\/\/[^\s]+)\)$/);
                if (markdownLink) return protectHTML(`<code>${sourceLink(markdownLink[2], markdownLink[1])}</code>`);
                if (/^https?:\/\/[^\s]+$/.test(content)) return protectHTML(`<code>${sourceLink(content, content)}</code>`);
                return protectHTML(`<code>${escapeHTML(content)}</code>`);
            });
            text = replaceLatexCommand(text, 'url', url => protectHTML(sourceLink(url, proseEscapes(url))));
            text = replaceTwoArgCommand(text, 'href', function(url, label) {
                const destination = normalizeSourceURL(url);
                // The nested formatter has its own fragment indices. Keep any
                // already-protected label math separate until it returns.
                const labelInput = label.replace(/\uE000TEX(\d+)\uE001/g, '\uE002REF$1\uE003');
                const caption = formatTeX(labelInput).replace(/^<p>|<\/p>$/g, '')
                    .replace(/<\/?a(?:\s[^>]*)?>/g, '')
                    .replace(/\uE002REF(\d+)\uE003/g, '\uE000TEX$1\uE001');
                if (!/^https?:\/\//i.test(destination)) return protectHTML(caption);
                return protectHTML(`<a href="${escapeHTML(destination)}" target="_blank" rel="noopener noreferrer">${caption}</a>`);
            });

            // Keep explicit source references visible, even when a target is
            // absent. Their links are scoped to this writeup after DOM rendering.
            text = text.replace(/\\(label|ref|eqref|cref|Cref)\{([^}]+)\}/g, (match, kind, key, offset, input) => {
                const scope = referenceScope(input, offset);
                if (kind === 'label') return protectHTML(referenceLabel(key, scope));
                const keys = /^(?:cref|Cref)$/.test(kind) ? key.split(',').map(key => key.trim()).filter(Boolean) : [key];
                return keys.map(key => {
                    const caption = kind === 'eqref' ? `(${key})` : key;
                    return protectHTML(`<a class="tex-reference" data-tex-reference="${escapeHTML(key)}" data-tex-reference-kind="${kind}" data-tex-scope="${scope}">${escapeHTML(caption)}</a>`);
                }).join(', ');
            });
            if (inferInlineMath) text = convertInlineMath(text);
            text = window.wrapBareTeXMath ? window.wrapBareTeXMath(text) : text;
            text = protectMath(text);
            // These affect PDF line breaking/grouping, not the mathematical text.
            // Literal code and mathematics have already been protected.
            text = text.replace(/\\(?:begingroup|endgroup|sloppy|fussy)\b/g, '');
            // Reference scopes are captured; hide source boundaries before
            // escaped prose percentages become literal percent characters.
            text = text.replace(/^[ \t]*%[^\r\n]*(?:\r?\n|$)/gm, '');

            // These escapes belong to prose; retain their mathematical meanings
            // in the protected expressions above.
            text = text.replace(/\\\*/g, () => protectHTML('*'));
            // MathJax handles escaped prose dollars through processEscapes.
            // Unescaping them here would turn currency into math delimiters and
            // consume correctly delimited formulas between two prize amounts.
            text = text.replace(/\\\$/g, () => protectHTML('\\$'));
            // A literal ampersand inside a table cell must not become a column.
            text = text.replace(/\\&/g, () => protectHTML('&amp;'));
            // Literal prose braces must not be mistaken for formatting groups.
            text = text.replace(/\\([{}])/g, (match, brace) => protectHTML(brace));
            // Discard a sizing group's wrapper, including nested formatting,
            // without stripping an enclosing command's required argument.
            text = text.replace(/\{\s*\\(?:tiny|scriptsize|footnotesize|small|normalsize|large|Large|LARGE|huge|Huge)(?![A-Za-z])\s*/g,
                (match, offset, input) => /\\[A-Za-z]+\*?$/.test(input.slice(0, offset)) ? '{' : '\\textnormal{');
            // A table row ending "\\ " is a row break followed by whitespace,
            // not a prose control space. Keep both slashes for the table parser.
            text = text.replace(/\\begin\{tabular\}[\s\S]*?\\end\{tabular\}/g,
                block => block.replace(/(\\\\)[ \t]+/g, '$1\n'));
            text = proseEscapes(text);

            function parseBracedArg(input, startIdx) {
                if (input[startIdx] !== '{') return null;
                let depth = 0;
                let i = startIdx;
                for (; i < input.length; i += 1) {
                    const ch = input[i];
                    if (ch === '\\') {
                        i += 1;
                        continue;
                    }
                    if (ch === '{') {
                        depth += 1;
                    } else if (ch === '}') {
                        depth -= 1;
                        if (depth === 0) {
                            return {
                                value: input.slice(startIdx + 1, i),
                                end: i + 1
                            };
                        }
                    }
                }
                return null;
            }

            function replaceTwoArgCommand(input, command, replacer) {
                return replaceCommandArguments(input, command, 2, replacer);
            }

            function replaceCommandArguments(input, command, count, replacer) {
                const needle = '\\' + command + '{';
                let out = '';
                let i = 0;

                while (i < input.length) {
                    const idx = input.indexOf(needle, i);
                    if (idx === -1) {
                        out += input.slice(i);
                        break;
                    }
                    out += input.slice(i, idx);
                    const args = [];
                    let cursor = idx + needle.length - 1;
                    for (let argIndex = 0; argIndex < count; argIndex += 1) {
                        while (/\s/.test(input[cursor] || '') && cursor < input.length) cursor += 1;
                        const arg = parseBracedArg(input, cursor);
                        if (!arg) return out + input.slice(idx);
                        args.push(arg.value);
                        cursor = arg.end;
                    }
                    out += replacer(...args);
                    i = cursor;
                }

                return out;
            }

            // PDF/contents metadata has a separate purpose from the visible TeX
            // title. Keep the title and omit only the table-of-contents entry.
            text = replaceTwoArgCommand(text, 'texorpdfstring', title => title);
            text = replaceCommandArguments(text, 'addcontentsline', 3, () => '');
            
            // Convert LaTeX environments to HTML before escaping
            // This must happen before HTML escaping
            
            // Convert \begin{center}...\end{center} to <div style="text-align: center;">...</div>
            text = text.replace(/\\begin\{center\}([\s\S]*?)\\end\{center\}/g, '<div style="text-align: center;">$1</div>');
            text = replaceLatexCommand(text, 'centerline', '<div style="text-align: center;">', '</div>');
            text = replaceTwoArgCommand(text, 'MO', (id, title) => `<h3>MathOverflow #${id}: ${title}</h3>`);

            text = replaceTwoArgCommand(text, 'parbox', (width, content) => {
                let cssWidth = '';
                const widthTrimmed = width.trim();
                const lineWidthMatch = widthTrimmed.match(/^(\d*\.?\d+)\s*\\linewidth$/);
                if (lineWidthMatch) {
                    const percentage = Math.max(0, Math.min(100, parseFloat(lineWidthMatch[1]) * 100));
                    cssWidth = `${percentage}%`;
                } else if (/^(?:\d+(?:\.\d+)?|\.\d+)(?:em|ex|ch|rem|px|mm|cm|in|pt|pc|%)$/.test(widthTrimmed)) {
                    cssWidth = widthTrimmed;
                }
                const styleAttr = cssWidth ? ` style="max-width: ${cssWidth};"` : '';
                return `<div class="latex-parbox"${styleAttr}>${content}</div>`;
            });

            text = replaceLatexCommand(text, 'fbox', '<div class="latex-fbox">', '</div>');

            text = text.replace(/\\begin\{tabular\}([\s\S]*?)\\end\{tabular\}/g, function(match, body) {
                const input = body.trimStart();
                const spec = parseBracedArg(input, 0);
                if (!spec) return match;
                // Column modifiers such as @{} contain their own braces.
                // Skip their arguments rather than displaying the rest of the spec.
                const alignments = [];
                for (let i = 0; i < spec.value.length; i += 1) {
                    const arg = parseBracedArg(spec.value, i);
                    if (arg) { i = arg.end - 1; continue; }
                    if (spec.value[i] === '\\') {
                        const command = spec.value.slice(i).match(/^\\[A-Za-z]+/);
                        if (command) i += command[0].length - 1;
                    } else if (/[lcr]/.test(spec.value[i])) alignments.push(spec.value[i]);
                    else if (/[pmbL]/.test(spec.value[i])) alignments.push('l');
                }
                const rows = input.slice(spec.end).split(/\\\\(?:\[[^\]]*\])?/).map(row => row.trim()).filter(Boolean);
                const htmlRows = rows.map(row => {
                    const cleanRow = row.replace(/\\(?:hline|toprule|midrule|bottomrule)\b(?:\[[^\]]*\])?/g, '').trim();
                    if (!cleanRow) return '';
                    const cells = cleanRow.split('&').map(cell => cell.trim());
                    const cellHtml = cells.map((cell, idx) => {
                        const align = alignments[idx] || 'l';
                        const alignStyle = align === 'c'
                            ? 'text-align: center;'
                            : align === 'r'
                                ? 'text-align: right;'
                                : 'text-align: left;';
                        return `<td style="${alignStyle}">${cell}</td>`;
                    }).join('');
                    return `<tr>${cellHtml}</tr>`;
                }).filter(Boolean).join('');
                return `<table class="latex-table"><tbody>${htmlRows}</tbody></table>`;
            });
            
            // Keep nested lists attached to their parent item and show optional
            // item labels such as \item[(i)] without exposing TeX commands.
            const listStack = [];
            text = text.replace(/\\begin\{(itemize|enumerate|description)\}(?:\[[^\]]*\])?|\\end\{(itemize|enumerate|description)\}|\\item\b(?:\[([^\]]*)\])?\s*/g,
                function(match, start, end, label) {
                    if (start) {
                        const tag = start === 'enumerate' ? 'ol' : 'ul';
                        listStack.push({ environment: start, tag, hasItem: false });
                        return `<${tag}>`;
                    }
                    const current = listStack[listStack.length - 1];
                    // Imported fragments occasionally begin with a lone item.
                    // Preserve its label and text as a paragraph.
                    if (!current) return end ? match : `\n\n${label ? label + ' ' : ''}`;
                    if (end && current.environment !== end) return match;
                    if (end) {
                        listStack.pop();
                        return `${current.hasItem ? '</li>' : ''}</${current.tag}>`;
                    }
                    const closeItem = current.hasItem ? '</li>' : '';
                    current.hasItem = true;
                    return `${closeItem}<li>${label ? label + ' ' : ''}`;
                });
            
            // Convert \begin{quote}...\end{quote} to <blockquote>...</blockquote>
            text = text.replace(/\\begin\{quote\}([\s\S]*?)\\end\{quote\}/g, '<blockquote>$1</blockquote>');
            
            // Convert \begin{verbatim}...\end{verbatim} to <pre>...</pre>
            text = text.replace(/\\begin\{verbatim\}([\s\S]*?)\\end\{verbatim\}/g, '<pre>$1</pre>');
            
            // Convert theorem-like environments (theorem, lemma, definition, proof, etc.)
            for (const [environment, css, kind] of [
                ['theorem', 'theorem', 'Theorem'], ['lemma', 'lemma', 'Lemma'],
                ['claim', 'lemma', 'Claim'], ['proposition', 'proposition', 'Proposition'],
                ['corollary', 'corollary', 'Corollary'], ['remark', 'remark', 'Remark'],
                ['definition', 'definition', 'Definition'], ['construction', 'definition', 'Construction'],
                ['question', 'definition', 'Question'], ['conjecture', 'theorem', 'Conjecture'],
                ['warning', 'remark', 'Warning'], ['example', 'definition', 'Example'],
                ['inputthm', 'theorem', 'Input']
            ]) {
                const pattern = new RegExp('\\\\begin\\{' + environment + '\\}(?:\\[([\\s\\S]*?)\\])?([\\s\\S]*?)\\\\end\\{' + environment + '\\}', 'g');
                text = text.replace(pattern, (match, title, body) => {
                    const caption = title ? ' (' + protectHTML('<span class="tex-theorem-title">') + title + protectHTML('</span>') + ')' : '';
                    return `<div class="${css}"><strong>${kind}${caption}:</strong> ${body}</div>`;
                });
            }
            // Separate markers also support a lemma proof nested inside a longer proof.
            text = text.replace(/\\begin\{proof\}(\[.*?\])?/g, '<div class="proof"><em>Proof$1:</em> ');
            text = text.replace(/\\end\{proof\}/g, ' ∎</div>');
            text = text.replace(/\\begin\{thebibliography\}\{[^}]*\}([\s\S]*?)\\end\{thebibliography\}/g, function(match, content) {
                let hasItem = false;
                const items = content.replace(/\\bibitem(?:\[([^\]]*)\])?\{([^}]*)\}/g, function(item, label, key) {
                    const prefix = hasItem ? '</li>' : '';
                    hasItem = true;
                    return `${prefix}<li><strong>[${label || key}]</strong> `;
                });
                return `<h3>References</h3><ul>${items.trim().replace(/\n{2,}/g, ' ')}${hasItem ? '</li>' : ''}</ul>`;
            });
            
            // Convert psmallmatrix to regular pmatrix (MathJax will handle it)
            text = text.replace(/\\begin\{psmallmatrix\}/g, '\\begin{pmatrix}');
            text = text.replace(/\\end\{psmallmatrix\}/g, '\\end{pmatrix}');
            
            // Handle LaTeX text formatting commands BEFORE HTML escaping
            function replaceLatexCommand(input, command, openTag, closeTag) {
                const needle = '\\' + command + '{';
                let out = '';
                let i = 0;

                while (i < input.length) {
                    const idx = input.indexOf(needle, i);
                    if (idx === -1) {
                        out += input.slice(i);
                        break;
                    }
                    out += input.slice(i, idx);

                    let j = idx + needle.length;
                    let depth = 1;

                    while (j < input.length && depth > 0) {
                        const ch = input[j];
                        if (ch === '\\') {
                            j += 2;
                            continue;
                        }
                        if (ch === '{') {
                            depth += 1;
                        } else if (ch === '}') {
                            depth -= 1;
                            if (depth === 0) {
                                break;
                            }
                        }
                        j += 1;
                    }

                    if (depth !== 0) {
                        out += input.slice(idx);
                        return out;
                    }

                    const content = input.slice(idx + needle.length, j);
                    out += typeof openTag === 'function' ? openTag(content)
                        : openTag + replaceLatexCommand(content, command, openTag, closeTag) + closeTag;
                    i = j + 1;
                }

                return out;
            }

            // Resolve spacing before unwrapping text, so adjacent commands such
            // as \\qquad\\text{and} cannot merge into a new control word.
            text = text.replace(/\\qquad\b/g, '\u2003\u2003').replace(/\\quad\b/g, '\u2003');
            text = replaceLatexCommand(text, 'emph', '<em>', '</em>');
            text = replaceLatexCommand(text, 'textbf', '<strong>', '</strong>');
            text = replaceLatexCommand(text, 'textit', '<em>', '</em>');
            text = replaceLatexCommand(text, 'underline', '<u>', '</u>');
            text = replaceLatexCommand(text, 'footnote', '(', ')');
            text = replaceLatexCommand(text, 'textnormal', '', '');
            text = replaceLatexCommand(text, 'textup', '', '');
            text = replaceLatexCommand(text, 'text', '', '');
            text = text.replace(/\{\s*\\em\s+([^{}]*)\}/g, '<em>$1</em>');
            // Markdown-style emphasis
            text = text.replace(/\\qedhere\b/g, '\\(\\square\\)');
            text = text.replace(/\\qed\b/g, '\\(\\square\\)');
            text = text.replace(/\*\*((?:(?!\n\s*\n)[^*])+?)\*\*/g, '<strong>$1</strong>');
            text = text.replace(/(^|[\s>(])\*(?=\S)((?:(?!\n\s*\n)[^*])*?\S)\*(?=$|[\s<.,;:!?)])/g, '$1<em>$2</em>');
            // Markdown headings (##, ###, ####, ...)
            text = text.replace(/^\s*(#{2,6})\s+(.+)$/gm, function(match, hashes, heading) {
                const level = Math.min(6, hashes.length);
                return `<h${level}>${heading.trim()}</h${level}>`;
            });
            
            // Remove LaTeX reference commands
            text = text.replace(/\\label\{[^}]+\}/g, '');
            text = text.replace(/\\ref\{[^}]+\}/g, '');
            text = text.replace(/\\eqref\{[^}]+\}/g, '');
            
            // Remove LaTeX spacing and formatting commands
            text = text.replace(/\\medskip/g, '');
            text = text.replace(/\\noindent/g, '');
            text = text.replace(/\\bigskip/g, '');
            text = text.replace(/\\smallskip/g, '');
            text = text.replace(/\\hfill/g, '');
            text = text.replace(/\\newblock\b/g, ' ');
            text = text.replace(/\\S(?![A-Za-z])(?:\{\})?/g, '§');
            text = text.replace(/\\par\b/g, '\n\n');
            text = text.replace(/\\hrule\b/g, '<hr>');
            text = text.replace(/\\newline\b|\\\\(?:\[[^\]]*\])?/g, '<br>');
            text = text.replace(/\\LaTeX\b(?:\{\})?/g, 'LaTeX');
            text = text.replace(/\\textasciicircum\b(?:\{\})?/g, '^');
            text = text.replace(/\\textasciitilde\b(?:\{\})?/g, () => protectHTML('~'));
            text = text.replace(/\\(?:small|normalsize|newpage)\b[ \t]*/g, '');
            text = text.replace(/\\date\{\s*\}/g, '');
            text = text.replace(/\\allowbreak\b/g, '<wbr>');
            text = text.replace(/\\dots\b/g, '…');
            
            // Replace delimiter sizing commands with \left and \right equivalents
            // These work better in MathJax than the explicit sizing commands
            text = text.replace(/\\[Bb]igg?l\s*([(\[{|])/g, '\\left$1');
            text = text.replace(/\\[Bb]igg?r\s*([)\]}|])/g, '\\right$1');
            text = text.replace(/\\[Bb]igg?l\s*\\\{/g, '\\left\\{');
            text = text.replace(/\\[Bb]igg?r\s*\\\}/g, '\\right\\}');
            text = text.replace(/\\[Bb]igg?l\s*\{/g, '\\left\\{');
            text = text.replace(/\\[Bb]igg?r\s*\}/g, '\\right\\}');
            text = text.replace(/\\left\{/g, '\\left\\{');
            text = text.replace(/\\right\}/g, '\\right\\}');
            // Remove any remaining standalone sizing commands
            text = text.replace(/\\[Bb]igg?[lr]/g, '');

            // Handle \cite{...} - convert to [ref] format
            const citationPattern = /\\cite[pt]?(?:\[([^\]]*)\])?(?:\[([^\]]*)\])?\{([^}]+)\}/g;
            // Citation notes can themselves contain a citation.
            for (let pass = 0; pass < 3; pass += 1) text = text.replace(citationPattern,
                (match, first, second, keys) => second === undefined
                    ? `[${keys}${first ? ', ' + first : ''}]`
                    : `[${first ? first + ' ' : ''}${keys}${second ? ', ' + second : ''}]`);

            // Protect each generated link, including its label, from autolinking.
            text = text.replace(/\[([^\]\n]+)\]\((https?:\/\/(?:[^\s()]|\([^()\s]*\))+)\)/g,
                (match, label, url) => protectHTML(sourceLink(url, label)));
            text = linkPlainURLs(text);

            // Replace LaTeX quotes with proper HTML entities
            text = text.replace(/``/g, '"');
            text = text.replace(/''/g, '"');
            text = text.replace(/\\textquotesingle\b(?:\{\}|[ \t]+)?/g, "'");

            // Decode prose accents generally, including authors' names. Math and
            // code have already been protected, so their commands stay literal.
            const textLetters = { o: 'ø', O: 'Ø', l: 'ł', L: 'Ł', i: 'ı', j: 'ȷ' };
            text = text.replace(/\{\\([oOlLij])\}/g, (match, letter) => textLetters[letter]);
            text = text.replace(/\\([oOlLij])(?![A-Za-z])(?:\{\}|[ \t]+)?/g,
                (match, letter) => textLetters[letter]);
            const accents = { "'": '\u0301', '`': '\u0300', '"': '\u0308',
                '^': '\u0302', '~': '\u0303', '=': '\u0304', '.': '\u0307',
                H: '\u030b', v: '\u030c', u: '\u0306', c: '\u0327', k: '\u0328', r: '\u030a' };
            for (const [command, accent] of Object.entries(accents)) {
                const escaped = command.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                const boundary = /[A-Za-z]/.test(command) ? '(?![A-Za-z])' : '';
                const pattern = new RegExp('\\\\' + escaped + boundary + '[ \\t]*(?:\\{([\\p{L}])\\}|([\\p{L}]))', 'gu');
                text = text.replace(pattern, (match, braced, plain) => {
                    const letter = (braced || plain).replace('ı', 'i').replace('ȷ', 'j');
                    return (letter + accent).normalize('NFC');
                });
            }
            // Use the character itself so later HTML escaping cannot double-escape it.
            text = text.replace(/~|&nbsp;/g, '\u00a0');
            
            // Convert LaTeX sectioning commands to HTML headings
            for (const [command, tag] of [['section', 'h2'], ['subsection', 'h3'],
                ['subsubsection', 'h4'], ['paragraph', 'h5'], ['subparagraph', 'h6']]) {
                text = replaceLatexCommand(text, command, `<${tag}>`, `</${tag}>`);
                text = replaceLatexCommand(text, command + '*', `<${tag}>`, `</${tag}>`);
            }

            // Escape HTML but preserve LaTeX
            let formatted = text
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;');

            // Restore LaTeX delimiters
            formatted = formatted
                .replace(/\\\[/g, '\\[')
                .replace(/\\\]/g, '\\]')
                .replace(/\\\(/g, '\\(')
                .replace(/\\\)/g, '\\)');
            
            // Restore the HTML tags we created from LaTeX environments
            formatted = formatted
                .replace(/&lt;div style="text-align: center;"&gt;/g, '<div style="text-align: center;">')
                .replace(/&lt;\/div&gt;/g, '</div>')
                .replace(/&lt;ul&gt;/g, '<ul>')
                .replace(/&lt;\/ul&gt;/g, '</ul>')
                .replace(/&lt;ol&gt;/g, '<ol>')
                .replace(/&lt;\/ol&gt;/g, '</ol>')
                .replace(/&lt;li&gt;/g, '<li>')
                .replace(/&lt;\/li&gt;/g, '</li>')
                .replace(/&lt;span class="latex-comment"&gt;/g, '<span class="latex-comment">')
                .replace(/&lt;\/span&gt;/g, '</span>')
                .replace(/&lt;blockquote&gt;/g, '<blockquote>')
                .replace(/&lt;\/blockquote&gt;/g, '</blockquote>')
                .replace(/&lt;br&gt;/g, '<br>')
                .replace(/&lt;hr&gt;/g, '<hr>')
                .replace(/&lt;wbr&gt;/g, '<wbr>')
                .replace(/&lt;pre&gt;/g, '<pre>')
                .replace(/&lt;\/pre&gt;/g, '</pre>')
                .replace(/&lt;div class="theorem"&gt;/g, '<div class="theorem">')
                .replace(/&lt;div class="lemma"&gt;/g, '<div class="lemma">')
                .replace(/&lt;div class="proposition"&gt;/g, '<div class="proposition">')
                .replace(/&lt;div class="corollary"&gt;/g, '<div class="corollary">')
                .replace(/&lt;div class="remark"&gt;/g, '<div class="remark">')
                .replace(/&lt;div class="definition"&gt;/g, '<div class="definition">')
                .replace(/&lt;div class="proof"&gt;/g, '<div class="proof">')
                .replace(/&lt;div class="latex-fbox"&gt;/g, '<div class="latex-fbox">')
                .replace(/&lt;div class="latex-parbox"( style="max-width: (?:\d+(?:\.\d+)?|\.\d+)(?:em|ex|ch|rem|px|mm|cm|in|pt|pc|%);")?&gt;/g, '<div class="latex-parbox"$1>')
                .replace(/&lt;\/div&gt;/g, '</div>')
                .replace(/&lt;h2&gt;/g, '<h2>')
                .replace(/&lt;\/h2&gt;/g, '</h2>')
                .replace(/&lt;h3&gt;/g, '<h3>')
                .replace(/&lt;\/h3&gt;/g, '</h3>')
                .replace(/&lt;h4&gt;/g, '<h4>')
                .replace(/&lt;\/h4&gt;/g, '</h4>')
                .replace(/&lt;h5&gt;/g, '<h5>')
                .replace(/&lt;\/h5&gt;/g, '</h5>')
                .replace(/&lt;h6&gt;/g, '<h6>')
                .replace(/&lt;\/h6&gt;/g, '</h6>')
                .replace(/&lt;strong&gt;/g, '<strong>')
                .replace(/&lt;\/strong&gt;/g, '</strong>')
                .replace(/&lt;em&gt;/g, '<em>')
                .replace(/&lt;\/em&gt;/g, '</em>')
                .replace(/&lt;u&gt;/g, '<u>')
                .replace(/&lt;\/u&gt;/g, '</u>')
                .replace(/&lt;table class="latex-table"&gt;/g, '<table class="latex-table">')
                .replace(/&lt;\/table&gt;/g, '</table>')
                .replace(/&lt;tbody&gt;/g, '<tbody>')
                .replace(/&lt;\/tbody&gt;/g, '</tbody>')
                .replace(/&lt;tr&gt;/g, '<tr>')
                .replace(/&lt;\/tr&gt;/g, '</tr>')
                .replace(/&lt;td( style="text-align: (?:left|center|right);")?&gt;/g, '<td$1>')
                .replace(/&lt;\/td&gt;/g, '</td>');

            // Use $...$ to avoid browsers that fail to render \( ... \) reliably.
            formatted = formatted
                .replace(/\\\(/g, '$')
                .replace(/\\\)/g, '$');

            // Convert line breaks to paragraphs, avoid inserting <br> inside math
            formatted = formatted
                .split(/\n{2,}/)
                .map(para => para.replace(/\n/g, ' ').trim())
                .filter(para => para.length > 0)
                .map(para => {
                    // Preserve line breaks in spans (like latex-comment)
                    if (para.includes('<span class="latex-comment">')) {
                        para = para.replace(/<\/span> <span class="latex-comment">/g, '</span><br><span class="latex-comment">');
                    }
                    if (/^<(h[1-6]|ul|ol|div|blockquote|pre|hr)\b/i.test(para)) {
                        return para;
                    }
                    const literalBlock = para.match(/^\uE000TEX(\d+)\uE001$/);
                    if (literalBlock && protectedFragments[Number(literalBlock[1])].startsWith('<pre>')) return para;
                    return '<p>' + para + '</p>';
                })
                .join('');

            // Restore after paragraph processing: blank lines inside equations or
            // literal blocks must not insert HTML into their content. A link label
            // may itself contain a protected mathematical expression.
            function restoreFragments(value) {
                return value.replace(/\uE000TEX(\d+)\uE001/g, (match, index) => {
                    const fragment = protectedFragments[Number(index)];
                    return fragment === undefined ? match : restoreFragments(fragment);
                });
            }
            formatted = restoreFragments(formatted);
            return formatted;
        }

        root.formatTeX = formatTeX;
})(typeof window !== 'undefined' ? window : globalThis);
