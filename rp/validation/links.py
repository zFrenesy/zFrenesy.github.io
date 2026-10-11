"""External links and linked artifacts (spec §10).

``check_external_links`` is the offline Tier 0 check: allowed artifact hosts, pins
that match the URL, and the rules for reference links in records and manuscripts
(HTTPS only; no shorteners, IP hosts, credentials, ``javascript:``/``data:`` or
confusable domains). ``verify_pins`` is the online step. It runs only in a job with
no secrets, talks only to the GitHub and Hugging Face APIs through a bounded client,
and never downloads, executes or embeds the linked material.
"""

from __future__ import annotations

import ipaddress
import json
import re
import unicodedata
import urllib.error
import urllib.request
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import quote, urlsplit

from rp.catalog import Catalog, default_catalog

__all__ = [
    "ArtifactLink",
    "BoundedHttp",
    "HttpClient",
    "LinkIssue",
    "LinkReport",
    "check_external_links",
    "host_problem",
    "sweep_links",
    "verify_pins",
]

TEXT_SUFFIXES = (".md", ".tex", ".bib", ".txt")
NOT_EXAMINED = "linked artifact not examined"
# URLs in prose: bare https?:// links plus the targets of Markdown links, \url and \href.
_URL = re.compile(r"""(?:https?|ftp)://(?:\[[0-9A-Fa-f:.]+\])?[^\s<>"'`{}\\|^\]\[)]*""", re.IGNORECASE)
# Script and local-file schemes, wherever they appear (prose mentions such as "Data: ..." do not match).
_BAD_SCHEME = re.compile(r"(?i)\b(?:javascript|vbscript):\S|\bdata:[a-z-]+/[a-z0-9.+-]+[;,]|\bfile:/")
_TRAILING = ".,;:!?'\")"
# Cyrillic and Greek letters that look like lowercase Latin letters (from Unicode's confusables).
# A non-Latin label made only of these imitates a Latin name; genuine words in those scripts
# (such as "москва") contain other letters and pass.
_LOOKALIKES = frozenset("аеорсухіјѕԁԛԝӏһ" "αοιρυνχ")


@dataclass(frozen=True)
class LinkIssue:
    where: str
    url: str
    message: str
    severity: str = "error"

    def __str__(self) -> str:
        return f"{self.where}: {self.url[:120]}: {self.message}"


@dataclass(frozen=True)
class ArtifactLink:
    where: str
    url: str
    host_key: str
    pin_kind: str
    pin: str
    verify: str


@dataclass
class LinkReport:
    issues: list[LinkIssue] = field(default_factory=list)
    artifacts: list[ArtifactLink] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    verified: dict[str, str] = field(default_factory=dict)  # artifact URL -> available | unavailable | unverified | not_checked
    notes: list[str] = field(default_factory=list)

    @property
    def errors(self) -> list[LinkIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[LinkIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors


# ---------------------------------------------------------------------------
# Hosts


def _scripts(label: str) -> set[str]:
    scripts = set()
    for char in label:
        if char.isascii() and (char.isalnum() or char == "-"):
            scripts.add("LATIN" if char.isalpha() else "COMMON")
            continue
        name = unicodedata.name(char, "")
        scripts.add(name.split(" ")[0] if name else "UNKNOWN")
    return scripts - {"COMMON", "DIGIT", "HYPHEN-MINUS"}


def _decode_label(label: str) -> str | None:
    if label.startswith("xn--"):
        try:
            return label[4:].encode("ascii").decode("punycode")
        except (UnicodeError, ValueError):
            return None
    return label


def host_problem(host: str) -> str | None:
    """Why ``host`` is not acceptable for a link, or None. Rejects IPs and confusable labels."""
    if not host:
        return "no host"
    try:
        ipaddress.ip_address(host.strip("[]"))
        return "links to a raw IP address"
    except ValueError:
        pass
    if host.endswith("."):
        host = host[:-1]
    for raw in host.split("."):
        label = _decode_label(raw.lower())
        if label is None:
            return "has an invalid internationalised label"
        if label.isascii():
            continue
        if unicodedata.normalize("NFKC", label) != label:
            return "has a domain label that is not in normal form"
        scripts = _scripts(label)
        if len(scripts) > 1:
            return "mixes alphabets in a domain name (possible lookalike)"
        letters = [c for c in label if c != "-" and not c.isdigit()]
        if letters and all(c in _LOOKALIKES for c in letters):
            return "uses letters that imitate Latin letters (possible lookalike)"
    return None


# ---------------------------------------------------------------------------
# Offline check


def _strings(value: Any, pointer: str) -> Iterable[tuple[str, str]]:
    if isinstance(value, str):
        yield pointer, value
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield from _strings(item, f"{pointer}/{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _strings(item, f"{pointer}/{index}")


def _reference(report: LinkReport, where: str, url: str, shorteners: set[str]) -> None:
    url = url.rstrip(_TRAILING)
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
    except ValueError:
        report.issues.append(LinkIssue(where, url, "is not a valid URL"))
        return
    if parts.scheme.lower() != "https":
        report.issues.append(LinkIssue(where, url, "must use HTTPS"))
        return
    if "@" in parts.netloc:
        report.issues.append(LinkIssue(where, url, "must not contain user names or passwords"))
        return
    if host in shorteners or any(host.endswith("." + s) for s in shorteners):
        report.issues.append(LinkIssue(where, url, "uses a URL shortener; link to the final address"))
        return
    if problem := host_problem(host):
        report.issues.append(LinkIssue(where, url, problem))
        return
    report.references.append(url)


def _artifact(report: LinkReport, where: str, external: Mapping[str, Any], policy: Mapping[str, Any], enabled: Iterable[str]) -> None:
    url, pin = external["url"], external["pin"]
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    entries = {key: policy["artifact_hosts"][key] for key in enabled if key in policy["artifact_hosts"]}
    match = next(((key, entry) for key, entry in entries.items() if host in entry["hosts"]), None)
    if parts.scheme != "https" or "@" in parts.netloc or parts.port not in (None, 443):
        report.issues.append(LinkIssue(where, url, "must be a plain HTTPS link"))
        return
    if match is None:
        allowed = ", ".join(sorted(h for e in entries.values() for h in e["hosts"]))
        report.issues.append(LinkIssue(where, url, f"is not on an allowed artifact host ({allowed})"))
        return
    key, entry = match
    if pin["kind"] != entry["pin_kind"]:
        report.issues.append(LinkIssue(where, url, f"{entry['name']} links are pinned with {entry['pin_kind']}, not {pin['kind']}"))
        return
    found = re.fullmatch(entry["url_pattern"], parts.path)
    if found is None or parts.query or parts.fragment:
        report.issues.append(LinkIssue(where, url, f"must point to an exact {entry['name']} revision, not a branch, tag or latest version"))
        return
    groups = found.groupdict()
    in_url = groups.get("pin") or (f"10.5281/zenodo.{groups['record']}" if groups.get("record") else None)
    if in_url != pin["value"]:
        report.issues.append(LinkIssue(where, url, f"the pin {pin['value']} does not match the revision in the URL"))
        return
    report.artifacts.append(ArtifactLink(where, url, key, pin["kind"], pin["value"], entry["verify"]))


def check_external_links(record: Mapping[str, Any], files: Mapping[str, bytes] | None = None, *,
                         catalog: Catalog | None = None, where: str = "") -> LinkReport:
    """Offline checks for one contribution or problem record and its text files."""
    catalog = catalog or default_catalog()
    policy = catalog.external_hosts
    report = LinkReport()
    if not policy:
        report.issues.append(LinkIssue(where or "policy", "", "no external-host policy is configured"))
        return report
    shorteners = set(policy["shorteners"])
    enabled = catalog.platform["allowed_external_hosts"]
    artifact_urls = set()
    for index, artifact in enumerate(record.get("artifacts", [])):
        if artifact.get("location") == "external_pinned":
            artifact_urls.add(artifact["external"]["url"])
            _artifact(report, f"{where}/artifacts/{index}", artifact["external"], policy, enabled)
    for pointer, text in _strings(record, where):
        if text in artifact_urls:
            continue
        if found := _BAD_SCHEME.search(text):
            report.issues.append(LinkIssue(pointer, found.group(0), "links with this scheme are not allowed"))
        for url in _URL.findall(text):
            _reference(report, pointer, url, shorteners)
    for name, data in sorted((files or {}).items()):
        if not name.lower().endswith(TEXT_SUFFIXES):
            continue
        text = data.decode("utf-8", errors="replace")
        for found in _BAD_SCHEME.finditer(text):
            report.issues.append(LinkIssue(f"{where}/{name}", found.group(0), "links with this scheme are not allowed"))
        for url in _URL.findall(text):
            _reference(report, f"{where}/{name}", url, shorteners)
    return report


# ---------------------------------------------------------------------------
# Online verification


class HttpClient(Protocol):
    def get_json(self, url: str) -> tuple[int, Any]:
        """Status and decoded JSON body (None when absent). Raises OSError on network failure."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed: set[str], limit: int):
        self.allowed, self.limit, self.count = allowed, limit, 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        self.count += 1
        host = (urlsplit(newurl).hostname or "").lower()
        if self.count > self.limit or urlsplit(newurl).scheme != "https" or host not in self.allowed:
            raise urllib.error.HTTPError(newurl, code, "redirect not allowed", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class BoundedHttp:
    """GET JSON from the GitHub and Hugging Face APIs only, with time, size and redirect limits."""

    ALLOWED = {"api.github.com", "huggingface.co"}

    def __init__(self, timeout: float = 15.0, max_bytes: int = 2 * 1024 * 1024, max_redirects: int = 3):
        self.timeout, self.max_bytes, self.max_redirects = timeout, max_bytes, max_redirects

    def get_json(self, url: str) -> tuple[int, Any]:
        parts = urlsplit(url)
        if parts.scheme != "https" or (parts.hostname or "") not in self.ALLOWED:
            raise OSError(f"refusing to fetch {parts.hostname}")
        opener = urllib.request.build_opener(_NoRedirect(self.ALLOWED, self.max_redirects))
        request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "we-solve-link-check"})
        try:
            with opener.open(request, timeout=self.timeout) as response:
                body = response.read(self.max_bytes + 1)
                status = response.status
        except urllib.error.HTTPError as exc:
            if exc.code in (404, 410, 422):
                return exc.code, None
            raise OSError(f"HTTP {exc.code}") from exc
        if len(body) > self.max_bytes:
            raise OSError("response too large")
        return status, json.loads(body)


def _github(link: ArtifactLink, http: HttpClient) -> tuple[str, list[str]]:
    owner, repo = urlsplit(link.url).path.split("/")[1:3]
    status, _ = http.get_json(f"https://api.github.com/repos/{quote(owner)}/{quote(repo)}/commits/{link.pin}")
    return ("available", []) if status == 200 else ("unavailable", ["the pinned commit was not found"])


def _hugging_face(link: ArtifactLink, http: HttpClient, pickle_suffixes: set[str]) -> tuple[str, list[str]]:
    path = urlsplit(link.url).path.strip("/").split("/")
    kind = "models"
    if path[0] in ("datasets", "spaces"):
        kind, path = path[0], path[1:]
    status, info = http.get_json(f"https://huggingface.co/api/{kind}/{quote(path[0])}/{quote(path[1])}/revision/{link.pin}")
    if status != 200 or not isinstance(info, dict):
        return "unavailable", ["the pinned revision was not found"]
    notes = []
    names = [s.get("rfilename", "") for s in info.get("siblings", []) if isinstance(s, dict)]
    pickled = sorted(n for n in names if any(n.lower().endswith(s) for s in pickle_suffixes))
    if pickled:
        notes.append(f"pickle-format files can run code when loaded: {', '.join(pickled[:5])}")
    config = info.get("config") if isinstance(info.get("config"), dict) else {}
    if config.get("auto_map") or any(n.endswith(".py") for n in names):
        notes.append("the repository asks to run its own code (remote code)")
    return "available", notes


def verify_pins(report: LinkReport, http: HttpClient, *, catalog: Catalog | None = None) -> LinkReport:
    """Check that each pinned target exists. Network failures leave the link unverified, never 'fabricated'."""
    catalog = catalog or default_catalog()
    pickle_suffixes = set(catalog.external_hosts.get("pickle_suffixes", []))
    for link in report.artifacts:
        try:
            if link.verify == "github_api":
                state, notes = _github(link, http)
            elif link.verify == "hugging_face_api":
                state, notes = _hugging_face(link, http, pickle_suffixes)
            else:
                state, notes = "not_checked", []
        except (OSError, ValueError) as exc:
            state, notes = "unverified", [f"could not be checked now ({exc}); this is not evidence of a problem"]
        report.verified[link.url] = state
        if state == "unavailable":
            report.issues.append(LinkIssue(link.where, link.url, notes[0]))
        for note in notes if state != "unavailable" else []:
            report.issues.append(LinkIssue(link.where, link.url, note, "warning"))
    if report.artifacts:
        report.notes.append(f"{NOT_EXAMINED}: the platform checks that pins exist, never runs or inspects the content")
    return report


def sweep_links(root, http: HttpClient, *, catalog: Catalog | None = None) -> dict[str, Any]:
    """Availability of every pinned artifact in a research tree (the weekly link check, §10).

    A vanished target is marked ``unavailable``; no scientific label changes. The
    result is display data for the site, keyed by URL.
    """
    from pathlib import Path

    from rp import strict_yaml

    links: dict[str, dict[str, str]] = {}
    for path in sorted(Path(root).glob("problems/*/*/*/*/contribution.yaml")):
        record = strict_yaml.load(path.read_bytes())
        report = check_external_links({"artifacts": record.get("artifacts", [])}, catalog=catalog, where=path.parent.relative_to(root).as_posix())
        verify_pins(report, http, catalog=catalog)
        for link in report.artifacts:
            links[link.url] = {"state": report.verified.get(link.url, "unverified"), "pin": link.pin, "contribution_id": record["contribution_id"]}
    return {"schema_version": 1, "links": links}
