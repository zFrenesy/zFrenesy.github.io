"""Resolve references in sanitized renderer output before publishing HTML.

This module does not interpret TeX or invent theorem/equation numbers. Labels
are scoped to a document, its immutable revision, and an imported source scope.
Only explicitly supplied external targets may satisfy a missing local label.
The JSON-ready target mapping can be saved as the site's reference manifest.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from html import escape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

__all__ = ["ReferenceResult", "reference_key", "resolve_references"]

_VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"})
_THEOREMS = frozenset({"theorem", "lemma", "proposition", "corollary", "claim", "definition", "remark"})
_HEADINGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})


@dataclass(frozen=True)
class ReferenceResult:
    html: str
    targets: dict[str, dict[str, Any]]
    diagnostics: tuple[dict[str, Any], ...]


@dataclass(eq=False)
class _Node:
    tag: str | None = None
    attrs: dict[str, str | None] = field(default_factory=dict)
    data: str = ""
    children: list[_Node] = field(default_factory=list)
    parent: _Node | None = field(default=None, repr=False)


class _Fragment(HTMLParser):
    def __init__(self, source: str):
        super().__init__(convert_charrefs=True)
        self.root = _Node(tag="")
        self.stack = [self.root]
        self.feed(source)
        self.close()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(tag=tag, attrs=dict(attrs), parent=self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(_Node(data=data, parent=self.stack[-1]))


def _walk(root: _Node):
    pending = list(reversed(root.children))
    while pending:
        node = pending.pop()
        yield node
        pending.extend(reversed(node.children))


def _text(node: _Node) -> str:
    return re.sub(r"\s+", " ", "".join(child.data for child in _walk(node) if child.tag is None)).strip()


def _serialize(root: _Node) -> str:
    output: list[str] = []
    pending: list[_Node | str] = list(reversed(root.children))
    while pending:
        node = pending.pop()
        if isinstance(node, str):
            output.append(node)
        elif node.tag is None:
            output.append(escape(node.data, quote=False))
        else:
            attrs = "".join(f" {key}" if value is None else f' {key}="{escape(value, quote=True)}"' for key, value in sorted(node.attrs.items()))
            output.append(f"<{node.tag}{attrs}>")
            if node.tag not in _VOID:
                pending.append(f"</{node.tag}>")
                pending.extend(reversed(node.children))
    return "".join(output)


def _classes(node: _Node) -> set[str]:
    return set((node.attrs.get("class") or "").split())


def _literal(node: _Node) -> bool:
    parent = node.parent
    while parent is not None:
        if parent.tag in {"pre", "code"} or _classes(parent) & {"tex-source-box", "mathjax-ignore"}:
            return True
        parent = parent.parent
    return False


def reference_key(document_id: str, revision: str, scope: str, label: str) -> str:
    """Unambiguous, JSON-compatible key; delimiters in source labels stay data."""
    return json.dumps([document_id, revision, scope, label], ensure_ascii=False, separators=(",", ":"))


def _anchor(document_id: str, revision: str, scope: str, label: str) -> str:
    digest = hashlib.sha256(reference_key(document_id, revision, scope, label).encode("utf-8")).hexdigest()
    return "tex-label-" + digest[:32]


def _safe_url(url: str) -> bool:
    if not url or re.search(r"[\x00-\x20\x7f\\]", url):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return (url.startswith("/") and not url.startswith("//") and not parts.scheme and not parts.netloc) or (
        parts.scheme in {"http", "https"} and bool(parts.netloc)
    )


def _caption(label: _Node, key: str) -> tuple[str, str]:
    # Math labels precede the whole expression. The formatter has discarded
    # row ownership for alignments, so neither automatic nor explicit equation
    # tags can reliably name every such label here.
    if label.attrs.get("data-tex-label-kind") == "math":
        return key, "equation"
    parent = label.parent
    while parent is not None:
        if parent.tag in _HEADINGS:
            return _text(parent) or key, "section"
        kinds = _classes(parent) & _THEOREMS
        if kinds:
            # The renderer emits the theorem's own heading as its first strong
            # child. Do not borrow a heading from a nested theorem or its proof.
            heading = next((child for child in parent.children if child.tag == "strong"), None)
            if heading is not None:
                caption = _text(heading).rstrip(": ")
                if caption:
                    return caption, caption.split(" ", 1)[0].lower()
            return key, sorted(kinds)[0]
        parent = parent.parent
    return key, "prose"


def _external_index(targets: Mapping | None, diagnostics: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    index: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for lookup, value in (targets or {}).items():
        candidates = value if isinstance(value, (list, tuple)) else [value]
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                diagnostics.append({"code": "invalid_external_target", "message": "External target must be a reference manifest entry."})
                continue
            target = dict(candidate)
            if isinstance(lookup, tuple) and len(lookup) == 2:
                target.setdefault("scope", lookup[0])
                target.setdefault("label", lookup[1])
            target.setdefault("scope", "0")
            required = ("document_id", "revision", "scope", "label")
            valid_url = target.get("ambiguous") is True or (isinstance(target.get("url"), str) and _safe_url(target["url"]))
            if any(not isinstance(target.get(key), str) or not target[key] for key in required) or not valid_url:
                diagnostics.append({"code": "invalid_external_target", "message": "External target needs a document, revision, scope, label and safe URL."})
                continue
            target.setdefault("caption", target["label"])
            target.setdefault("kind", "prose")
            target.setdefault("url", None)
            index[(target["scope"], target["label"])].append(target)
    return index


def resolve_references(
    html: str,
    *,
    document_id: str,
    revision: str,
    document_url: str,
    external_targets: Mapping | None = None,
) -> ReferenceResult:
    """Resolve a sanitized fragment without fetching or consulting page order.

    ``external_targets`` accepts another result's ``targets`` mapping, combined
    manifests, or ``(scope, label)`` keys with a target dictionary/list. Callers
    must pass only explicitly declared reference sources. Ambiguous local
    labels never fall through to an external target. Target manifests include
    duplicate occurrences but mark their shared label as ambiguous.

    Sanitization belongs before this call: we preserve the fragment's existing
    HTML and escape every new attribute/text value. Generated IDs depend on
    document identity and immutable revision, not catalogue or display order.
    """
    if not document_id or not revision:
        raise ValueError("References require a document identity and immutable revision.")
    if not _safe_url(document_url):
        raise ValueError("Reference document URL must be an absolute site path or HTTP(S) URL.")
    base_url = document_url.split("#", 1)[0]
    root = _Fragment(html).root
    nodes = list(_walk(root))
    labels: dict[tuple[str, str], list[_Node]] = defaultdict(list)
    links: list[_Node] = []
    targets: dict[str, dict[str, Any]] = {}
    diagnostics: list[dict[str, Any]] = []
    for node in nodes:
        if node.tag == "span" and "data-tex-label" in node.attrs and not _literal(node):
            label = node.attrs.get("data-tex-label") or ""
            scope = node.attrs.get("data-tex-scope") or "0"
            if label:
                labels[(scope, label)].append(node)
        elif node.tag == "a" and "data-tex-reference" in node.attrs and not _literal(node):
            links.append(node)

    for (scope, label), occurrences in labels.items():
        base_anchor = _anchor(document_id, revision, scope, label)
        anchors = []
        for i, node in enumerate(occurrences, 1):
            anchor = base_anchor if len(occurrences) == 1 else f"{base_anchor}-duplicate-{i}"
            node.attrs["id"] = anchor
            node.attrs["tabindex"] = "-1"
            anchors.append(anchor)
        caption, kind = _caption(occurrences[0], label)
        ambiguous = len(occurrences) != 1
        targets[reference_key(document_id, revision, scope, label)] = {
            "document_id": document_id,
            "revision": revision,
            "scope": scope,
            "label": label,
            "anchor": None if ambiguous else anchors[0],
            "anchors": anchors,
            "url": None if ambiguous else f"{base_url}#{anchors[0]}",
            "caption": caption,
            "kind": kind,
            "ambiguous": ambiguous,
        }
        if ambiguous:
            diagnostics.append({"code": "duplicate_label", "scope": scope, "label": label, "occurrences": len(occurrences)})

    external = _external_index(external_targets, diagnostics)
    for link in links:
        scope = link.attrs.get("data-tex-scope") or "0"
        label = link.attrs.get("data-tex-reference") or ""
        target = targets.get(reference_key(document_id, revision, scope, label))
        is_external = False
        reason = "target not present in this document or its declared reference sources"
        code = "unresolved_reference"
        if target is not None:
            if target["ambiguous"]:
                target = None
                reason = "multiple labels in the same source scope"
                code = "ambiguous_reference"
        else:
            candidates = external.get((scope, label), [])
            # Repeating the same manifest entry does not create ambiguity.
            candidates = list({(c["document_id"], c["revision"], c["scope"], c["label"], c["url"]): c for c in candidates}.values())
            if len(candidates) == 1 and not candidates[0].get("ambiguous", False):
                target = candidates[0]
                is_external = True
            elif candidates:
                reason = "multiple targets in the declared reference sources"
                code = "ambiguous_reference"

        link.attrs.pop("href", None)
        link.attrs.pop("target", None)
        link.attrs["data-tex-reference-ready"] = "true"
        if target is None:
            link.attrs["title"] = f"Reference {label}: {reason}."
            classes = _classes(link)
            classes.add("tex-reference-unresolved")
            link.attrs["class"] = " ".join(sorted(classes))
            diagnostics.append({"code": code, "scope": scope, "label": label, "message": reason})
            continue

        classes = _classes(link)
        classes.discard("tex-reference-unresolved")
        link.attrs["class"] = " ".join(sorted(classes))
        link.attrs["href"] = target["url"] if is_external else "#" + target["anchor"]
        location = f"{target['document_id']} · {target['revision']}" if is_external else f"this document · {revision}"
        link.attrs["title"] = f"View {target['caption']} in {location}"
        caption = str(target["caption"])
        if "\\" not in caption and "$" not in caption:
            if link.attrs.get("data-tex-reference-kind") == "eqref":
                caption = f"({caption})"
            if is_external:
                caption += f" · {target['document_id']} · {target['revision']}"
            link.children = [_Node(data=caption, parent=link)]
    return ReferenceResult(_serialize(root), targets, tuple(diagnostics))
