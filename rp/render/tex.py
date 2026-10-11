"""Build-time TeX rendering with the extracted legacy renderer (docs/adr/0011).

Pipeline per document:

1. ``prepare`` reproduces what the legacy site passed to ``formatTeX`` for that
   collection, using the unchanged legacy helpers in ``rp.render.legacy_prep``.
2. ``site/renderer/render-batch.js`` runs the extracted ``formatTeX`` (and the
   Economics normaliser) under Node in a sandboxed ``vm`` context, in one batch.
3. Post-processing: paragraphs that still contain TeX commands outside maths
   become escaped source boxes (never typeset); ``nh3`` applies an allowlist;
   ``\\label`` keys are collected for the reference index.

Results are cached on disk by a key covering the prepared input, the renderer
bundle, the post-processing version and the Node major version.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import json
import os
import re
import subprocess
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import nh3

from rp.render import legacy_prep

__all__ = ["Prepared", "RenderError", "Rendered", "TexRenderer", "prepare", "renderer_digest"]

RENDERER_DIR = Path(__file__).resolve().parents[2] / "site" / "renderer"
RUNNER = RENDERER_DIR / "render-batch.js"
BUNDLE_FILES = ("render-batch.js", "format-tex.js", "tex-bare-math.js", "economics-normalize.js")
POSTPROCESS_VERSION = "post/2"

KINDS = (
    "erdos_attempt",
    "mo_attempt",
    "top_attempt",
    "top_openai",
    "top_statement",
    "economics_statement",
    "economics_attempt",
)

ALLOWED_TAGS = {
    "p", "h1", "h2", "h3", "h4", "h5", "h6", "a", "em", "strong", "u", "code", "pre", "blockquote",
    "ul", "ol", "li", "table", "thead", "tbody", "tr", "td", "th", "span", "div", "br", "hr", "wbr",
    "sup", "sub",
}
ALLOWED_ATTRIBUTES = {
    "a": {"href", "class", "data-tex-reference", "data-tex-reference-kind", "data-tex-scope"},
    "span": {"class", "data-tex-label", "data-tex-scope", "data-tex-label-kind"},
    "div": {"class", "style"},
    "td": {"style"},
    "table": {"class"},
    "pre": {"class"},
}
LINK_ATTRIBUTES = {"a": {"target": "_blank", "referrerpolicy": "no-referrer"}}
LINK_REL = "noopener noreferrer nofollow ugc"

# Environments MathJax typesets outside delimiters (processEnvironments). Anything else
# left as \begin{...} is unconverted source and must become a source box.
MATH_ENVIRONMENTS = (
    "equation", "align", "alignat", "gather", "multline", "flalign", "eqnarray", "displaymath", "math",
    "split", "aligned", "gathered", "alignedat", "cases", "array", "matrix", "pmatrix", "bmatrix",
    "Bmatrix", "vmatrix", "Vmatrix", "smallmatrix", "subequations", "CD",
)
_MATH = re.compile(
    r"\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|(?<!\\)\$(?:\\.|[^$\\])+\$"
    r"|\\begin\{((?:" + "|".join(MATH_ENVIRONMENTS) + r")\*?)\}[\s\S]*?\\end\{\1\}"
)
_LITERAL = re.compile(r"<(pre|code)\b[\s\S]*?</\1>")
_TAG = re.compile(r"<[^>]+>")
_COMMAND = re.compile(r"\\([A-Za-z]+)")
_BLOCK = re.compile(r"<(p|li|h[1-6]|td)\b[^>]*>([\s\S]*?)</\1>")
_LABEL = re.compile(r'data-tex-label="([^"]*)"')
_HAS_MATH = re.compile(r"\$|\\\(|\\\[|\\begin\{(?:equation|align|gather|multline|flalign|eqnarray|displaymath)")


class RenderError(RuntimeError):
    pass


@dataclass(frozen=True)
class Prepared:
    text: str
    preserve_collection: bool = False
    infer_inline_math: bool = True
    economics: bool = False
    scope: str | None = None


@dataclass(frozen=True)
class Rendered:
    html: str
    scope_html: str | None = None
    has_math: bool = False
    labels: tuple[str, ...] = ()
    source_boxes: int = 0
    leftover_commands: tuple[str, ...] = field(default=())
    error: str | None = None


def _openai_body(content: str) -> str:
    """parse_openai_claim returns the text after its four ordered header lines."""
    return "".join(content.splitlines(keepends=True)[4:])


def _split_openai_scope(raw: str) -> tuple[str, str]:
    """Python port of the legacy splitOpenAIClaimContent (docs/app.js)."""
    heading = re.search(r"^[ \t]*\\subsection\*?\{Scope relative to this problem\}[ \t]*\r?$", raw, re.M)
    if not heading:
        return "", raw
    body_start = heading.end()
    remainder = raw[body_start:]
    nxt = re.search(r"^[ \t]*\\(?:subsection|section)\*?\{|^[ \t]*\\end\{document\}", remainder, re.M)
    body_end = body_start + nxt.start() if nxt else len(raw)
    return raw[body_start:body_end].strip(), raw[: heading.start()] + raw[body_end:]


def prepare(kind: str, content: str, path: str = "") -> Prepared:
    """Return the text and flags the legacy site would have passed to formatTeX."""
    if kind in ("erdos_attempt", "mo_attempt"):
        provenance, raw = legacy_prep.parse_collection_metadata(content)
        return Prepared(raw, preserve_collection=bool(provenance and provenance["kind"] == "reused_writeup"))
    if kind == "top_openai":
        scope, raw = _split_openai_scope(_openai_body(content))
        return Prepared(raw, scope=scope or None)
    if kind == "top_attempt":
        raw = content
        if r"\subsection{Definitions and mathematical statement}" in content:
            raw = legacy_prep.parse_numbered_problem_tex(content, require_source_urls=False)["documentTeX"]
        else:
            raw = legacy_prep.normalize_article_notation(content)
        provenance, raw = legacy_prep.parse_collection_metadata(raw)
        return Prepared(raw, preserve_collection=bool(provenance and provenance["kind"] == "reused_writeup"))
    if kind == "top_statement":
        definition = legacy_prep.parse_numbered_problem_tex(content, require_source_urls=False)["definitionTeX"]
        return Prepared(definition, infer_inline_math=False)
    if kind == "economics_statement":
        return Prepared(legacy_prep.extract_statement(content), infer_inline_math=False, economics=True)
    if kind == "economics_attempt":
        statuses = re.findall(r"^% ATTEMPT_STATUS: (.+)$", content, re.M)
        body = legacy_prep.economics_attempt_body(content, Path(path))
        raw = "% ATTEMPT_STATUS: " + (statuses[0] if statuses else "unresolved") + "\n" + body.strip()
        return Prepared(raw, infer_inline_math=False, economics=True)
    raise ValueError(f"unknown render kind {kind!r}")


@cache
def renderer_digest() -> str:
    h = hashlib.sha256()
    for name in BUNDLE_FILES:
        h.update(name.encode() + b"\0" + (RENDERER_DIR / name).read_bytes() + b"\0")
    h.update(POSTPROCESS_VERSION.encode())
    return "sha256:" + h.hexdigest()


@cache
def node_version() -> str:
    try:
        return subprocess.run(["node", "--version"], capture_output=True, text=True, check=True, timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise RenderError("Node.js is required to render TeX (see docs/adr/0011)") from exc


def _visible_text(fragment: str) -> str:
    text = _LITERAL.sub(" ", fragment)
    text = _TAG.sub(" ", text)
    return _MATH.sub(" ", html_lib.unescape(text))


def _source_boxes(html: str) -> tuple[str, int, list[str]]:
    """Replace blocks whose visible prose still contains TeX commands with escaped source boxes."""
    leftovers: list[str] = []
    count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal count
        commands = _COMMAND.findall(_visible_text(match.group(2)))
        if not commands:
            return match.group(0)
        count += 1
        leftovers.extend(commands)
        source = html_lib.escape(html_lib.unescape(_TAG.sub("", match.group(2))).strip())
        return f'<pre class="tex-source-box mathjax-ignore" title="Shown as source: this passage could not be converted">{source}</pre>'

    return _BLOCK.sub(replace, html), count, leftovers


def sanitise(html: str) -> str:
    return nh3.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes={"https", "http", "mailto"},
        link_rel=LINK_REL,
        set_tag_attribute_values=LINK_ATTRIBUTES,
        filter_style_properties={"max-width", "text-align"},
        strip_comments=True,
    )


def _postprocess(raw_html: str) -> tuple[str, int, list[str]]:
    boxed, count, leftovers = _source_boxes(raw_html)
    return sanitise(boxed), count, leftovers


class TexRenderer:
    def __init__(self, cache_dir: Path | None = None, timeout_ms: int = 10000):
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.timeout_ms = timeout_ms

    def _key(self, request: Mapping) -> str:
        payload = json.dumps(
            {"bundle": renderer_digest(), "node": node_version().split(".")[0], "request": request},
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _run(self, requests: list[dict]) -> dict[str, dict]:
        if not requests:
            return {}
        stdin = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in requests)
        proc = subprocess.run(
            ["node", str(RUNNER)],
            input=stdin.encode("utf-8"),
            capture_output=True,
            env={"RP_RENDER_TIMEOUT_MS": str(self.timeout_ms), "PATH": _path_env()},
            timeout=max(120, len(requests)),
        )
        if proc.returncode != 0:
            raise RenderError(proc.stderr.decode("utf-8", "replace")[:1000])
        results = {}
        for line in proc.stdout.decode("utf-8").splitlines():
            reply = json.loads(line)
            results[reply["id"]] = reply
        missing = {r["id"] for r in requests} - set(results)
        if missing:
            raise RenderError(f"renderer returned no result for {len(missing)} documents")
        return results

    def render_many(self, documents: Mapping[str, Prepared]) -> dict[str, Rendered]:
        """Render prepared documents. Failures become source boxes, never exceptions."""
        requests: dict[str, dict] = {}
        for doc_id, prepared in documents.items():
            base = {"preserveCollection": prepared.preserve_collection, "inferInlineMath": prepared.infer_inline_math, "economics": prepared.economics}
            requests[f"{doc_id}\0body"] = {"text": prepared.text, **base}
            if prepared.scope:
                requests[f"{doc_id}\0scope"] = {"text": prepared.scope, "preserveCollection": False, "inferInlineMath": False, "economics": False}
        outputs: dict[str, dict] = {}
        pending = []
        for rid, request in requests.items():
            cached = self._cache_get(self._key(request))
            if cached is not None:
                outputs[rid] = cached
            else:
                pending.append({"id": rid, **request})
        for rid, reply in self._run(pending).items():
            request = requests[rid]
            if "error" in reply:
                entry = {"html": None, "error": reply["error"]}
            else:
                html, boxes, leftovers = _postprocess(reply["html"])
                entry = {"html": html, "boxes": boxes, "leftovers": leftovers, "error": None}
            outputs[rid] = entry
            self._cache_put(self._key(request), entry)
        results = {}
        for doc_id, prepared in documents.items():
            body = outputs[f"{doc_id}\0body"]
            scope = outputs.get(f"{doc_id}\0scope")
            if body["error"] is not None:
                fallback = f'<pre class="tex-source-box mathjax-ignore">{html_lib.escape(prepared.text)}</pre>'
                results[doc_id] = Rendered(fallback, error=body["error"], source_boxes=1)
                continue
            html = body["html"]
            results[doc_id] = Rendered(
                html=html,
                scope_html=scope["html"] if scope and scope["error"] is None else None,
                has_math=bool(_HAS_MATH.search(html)),
                labels=tuple(dict.fromkeys(_LABEL.findall(html))),
                source_boxes=body["boxes"],
                leftover_commands=tuple(body["leftovers"]),
            )
        return results

    def _cache_get(self, key: str) -> dict | None:
        if self.cache_dir is None:
            return None
        path = self.cache_dir / key[:2] / f"{key}.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _cache_put(self, key: str, entry: dict) -> None:
        if self.cache_dir is None:
            return
        path = self.cache_dir / key[:2] / f"{key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)


def _path_env() -> str:
    return os.environ.get("PATH", "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin")


def report(results: Mapping[str, Rendered]) -> dict:
    """Aggregate rendering quality for the build report."""
    commands: Counter[str] = Counter()
    for r in results.values():
        commands.update(r.leftover_commands)
    return {
        "documents": len(results),
        "errors": sum(1 for r in results.values() if r.error),
        "documents_with_source_boxes": sum(1 for r in results.values() if r.source_boxes),
        "source_boxes": sum(r.source_boxes for r in results.values()),
        "top_leftover_commands": commands.most_common(30),
    }
