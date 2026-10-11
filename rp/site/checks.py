"""Offline checks for the published tree; no linked resource is fetched.

Payload counts are uncompressed transfer bytes, including each initial local
subresource once. MathJax assets and explicitly marked document content are
excluded from that budget, but still checked for broken or remote resources.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

# Anchor (navigation) schemes. codex:// and claude-cli:// are the spec §20 agent deep links;
# they open local applications and load nothing into the page.
ANCHOR_SCHEMES = frozenset({"http", "https", "mailto", "tel", "codex", "claude-cli"})


class SiteCheckError(ValueError):
    """A publication gate failed; ``report`` retains machine-readable results."""

    def __init__(self, report: dict):
        self.report = report
        self.errors = report["errors"]
        super().__init__("Site validation failed:\n" + "\n".join(self.errors[:30])
                         + (f"\n... and {len(self.errors) - 30} more errors" if len(self.errors) > 30 else ""))


@dataclass(frozen=True)
class _Reference:
    url: str
    resource: bool = False
    excluded: bool = False


@dataclass
class _Document:
    ids: set[str] = field(default_factory=set)
    references: list[_Reference] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    payload_bytes: int = 0


_VOID = frozenset("area base br col embed hr img input link meta param source track wbr".split())
_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_CSS_URL = re.compile(r"url\(\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s)]*))\s*\)", re.I)
_CSS_IMPORT = re.compile(r"@import\s+(?:\"([^\"]*)\"|'([^']*)')", re.I)
_CSS_ESCAPE = re.compile(r"\\(?:([0-9a-fA-F]{1,6})\s?|([^\r\n]))")


def _css_references(css: str, *, excluded: bool = False) -> list[_Reference]:
    # CSS escapes can spell part of a URL or even the `url` keyword.
    css = _CSS_COMMENT.sub("", css)
    css = _CSS_ESCAPE.sub(lambda m: chr(int(m[1], 16)) if m[1] and 0 < int(m[1], 16) <= 0x10FFFF
                         else (m[2] or "\ufffd"), css)
    return [_Reference(next(group for group in match.groups() if group is not None), True, excluded)
            for pattern in (_CSS_URL, _CSS_IMPORT) for match in pattern.finditer(css)]


def _srcset_urls(value: str) -> list[str]:
    # Consume URL tokens separately from descriptors; data URLs may contain commas.
    urls = []
    remaining = value.strip()
    while remaining:
        remaining = remaining.lstrip(" ,\t\r\n")
        if not remaining:
            break
        split = re.split(r"\s+", remaining, maxsplit=1)
        token, rest = split[0], split[1] if len(split) > 1 else ""
        if token.startswith("data:"):
            urls.append(token.rstrip(","))
        else:
            urls.extend(part for part in token.split(",") if part)
        if token.endswith(","):
            remaining = rest
        else:
            _, comma, remaining = rest.partition(",")
            if not comma:
                break
    return urls


class _HTML(HTMLParser):
    def __init__(self, source: str):
        super().__init__(convert_charrefs=True)
        self.source = source
        self.document = _Document(payload_bytes=len(source.encode("utf-8")))
        self.line_offsets = [0]
        self.line_offsets.extend(m.end() for m in re.finditer("\n", source))
        self.stack: list[tuple[str, int | None]] = []
        self.excluded_start: int | None = None
        self.style_parts: list[str] | None = None
        self.style_excluded = False

    def _offset(self) -> int:
        line, col = self.getpos()
        return self.line_offsets[line - 1] + col

    def _reference(self, url: str, resource: bool = False) -> None:
        self.document.references.append(_Reference(url, resource, self.excluded_start is not None))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        element_id = attributes.get("id")
        if element_id:
            if element_id in self.document.ids:
                self.document.errors.append(f"duplicate id {element_id!r}")
            self.document.ids.add(element_id)
        if tag == "a" and attributes.get("name"):
            self.document.ids.add(attributes["name"])
        if tag == "base":
            self.document.errors.append("base elements are not supported; use the configured base_path")
        exclude_at = None
        if "data-payload-exclude" in attributes and self.excluded_start is None and tag not in _VOID:
            exclude_at = self._offset() + len(self.get_starttag_text())
            self.excluded_start = exclude_at
        if tag not in _VOID:
            self.stack.append((tag, exclude_at))
        # The trusted MathJax bootstrap loads this declared URL dynamically.
        for name in ("src", "poster", "background", "data-mathjax-src"):
            if attributes.get(name):
                self._reference(attributes[name], True)
        if tag == "object" and attributes.get("data"):
            self._reference(attributes["data"], True)
        for name in ("srcset", "imagesrcset"):
            if attributes.get(name):
                for url in _srcset_urls(attributes[name]):
                    self._reference(url, True)
        if attributes.get("href"):
            rel = set((attributes.get("rel") or "").lower().split())
            resource = tag not in {"a", "area"} and not (tag == "link" and rel <= {"canonical", "alternate", "author", "license", "help"})
            self._reference(attributes["href"], resource)
        if attributes.get("xlink:href"):
            self._reference(attributes["xlink:href"], True)
        if attributes.get("style"):
            self.document.references.extend(_css_references(attributes["style"], excluded=self.excluded_start is not None))
        if tag == "style":
            self.style_parts = []
            self.style_excluded = self.excluded_start is not None
        if tag == "meta" and (attributes.get("http-equiv") or "").lower() == "refresh":
            match = re.search(r"(?:^|;)\s*url\s*=\s*(.*)", attributes.get("content") or "", re.I)
            if match:
                # Check the navigation target, but budget its own page separately.
                self.document.references.append(_Reference(match[1].strip().strip("\"'"), True, True))
        if attributes.get("srcdoc"):
            nested = _parse_html(attributes["srcdoc"])
            self.document.errors.extend(nested.errors)
            self.document.references.extend(nested.references)
        if attributes.get("ping"):
            for url in attributes["ping"].split():
                self._reference(url, True)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self.style_parts is not None:
            self.style_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "style" and self.style_parts is not None:
            self.document.references.extend(_css_references("".join(self.style_parts), excluded=self.style_excluded))
            self.style_parts = None
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                removed = self.stack[index:]
                del self.stack[index:]
                for _, start in removed:
                    if start is not None:
                        self.document.payload_bytes -= len(self.source[start:max(start, self._offset())].encode("utf-8"))
                        self.excluded_start = None
                break


def _parse_html(source: str) -> _Document:
    parser = _HTML(source)
    parser.feed(source)
    parser.close()
    if parser.excluded_start is not None:
        parser.document.errors.append("unclosed data-payload-exclude container")
    return parser.document


def _is_mathjax(path: str) -> bool:
    return path.startswith("assets/vendor/mathjax/") or path.startswith("assets/vendor/mathjax-")


def validate_site(out: Path, *, base_path: str = "", payload_limit: int = 200 * 1024,
                  site_limit: int = 800 * 1024 * 1024) -> dict:
    """Validate routes, assets, fragments and byte budgets in a static Pages tree.

    ``base_path`` is the deployment prefix, e.g. ``/research`` for project Pages.
    Both root-relative prefixed URLs and ordinary document-relative URLs work.
    Anchor navigation to external sites is allowed; remote subresources are not.
    Required shared assets are ``assets/site.css`` and ``assets/site.js``. Every
    referenced MathJax engine/extension/font must also exist in this tree.
    """
    out = Path(out)
    if base_path and (not base_path.startswith("/") or "?" in base_path or "#" in base_path
                      or "\\" in base_path or any(p in {".", ".."} for p in base_path.split("/"))):
        raise ValueError("base_path must be an absolute URL path without traversal, query or fragment")
    base_path = base_path.rstrip("/")
    if payload_limit < 0 or site_limit <= 0:
        raise ValueError("payload_limit must be nonnegative and site_limit must be positive")
    report = {"html_pages": 0, "files": 0, "total_bytes": 0, "max_initial_payload_bytes": 0,
              "largest_page": None, "largest_pages": [], "errors": []}
    errors: list[str] = report["errors"]
    if not out.is_dir():
        errors.append(f"site output directory does not exist: {out}")
        raise SiteCheckError(report)
    sizes: dict[str, int] = {}
    documents: dict[str, _Document] = {}
    references: dict[str, list[_Reference]] = {}
    for path in sorted(out.rglob("*")):
        relative = path.relative_to(out).as_posix()
        if path.is_symlink():
            errors.append(f"{relative}: symlinks are not allowed in Pages output")
            continue
        if not path.is_file():
            continue
        sizes[relative] = path.stat().st_size
        if path.suffix.lower() in {".zip", ".pdf"}:
            errors.append(f"{relative}: ZIP/PDF downloads belong in immutable Release assets, not Pages output")
        if path.suffix.lower() not in {".html", ".htm", ".svg", ".css"}:
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeError:
            errors.append(f"{relative}: expected UTF-8 text")
            continue
        if path.suffix.lower() == ".css":
            references[relative] = _css_references(source)
        else:
            document = _parse_html(source)
            documents[relative] = document
            references[relative] = document.references
            errors.extend(f"{relative}: {error}" for error in document.errors)
            if path.suffix.lower() in {".html", ".htm"}:
                report["html_pages"] += 1
    report["files"] = len(sizes)
    report["total_bytes"] = sum(sizes.values())
    if not report["html_pages"]:
        errors.append("site contains no HTML pages")
    for required in ("assets/site.css", "assets/site.js"):
        if required not in sizes:
            errors.append(f"missing mandatory self-hosted asset: {required}")
    if report["total_bytes"] >= site_limit:
        errors.append(f"site output is {report['total_bytes']} bytes; must be under {site_limit} bytes")

    def resolve(source: str, ref: _Reference) -> str | None:
        raw = ref.url.strip()
        if any(ord(char) < 32 for char in raw) or "\\" in raw:
            errors.append(f"{source}: unsafe URL {raw!r}")
            return None
        try:
            parsed = urlsplit(raw)
        except ValueError:
            errors.append(f"{source}: malformed URL {raw!r}")
            return None
        if parsed.scheme or parsed.netloc or raw.startswith("//"):
            if ref.resource:
                if parsed.scheme.lower() != "data":
                    errors.append(f"{source}: external subresource is forbidden: {raw!r}")
            elif parsed.scheme.lower() not in ANCHOR_SCHEMES and not raw.startswith("//"):
                errors.append(f"{source}: unsafe link scheme in {raw!r}")
            return None
        try:
            path = unquote(parsed.path, errors="strict")
            fragment = unquote(parsed.fragment, errors="strict")
        except UnicodeError:
            errors.append(f"{source}: malformed percent encoding in {raw!r}")
            return None
        if "\\" in path or any(ord(char) < 32 for char in path):
            errors.append(f"{source}: unsafe path in {raw!r}")
            return None
        if path.startswith("/"):
            if base_path and not (path == base_path or path.startswith(base_path + "/")):
                errors.append(f"{source}: URL is outside configured base_path {base_path!r}: {raw!r}")
                return None
            path = path[len(base_path):].lstrip("/")
            parts: list[str] = []
        else:
            parts = list(PurePosixPath(source).parent.parts) if path else []
        if not parsed.path:
            target = source
        else:
            for part in path.split("/"):
                if part == "..":
                    if not parts:
                        errors.append(f"{source}: path traversal outside site in {raw!r}")
                        return None
                    parts.pop()
                elif part and part != ".":
                    parts.append(part)
            target = "/".join(parts)
            if target not in sizes:
                index = (target + "/" if target else "") + "index.html"
                if index in sizes:
                    target = index
                else:
                    errors.append(f"{source}: missing internal target {raw!r} (resolved to {target or '/'})")
                    return None
        if fragment and target in documents and fragment not in documents[target].ids:
            errors.append(f"{source}: missing anchor {fragment!r} in {target} (URL {raw!r})")
        return target

    resource_graph: dict[str, set[str]] = {}
    for source, refs in references.items():
        resources = resource_graph.setdefault(source, set())
        for ref in refs:
            target = resolve(source, ref)
            if target is not None and ref.resource and not ref.excluded and not _is_mathjax(target):
                resources.add(target)

    # Shared stylesheets and their fonts/images are expanded once, not once per page.
    dependency_cache: dict[str, frozenset[str]] = {}

    def dependencies(start: str) -> frozenset[str]:
        if start not in dependency_cache:
            found: set[str] = set()
            pending = [start]
            while pending:
                current = pending.pop()
                if current in found or _is_mathjax(current):
                    continue
                found.add(current)
                pending.extend(resource_graph.get(current, ()))
            dependency_cache[start] = frozenset(found)
        return dependency_cache[start]

    payloads: list[tuple[int, str]] = []
    for page, document in documents.items():
        if PurePosixPath(page).suffix.lower() not in {".html", ".htm"}:
            continue
        initial: set[str] = set()
        for resource in resource_graph.get(page, ()):
            initial.update(dependencies(resource))
        initial.discard(page)
        payload = document.payload_bytes + sum(sizes[path] for path in initial)
        payloads.append((payload, page))
        if payload > payload_limit:
            errors.append(f"{page}: initial first-party payload is {payload} bytes; limit is {payload_limit} bytes")
    payloads.sort(reverse=True)
    report["largest_pages"] = [{"path": page, "initial_payload_bytes": payload} for payload, page in payloads[:10]]
    if payloads:
        report["max_initial_payload_bytes"], report["largest_page"] = payloads[0]
    if errors:
        raise SiteCheckError(report)
    return report
