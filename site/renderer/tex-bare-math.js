// Recover complete, recognizable TeX atoms in otherwise unmarked prose.
// Call after protecting existing math, links and code, before prose unescaping.
(function (host) {
    const symbols = new Set((
        'alpha beta gamma delta epsilon varepsilon zeta eta theta vartheta iota kappa lambda mu nu xi pi varpi rho varrho sigma varsigma tau upsilon phi varphi chi psi omega ' +
        'Gamma Delta Theta Lambda Xi Pi Sigma Upsilon Phi Psi Omega aleph beth ell hbar infty emptyset varnothing prime nabla partial wp Re Im ' +
        'le leq ge geq neq ne in notin ni subset subseteq supset supseteq equiv sim simeq approx asymp propto parallel mid nmid perp prec succ preceq succeq ll gg ' +
        'times div cdot ast star circ bullet cap cup setminus smallsetminus oplus otimes odot wedge vee land lor ' +
        'to mapsto leftarrow rightarrow leftrightarrow Leftarrow Rightarrow Leftrightarrow hookrightarrow uparrow downarrow ' +
        'sum prod coprod bigcup bigcap bigoplus bigotimes int iint iiint oint lim limsup liminf sup inf max min gcd lcm det log ln exp sin cos tan arctan deg dim ker rank Pr ' +
        'dots cdots ldots vdots ddots lceil rceil lfloor rfloor langle rangle lvert rvert lVert rVert exists forall pm gtrsim square'
    ).split(' '));
    const oneArgument = new Set(('mathbb mathcal mathfrak mathrm mathbf mathit mathsf mathtt boldsymbol overline bar hat widehat tilde widetilde vec dot ddot sqrt pmod operatorname').split(' '));
    const twoArguments = new Set(('frac dfrac tfrac binom dbinom tbinom overset underset').split(' '));
    const functions = new Set(('alpha beta gamma delta epsilon theta kappa lambda mu nu pi rho sigma phi chi psi omega Gamma Delta Theta Lambda Xi Pi Sigma Upsilon Phi Psi Omega max min gcd lcm det log ln exp sin cos tan arctan deg dim ker rank Pr operatorname').split(' '));
    const proseWords = /\b(?:a[nst]|at|be|by|do|if|in|is|it|of|on|or|so|to|up|we)\b/i;
    const privateCharacter = /[\uE000-\uF8FF]/;
    const word = /[A-Za-z]/;

    function wrapBareTeXMath(input) {
        if (!input || !input.includes('\\')) return input;
        const pieces = [];
        const white = index => {
            while (/[ \t]/.test(input[index] || '')) index += 1;
            return index;
        };
        const paragraphEnd = index => {
            const end = input.indexOf('\n\n', index);
            return end < 0 ? input.length : end;
        };
        const commandAt = index => /^\\([A-Za-z]+)/.exec(input.slice(index));
        const recognized = command => symbols.has(command) || oneArgument.has(command) || twoArguments.has(command);

        function groupAt(index, open = '{', close = '}') {
            if (input[index] !== open) return null;
            const stack = [close];
            const start = index;
            for (index += 1; index < input.length; index += 1) {
                const character = input[index];
                if (privateCharacter.test(character) || input.slice(index, index + 2) === '\n\n') return null;
                if (character === '\\') { index += 1; continue; }
                if (character === '{') stack.push('}');
                else if (open !== '{' && character === '(') stack.push(')');
                else if (open !== '{' && character === '[') stack.push(']');
                else if (character === stack[stack.length - 1]) {
                    stack.pop();
                    if (!stack.length) return { start, end: index + 1, content: input.slice(start + 1, index) };
                } else if (open !== '{' && /[)}\]]/.test(character)) return null;
            }
            return null;
        }

        // Required TeX arguments are explicit mathematical syntax. Optional
        // function parentheses also need to look like variables, not a sentence.
        function mathematicalContent(content, optional = false, offset = 0) {
            if (!content.trim() || privateCharacter.test(content) || /[<>]\/?[A-Za-z][^>]*>/.test(content)) return false;
            let plain = content;
            const commands = /\\([A-Za-z]+|.)/g;
            let match;
            while ((match = commands.exec(content))) {
                if (!recognized(match[1]) && !/^[,;!: {}%#&_|]$/.test(match[1])) return false;
                if (recognized(match[1])) {
                    const nested = atomAt(offset + match.index);
                    if (!nested || !nested.valid || nested.end > offset + content.length) return false;
                    // atomAt has validated its arguments recursively already.
                    commands.lastIndex = nested.end - offset;
                }
            }
            if (optional) {
                plain = plain.replace(/\\[A-Za-z]+/g, '');
                if (/[A-Za-z]{3,}/.test(plain) || proseWords.test(plain)) return false;
            }
            return !/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(content);
        }

        function argumentAt(index, allowSingle, requireBoundary = true) {
            index = white(index);
            const group = groupAt(index);
            if (group) return mathematicalContent(group.content, false, group.start + 1) ? group.end : null;
            if (!allowSingle || input[index] === '{' || privateCharacter.test(input[index] || '')) return null;
            if (/[A-Za-z0-9]/.test(input[index] || '')
                && (!requireBoundary || !word.test(input[index + 1] || ''))) return index + 1;
            const command = commandAt(index);
            if (command && symbols.has(command[1])) return index + command[0].length;
            return null;
        }

        function scriptsAfter(index) {
            const seen = new Set();
            for (;;) {
                const start = white(index);
                if (input[start] !== '_' && input[start] !== '^') return { end: index, valid: true };
                if (seen.has(input[start])) return { end: paragraphEnd(start), valid: false };
                seen.add(input[start]);
                const end = argumentAt(start + 1, true);
                if (end === null) return { end: paragraphEnd(start), valid: false };
                index = end;
            }
        }

        function atomAt(index) {
            const match = commandAt(index);
            if (!match || !recognized(match[1])) return null;
            const name = match[1];
            let end = index + match[0].length;
            if (name === 'sqrt' && input[white(end)] === '[') {
                const rootIndex = groupAt(white(end), '[', ']');
                if (!rootIndex || !mathematicalContent(rootIndex.content, false, rootIndex.start + 1)) return { end: paragraphEnd(end), valid: false };
                end = rootIndex.end;
            }
            const count = twoArguments.has(name) ? 2 : oneArgument.has(name) ? 1 : 0;
            for (let argument = 0; argument < count; argument += 1) {
                // TeX accepts \frac12 and \frac ab as two single-token
                // arguments. Require a boundary after the last token so a
                // prose word such as "something" cannot become a fraction.
                const next = argumentAt(end, name !== 'operatorname', !(count === 2 && argument === 0));
                if (next === null) return { end: paragraphEnd(end), valid: false };
                end = next;
            }
            const scripted = scriptsAfter(end);
            if (!scripted.valid) return scripted;
            end = scripted.end;
            if (functions.has(name) && input[white(end)] === '(') {
                const parentheses = groupAt(white(end), '(', ')');
                if (parentheses && mathematicalContent(parentheses.content, true, parentheses.start + 1)) end = parentheses.end;
            }
            return { end, valid: true };
        }

        function add(text, math = false) {
            const previous = pieces[pieces.length - 1];
            if (previous && previous.math === math) previous.text += text;
            else pieces.push({ text, math });
        }

        for (let index = 0; index < input.length;) {
            // Preserve previously protected fragments and explicit delimiters.
            const token = /^[\uE000-\uF8FF][^\uE000-\uF8FF]*[\uE000-\uF8FF]/.exec(input.slice(index));
            if (token) { add(token[0]); index += token[0].length; continue; }
            const environment = /^\\begin\{((?:verbatim|equation|align|alignat|gather|multline|flalign|eqnarray|math|displaymath)\*?)\}[\s\S]*?\\end\{\1\}/.exec(input.slice(index));
            if (environment) { add(environment[0]); index += environment[0].length; continue; }
            const literal = /^(?:<code\b[^>]*>[\s\S]*?<\/code>|<pre\b[^>]*>[\s\S]*?<\/pre>|\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\]|\$\$[\s\S]*?\$\$|\$(?:\\.|[^$\\])*?\$)/.exec(input.slice(index));
            if (literal) { add(literal[0]); index += literal[0].length; continue; }
            if (/^\\[^A-Za-z]/.test(input.slice(index))) {
                add(input.slice(index, index + 2)); index += 2; continue;
            }

            // An explicit script on one Latin variable can contain a raw macro:
            // H_\kappa and S_{\alpha,\beta} are complete local TeX atoms.
            if (/[A-Za-z0-9]/.test(input[index]) && !/[A-Za-z0-9_]/.test(input[index - 1] || '')
                && /[_^]/.test(input[index + 1] || '')) {
                const scripted = scriptsAfter(index + 1);
                const atom = input.slice(index, scripted.end);
                if (!scripted.valid) { add(atom); index = scripted.end; continue; }
                if (/\\[A-Za-z]+/.test(atom)) { add(atom, true); index = scripted.end; continue; }
            }

            // The prose renderer already displays a standalone \dots as an
            // ellipsis; keep that established behavior outside complete atoms.
            const atom = /^\\dots\b/.test(input.slice(index)) ? null : atomAt(index);
            if (atom) { add(input.slice(index, atom.end), atom.valid); index = atom.end; continue; }
            const command = commandAt(index);
            if (command) {
                // Unknown commands may take literal/code arguments. Never render
                // isolated commands inside those arguments or broken formulas.
                let end = index + command[0].length;
                if (command[1] === 'left' || command[1] === 'right') end = paragraphEnd(end);
                while (input[white(end)] === '{' || input[white(end)] === '[') {
                    const start = white(end), open = input[start], group = groupAt(start, open, open === '{' ? '}' : ']');
                    if (!group) { end = paragraphEnd(start); break; }
                    end = group.end;
                }
                add(input.slice(index, end)); index = end; continue;
            }
            add(input[index]); index += 1;
        }
        return pieces.map(piece => piece.math ? '\\(' + piece.text + '\\)' : piece.text).join('');
    }

    host.wrapBareTeXMath = wrapBareTeXMath;
    if (typeof module !== 'undefined' && module.exports) module.exports = wrapBareTeXMath;
})(typeof window !== 'undefined' ? window : globalThis);
