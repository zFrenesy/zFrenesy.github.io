// normalizedStatement and its helpers, extracted unchanged from the legacy
// mehmetmars7/Erdosproblems-llm-hunter @ b1f6331 docs/economics-detail.js (Apache-2.0).
// The legacy Economics pages applied it before formatTeX. Only this wrapper is new.
(function (root) {
    function normalizedReferences(text) {
        return String(text || '')
            .replace(/\\Problemref\{([^}]+)\}/g, '\\ref{problem:$1}')
            .replace(/\\JELref\{([^}]+)\}\{([^}]+)\}/g, '\\ref{jel:$1:$2}');
    }

    function bracedGroup(text, start) {
        while (/\s/.test(text[start] || '') && start < text.length) start += 1;
        if (text[start] !== '{') return null;
        let depth = 1;
        for (let end = start + 1; end < text.length; end += 1) {
            if (text[end] === '\\') { end += 1; continue; }
            if (text[end] === '{') depth += 1;
            if (text[end] === '}' && --depth === 0) {
                return { content: text.slice(start + 1, end), end: end + 1 };
            }
        }
        return null;
    }

    function replaceCommand(text, name, arity, renderCommand) {
        const pattern = new RegExp('\\\\' + name + '(?![A-Za-z])', 'g');
        let output = '', cursor = 0, match;
        while ((match = pattern.exec(text))) {
            const args = [];
            let end = pattern.lastIndex;
            for (let index = 0; index < arity; index += 1) {
                const group = bracedGroup(text, end);
                if (!group) break;
                args.push(group.content);
                end = group.end;
            }
            if (args.length !== arity) continue;
            output += text.slice(cursor, match.index) + renderCommand(...args);
            cursor = end;
            pattern.lastIndex = end;
        }
        return output + text.slice(cursor);
    }

    function normalizedStatement(text) {
        const protectedFragments = [];
        const protect = fragment => {
            protectedFragments.push(fragment);
            return '\uE110ECON' + (protectedFragments.length - 1) + '\uE111';
        };
        // PDF presentation commands are prose metadata. Keep every mathematical
        // expression and literal source example intact while unwrapping that metadata.
        let source = String(text || '')
            .replace(/\\begin\{(verbatim\*?|Verbatim|Code)\}(?:\[[^\]]*\])?[\s\S]*?\\end\{\1\}/g, protect)
            .replace(/\\verb\*?([^\w\s])([^\n]*?)\1/g, protect)
            .replace(/\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|(?<!\\)\$\$[\s\S]*?(?<!\\)\$\$|(?<!\\)\$(?!\$)(?:\\[\s\S]|[^$\\])*?\$|\\begin\{((?:equation|align|alignat|gather|multline|flalign|eqnarray|math|displaymath)\*?)\}[\s\S]*?\\end\{\1\}/g, protect);
        source = replaceCommand(source, 'ensuremath', 1, content => protect('$' + content + '$'));
        function unwrapStyles(input) {
            let output = '';
            for (let index = 0; index < input.length; index += 1) {
                if (input[index] === '{' && input[index - 1] !== '\\' &&
                        /^\s*\\(?:sffamily|rmfamily|small|footnotesize|scriptsize|normalsize|large|Large|raggedright|color)\b/.test(input.slice(index + 1))) {
                    const group = bracedGroup(input, index);
                    if (group) {
                        output += unwrapStyles(group.content);
                        index = group.end - 1;
                        continue;
                    }
                }
                output += input[index];
            }
            return output;
        }
        source = unwrapStyles(source)
            .replace(/\\(?:sffamily|rmfamily|raggedright|footnotesize|scriptsize|tiny|small|normalsize|large|Large|LARGE|huge|Huge|bfseries|mdseries|upshape|itshape|scshape|phantomsection)\b[ \t]*/g, '')
            .replace(/\\color\{[^}]+\}[ \t]*/g, '');
        source = replaceCommand(source, 'entrymeta', 3, (id, subject, status) =>
            '\\textbf{\\texttt{' + id + '}}\\quad|\\quad ' + subject + '\\par ' + status + '\\par');
        source = replaceCommand(source, 'hypertarget', 2, (key, caption) => '\\label{' + key + '}' + caption);
        source = replaceCommand(source, 'nolinkurl', 1, content => '\\texttt{' + content + '}');
        source = source.replace(/(?:page\s*~?\s*)?\\pageref\{([^}]+)\}/g, '\\ref{$1}')
            // The source double-escaped an ampersand in this journal's prose name.
            .replace(/\\textbackslash\{\}(?=\\&)/g, '');
        source = normalizedReferences(source);
        return source.replace(/\uE110ECON(\d+)\uE111/g, (match, index) => protectedFragments[Number(index)]);
    }

    root.normalizedEconomicsStatement = normalizedStatement;
})(typeof window !== 'undefined' ? window : globalThis);
