import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from rp.render import tex
from rp.render.tex import Prepared, TexRenderer, prepare, sanitise

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("suite", ["test_tex_renderer.js", "test_tex_bare_math.js"])
def test_ported_legacy_regression_suites_pass(suite):
    proc = subprocess.run(["node", str(ROOT / "tests" / "renderer" / suite)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr[-2000:]


def test_extracted_formatter_matches_recorded_provenance():
    provenance = json.loads((ROOT / "site" / "renderer" / "PROVENANCE.json").read_text())
    source = (ROOT / "site" / "renderer" / "format-tex.js").read_text()
    body = source[source.index("        function formatTeX("):source.index("\n        root.formatTeX = formatTeX;")].rstrip() + "\n"
    assert "sha256:" + hashlib.sha256(body.encode()).hexdigest() == provenance["files"]["format-tex.js"]["body_sha256"]


def render(text, **flags):
    return TexRenderer().render_many({"d": Prepared(text, **flags)})["d"]


def test_basic_rendering_keeps_maths_for_mathjax():
    result = render("\\section{Main}\nLet $x^2$ be 50\\%.\n\n\\begin{theorem}[Key]Text.\\end{theorem}")
    assert "<h2>Main</h2>" in result.html
    assert "$x^2$" in result.html
    assert result.has_math and result.source_boxes == 0


def test_unconverted_environment_becomes_a_source_box():
    result = render("Before.\n\n\\begin{tikzpicture}\\draw (0,0) -- (1,1);\\end{tikzpicture}\n\nAfter $y$.")
    assert result.source_boxes == 1
    assert 'class="tex-source-box mathjax-ignore"' in result.html
    assert "After $y$." in result.html
    assert "tikzpicture" in result.leftover_commands or "begin" in result.leftover_commands


def test_display_maths_environments_are_not_boxed():
    result = render("We have\n\\begin{align}a &= b \\\\ c &= d\\end{align}\nand done.")
    assert result.source_boxes == 0


@pytest.mark.parametrize(
    "dirty, absent",
    [
        ('<p onclick="x()">a</p>', "onclick"),
        ("<script>alert(1)</script><p>a</p>", "<script"),
        ('<a href="javascript:alert(1)">a</a>', "javascript:"),
        ('<img src="https://tracker.example/x.png">', "<img"),
        ('<div style="position:fixed;max-width:80%">a</div>', "position"),
        ('<iframe src="https://example.org"></iframe>', "<iframe"),
    ],
)
def test_sanitiser_removes_active_content(dirty, absent):
    assert absent not in sanitise(dirty)


def test_links_get_safe_attributes():
    html = sanitise('<a href="https://example.org/x" target="_self" rel="opener">x</a>')
    assert 'rel="noopener noreferrer nofollow ugc"' in html
    assert 'referrerpolicy="no-referrer"' in html
    assert 'target="_blank"' in html


def test_labels_are_collected():
    result = render("\\begin{lemma}\\label{lem:key}Text.\\end{lemma}\n\n$$x\\label{eq:one}$$")
    assert "lem:key" in result.labels


def test_openai_scope_is_split_and_rendered_separately():
    content = (
        "% TOP_PROBLEM: {}\n% FIRST_POSTED: 2026-10-06\n% ATTEMPT_STATUS: unresolved\n% OPENAI_CLAIM: {}\n"
        "\\section*{Claim}\nBody text.\n\\subsection*{Scope relative to this problem}\nOnly the case $n=2$.\n"
        "\\subsection*{Outline}\nMore.\n"
    )
    prepared = prepare("top_openai", content)
    assert prepared.scope == "Only the case $n=2$."
    assert "Scope relative" not in prepared.text and "OPENAI_CLAIM" not in prepared.text
    result = TexRenderer().render_many({"o": prepared})["o"]
    assert "$n=2$" in result.scope_html


def test_reused_writeup_preserves_collection():
    content = (
        '% COLLECTION_METADATA: {"schema_version": 1, "kind": "reused_writeup", "independently_reviewed": false, '
        '"primary_source": "attacks/erdos/gpt_pro_5.2/1.tex", "source_paths": ["attacks/erdos/gpt_pro_5.2/1.tex"], '
        '"source_model": "gpt_pro_5.2", "source_completion": null, "source_claim": "unresolved"}\nText.\n'
    )
    prepared = prepare("erdos_attempt", content)
    assert prepared.preserve_collection and not prepared.text.startswith("% COLLECTION_METADATA")


def test_economics_statement_uses_the_economics_normaliser():
    content = "% BEGIN ECONOMICS STATEMENT\n\\subsection*{Statement}\n{\\sffamily Find $x$.}\n% END ECONOMICS STATEMENT\n"
    prepared = prepare("economics_statement", content)
    assert prepared.economics and not prepared.infer_inline_math
    result = TexRenderer().render_many({"e": prepared})["e"]
    assert "sffamily" not in result.html and "$x$" in result.html


def test_cache_avoids_rerendering(tmp_path, monkeypatch):
    renderer = TexRenderer(cache_dir=tmp_path)
    first = renderer.render_many({"a": Prepared("Hello $x$.")})["a"]

    def boom(requests):
        if requests:
            raise AssertionError("cache miss")
        return {}

    monkeypatch.setattr(renderer, "_run", boom)
    assert renderer.render_many({"a": Prepared("Hello $x$.")})["a"] == first


def test_renderer_failure_falls_back_to_escaped_source(monkeypatch):
    renderer = TexRenderer()
    monkeypatch.setattr(renderer, "_run", lambda requests: {r["id"]: {"id": r["id"], "error": "timeout"} for r in requests})
    result = renderer.render_many({"a": Prepared("<b>\\bad</b>")})["a"]
    assert result.error == "timeout"
    assert "&lt;b&gt;" in result.html and "tex-source-box" in result.html


def test_unknown_kind():
    with pytest.raises(ValueError):
        prepare("pdf", "")


def test_report_aggregates():
    results = {"a": tex.Rendered("<p>x</p>"), "b": tex.Rendered("<pre>y</pre>", source_boxes=2, leftover_commands=("foo", "foo"))}
    rep = tex.report(results)
    assert rep["documents_with_source_boxes"] == 1 and rep["top_leftover_commands"] == [("foo", 2)]
