// Run with: node tests/renderer/test_tex_bare_math.js
// Ported unchanged from mehmetmars7/Erdosproblems-llm-hunter@b1f6331 except for the require path.
const assert = require('node:assert/strict');
const wrap = require('../../site/renderer/tex-bare-math.js');
const tex = String.raw;

assert.equal(wrap(tex`A graph has \chi(G[X])\le\aleph_0.`), tex`A graph has \(\chi(G[X])\le\aleph_0\).`);
assert.equal(wrap(tex`For every X\subseteq V and \omega_2^2.`), tex`For every X\(\subseteq\) V and \(\omega_2^2\).`);
assert.equal(wrap(tex`\mathbb N, \mathbb{Z}_{\ge 0}, and \frac{a}{b}.`), tex`\(\mathbb N\), \(\mathbb{Z}_{\ge 0}\), and \(\frac{a}{b}\).`);
assert.equal(wrap(tex`Take \bigcup_{m\in\mathbb N} and \rho(1/\alpha).`), tex`Take \(\bigcup_{m\in\mathbb N}\) and \(\rho(1/\alpha)\).`);
assert.equal(wrap(tex`H_\kappa and S_{\alpha,\beta} and n^\alpha.`), tex`\(H_\kappa\) and \(S_{\alpha,\beta}\) and \(n^\alpha\).`);
assert.equal(wrap(tex`\sqrt[3]{a+b} and \gcd(n,n+1).`), tex`\(\sqrt[3]{a+b}\) and \(\gcd(n,n+1)\).`);
assert.equal(wrap(tex`\frac{a+\sqrt{b}}{\frac{c}{d}}`), tex`\(\frac{a+\sqrt{b}}{\frac{c}{d}}\)`);
for (const atom of [tex`\frac12`, tex`\frac1p`, tex`\frac ab`, tex`\frac a b`, tex`\frac1{n_i}`,
    tex`\frac{\frac12}{\frac ab}`, tex`\frac\alpha\beta`, tex`\dfrac12`, tex`\tfrac1p`, tex`\binom nk`]) {
    assert.equal(wrap(atom), tex`\(${atom}\)`, atom);
}
const nested = tex`\frac{a}{`.repeat(40) + 'b' + '}'.repeat(40);
assert.equal(wrap(nested), tex`\(${nested}\)`);
// A missing dollar delimiter followed by many escapes must not backtrack
// exponentially while checking whether it is an existing literal formula.
const unmatchedDollar = '$unfinished ' + tex`\unknown `.repeat(100);
assert.equal(wrap(unmatchedDollar), unmatchedDollar);
assert.equal(wrap(tex`\chi (the chromatic number) and \rho (in this case).`), tex`\(\chi\) (the chromatic number) and \(\rho\) (in this case).`);
assert.equal(wrap(tex`\exists x \forall y \pm z \gtrsim 1 \square`), tex`\(\exists\) x \(\forall\) y \(\pm\) z \(\gtrsim\) 1 \(\square\)`);
assert.equal(wrap(tex`\dots and \sum_{i=1,\dots,n}`), tex`\dots and \(\sum_{i=1,\dots,n}\)`);

for (const literal of [
    tex`\frac{a}`, tex`\frac{a}{`, tex`\sqrt`, tex`\alpha_`, tex`\alpha_{n`,
    tex`\mathbb Natural numbers`, tex`\unknown{\alpha}`, tex`\newcommand{\foo}{\alpha+\beta}`,
    tex`\left(\alpha+\beta\right)`, tex`\begin{verbatim}{\alpha}\end{verbatim}`,
    tex`\frac{a}{\sqrt}`, tex`\frac{\alpha_}{b}`, tex`\frac{\unknown}{b}`,
    tex`\frac something`, tex`\frac abc`, tex`\frac a`, tex`\frac1`, tex`\frac1word`,
    tex`\begin{verbatim}\alpha\end{verbatim}`, tex`\begin{align}\alpha&=\beta\end{align}`,
    tex`\\alpha`, tex`\url{https://example.org/\alpha}`,
    tex`$\aleph_1$`, tex`\(\chi(G)\)`, tex`\[\frac{a}{b}\]`, tex`$$\omega_2$$`,
    tex`<code>\aleph_2</code>`, tex`<pre>\frac{a}{b}</pre>`,
    'No commands in A_{k,x} or ordinary prose.',
    '\uE000TEX17\uE001',
]) assert.equal(wrap(literal), literal, literal);
const token = '\uE000TEX17\uE001';
assert.equal(wrap(tex`\alpha and ${token} and \beta`), tex`\(\alpha\) and ${token} and \(\beta\)`);
assert.equal(wrap(tex`\chi(${token})`), tex`\(\chi\)(${token})`);
assert.equal(wrap(tex`\frac{${token}}{b}`), tex`\frac{${token}}{b}`);
console.log('Conservative bare TeX atoms, balanced arguments, prose boundaries and protected literals passed.');
