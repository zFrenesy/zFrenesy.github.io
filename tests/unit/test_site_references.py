import copy
import json
from html import escape
from html.parser import HTMLParser

import pytest

from rp.render.tex import _postprocess, sanitise
from rp.site.references import reference_key, resolve_references


class Elements(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tags = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def label(key="thm:main", scope="0", kind="prose"):
    return f'<span class="tex-label" data-tex-label="{escape(key, quote=True)}" data-tex-scope="{scope}" data-tex-label-kind="{kind}"></span>'


def ref(key="thm:main", scope="0", kind="ref"):
    return f'<a class="tex-reference" data-tex-reference="{escape(key, quote=True)}" data-tex-scope="{scope}" data-tex-reference-kind="{kind}">{escape(key)}</a>'


def resolve(html, **kwargs):
    params = {"document_id": "ERDOS-5-A1", "revision": "r1", "document_url": "/contributions/ERDOS-5-A1/r1/"}
    params.update(kwargs)
    return resolve_references(html, **params)


def links(result):
    return [attrs for tag, attrs in Elements(result.html).tags if tag == "a"]


def test_forward_reference_gets_stable_anchor_and_actual_theorem_title():
    source = '<p>Use ' + ref() + '.</p><div class="theorem"><strong>Theorem (<span class="tex-theorem-title">Finite case</span>):</strong> ' + label() + "Text.</div>"
    result = resolve(source)
    target = next(iter(result.targets.values()))
    assert target["caption"] == "Theorem (Finite case)"
    assert target["kind"] == "theorem" and target["revision"] == "r1"
    assert target["url"] == "/contributions/ERDOS-5-A1/r1/#" + target["anchor"]
    assert links(result)[0]["href"] == "#" + target["anchor"]
    assert ">Theorem (Finite case)</a>" in result.html
    assert not result.diagnostics


def test_same_label_in_reused_scopes_resolves_only_in_its_own_scope():
    result = resolve(label(scope="1") + ref(scope="1") + label(scope="2") + ref(scope="2") + ref(scope="0"))
    targets = list(result.targets.values())
    assert targets[0]["anchor"] != targets[1]["anchor"]
    assert [link.get("href") for link in links(result)] == ["#" + targets[0]["anchor"], "#" + targets[1]["anchor"], None]
    assert result.diagnostics[0]["code"] == "unresolved_reference"


def test_ids_do_not_depend_on_document_content_order():
    first = resolve(label("a") + label("b"))
    reordered = resolve("<h2>Added introduction</h2>" + label("b") + label("new") + label("a"))
    for key, target in first.targets.items():
        assert reordered.targets[key]["anchor"] == target["anchor"]


def test_document_and_revision_identity_are_part_of_anchors():
    first = resolve(label())
    later_revision = resolve(label(), revision="r2", document_url="/contributions/ERDOS-5-A1/r2/")
    other_doc = resolve(label(), document_id="ERDOS-5-A2")
    anchors = {next(iter(result.targets.values()))["anchor"] for result in [first, later_revision, other_doc]}
    assert len(anchors) == 3
    assert json.loads(next(iter(first.targets))) == ["ERDOS-5-A1", "r1", "0", "thm:main"]


def test_duplicate_labels_have_unique_anchors_but_no_reference_target():
    source = label() + ref() + label()
    result = resolve(source)
    target = next(iter(result.targets.values()))
    assert target["ambiguous"] and target["anchor"] is None and target["url"] is None
    assert len(target["anchors"]) == len(set(target["anchors"])) == 2
    ids = [attrs["id"] for tag, attrs in Elements(result.html).tags if "id" in attrs]
    assert ids == target["anchors"]
    assert "href" not in links(result)[0]
    assert "multiple labels" in links(result)[0]["title"]
    assert {d["code"] for d in result.diagnostics} == {"duplicate_label", "ambiguous_reference"}


def test_local_ambiguity_does_not_fall_through_to_an_external_target():
    prior = resolve(label(), document_id="prior")
    result = resolve(label() + label() + ref(), external_targets=prior.targets)
    assert "href" not in links(result)[0]


def test_only_explicit_external_targets_can_resolve_missing_labels():
    prior = resolve('<div class="lemma"><strong>Lemma 4:</strong>' + label() + "</div>",
                    document_id="PRIOR-A1", revision="r3", document_url="/contributions/PRIOR-A1/r3/")
    missing = resolve(ref())
    assert "href" not in links(missing)[0]
    snapshot = copy.deepcopy(prior.targets)
    resolved = resolve(ref(), external_targets=prior.targets)
    assert prior.targets == snapshot  # A consumer cannot rewrite an earlier revision's manifest.
    assert links(resolved)[0]["href"] == next(iter(prior.targets.values()))["url"]
    assert "Lemma 4 · PRIOR-A1 · r3</a>" in resolved.html
    assert not resolved.targets and not resolved.diagnostics


def test_local_target_takes_precedence_over_explicit_external_target():
    prior = resolve(label(), document_id="prior")
    result = resolve(label() + ref(), external_targets=prior.targets)
    assert links(result)[0]["href"] == "#" + next(iter(result.targets.values()))["anchor"]


def test_multiple_external_versions_remain_ambiguous():
    first = resolve(label(), revision="r1")
    second = resolve(label(), revision="r2")
    result = resolve(ref(), external_targets={**first.targets, **second.targets})
    assert "href" not in links(result)[0]
    assert result.diagnostics[0]["code"] == "ambiguous_reference"


def test_external_ambiguous_manifest_entry_remains_ambiguous():
    duplicate = resolve(label() + label())
    result = resolve(ref(), external_targets=duplicate.targets)
    assert "href" not in links(result)[0]
    assert result.diagnostics[0]["code"] == "ambiguous_reference"


def test_explicit_target_mapping_can_use_scope_and_label_keys():
    prior = next(iter(resolve(label(), document_id="prior").targets.values()))
    result = resolve(ref(), external_targets={("0", "thm:main"): prior})
    assert links(result)[0]["href"] == prior["url"]


def test_unresolved_reference_stays_visible_and_loses_any_stale_href():
    source = ref("missing").replace("<a ", '<a href="/old/#wrong" target="_blank" ')
    result = resolve(source)
    link = links(result)[0]
    assert "href" not in link and "target" not in link
    assert "missing</a>" in result.html and "not present" in link["title"]


def test_formula_labels_link_before_math_without_invented_numbering():
    result = resolve(label("eq:x", kind="math") + r"\begin{align}x=1\tag{7}\\y=2\tag{8}\end{align}" + ref("eq:x", kind="eqref"))
    target = next(iter(result.targets.values()))
    assert target["caption"] == "eq:x" and target["kind"] == "equation"
    assert ">(eq:x)</a>" in result.html and links(result)[0]["href"] == "#" + target["anchor"]
    assert r"\tag{7}" in result.html and r"\tag{8}" in result.html


def test_label_and_caption_payloads_are_escaped_and_never_become_attributes():
    key = '\"><img src=x onerror=alert(1)> & \'x'
    result = resolve(label(key) + ref(key))
    parsed = Elements(result.html)
    assert [tag for tag, _ in parsed.tags] == ["span", "a"]
    assert all("onerror" not in attrs for _, attrs in parsed.tags)
    target = next(iter(result.targets.values()))
    assert target["label"] == key
    assert "<img" not in result.html and "&lt;img" in result.html
    assert links(result)[0]["href"] == "#" + target["anchor"]


@pytest.mark.parametrize("url", ["javascript:alert(1)", "//evil.example/x", "https:\\evil.example/x", " https://example.org/x", "/\n/evil.example/x"])
def test_unsafe_new_link_destinations_are_rejected(url):
    with pytest.raises(ValueError, match="URL"):
        resolve(label(), document_url=url)
    target = next(iter(resolve(label()).targets.values())) | {"url": url}
    result = resolve(ref(), external_targets={"bad": target})
    assert "href" not in links(result)[0]
    assert result.diagnostics[0]["code"] == "invalid_external_target"


def test_code_and_fallback_text_never_allocate_or_resolve_labels():
    result = resolve('<pre class="tex-source-box mathjax-ignore">' + label() + ref() + "</pre>" + ref())
    assert not result.targets
    assert all("href" not in link for link in links(result))
    assert len(result.diagnostics) == 1


def test_source_boxing_preserves_label_markers_outside_the_literal_block():
    boxed, count, _ = _postprocess("<p>" + label() + r"\unsupported{still readable}" + "</p><p>" + ref() + "</p>")
    assert count == 1
    assert boxed.index('data-tex-label="thm:main"') < boxed.index("<pre")
    result = resolve(boxed)
    target = next(iter(result.targets.values()))
    assert links(result)[0]["href"] == "#" + target["anchor"]
    assert "unsupported" in result.html


def test_repeated_resolution_is_idempotent_and_preserves_math_entities():
    source = sanitise("<p>" + label() + ref() + r" $x&lt;y$ &amp; text." + "</p>")
    first = resolve(source)
    second = resolve(first.html)
    assert second == first
    assert "$x&lt;y$ &amp; text." in second.html


def test_reference_key_is_unambiguous_with_delimiters_and_unicode():
    assert reference_key("a:b", "r1", "0", "é:x") != reference_key("a", "b:r1", "0", "é:x")
    assert json.loads(reference_key("a", "r1", "0", "é:x")) == ["a", "r1", "0", "é:x"]
