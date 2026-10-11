"""Deterministic revision packages (spec §11).

One ZIP per published contribution revision:

    <alias>-<rK>/contribution.yaml      the authored record, unchanged
    <alias>-<rK>/files/...              the original artifacts, unchanged
    <alias>-<rK>/MANIFEST.json          identities, fingerprint, per-file digests
    <alias>-<rK>/README.md, ATTRIBUTION.md, RIGHTS.md
    <alias>-<rK>/CITATION.cff, citation.json, citation.bib
    <alias>-<rK>/SHA256SUMS             digests of every other file

Entries are sorted, timestamps fixed and permissions normalised, so the same
inputs always give byte-identical archives. Packages are built locally; upload
to Release assets is milestone 5 (never Pages, never the authoring branch).
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from rp import strict_yaml
from rp.canonical import sha256_digest
from rp.publication.citation import CitationData, bibtex, cff, csl_json

__all__ = ["PACKAGE_FORMAT", "Package", "build_package"]

PACKAGE_FORMAT = "rp-package/1"
FIXED_TIME = (1980, 1, 1, 0, 0, 0)
DISCLAIMER = (
    "This is an archived research contribution. Publication on we-solve means admission to an attributed archive; "
    "it does not mean the contribution is correct, novel or peer reviewed. LLM-generated text can contain errors, "
    "invalid arguments and invented references."
)


@dataclass(frozen=True)
class Package:
    name: str
    data: bytes
    digest: str
    manifest: dict[str, Any]


def _people(record: Mapping[str, Any]) -> list[str]:
    return [p["display_name"] for p in record["attribution"]["humans"]]


def _attribution_md(record: Mapping[str, Any]) -> str:
    a = record["attribution"]
    lines = ["# Attribution", "", f"Contribution mode: {a['contribution_mode']}", "", f"Submitter: {a['submitter']['display_name']}"]
    if a["humans"]:
        lines += ["", "Human contributors:"]
        for p in a["humans"]:
            status = "" if p["authorship_confirmation"] == "confirmed" else f" ({p['authorship_confirmation'].replace('_', ' ')})"
            lines.append(f"- {p['display_name']}: {', '.join(p['roles'])}{status}")
    if record["model_uses"]:
        lines += ["", "Model and tool uses (as declared; versions are not verified):"]
        for m in record["model_uses"]:
            evidence = "; ".join(e.get("note", e["kind"]) for e in m["provenance"]["evidence"]) or "none"
            lines.append(f"- {m['declared_name']} (provider {m['provider']}, version {m['version']}, role {m['role']}; provenance {m['provenance']['level']}: {evidence})")
    return "\n".join(lines) + "\n"


def _rights_md(record: Mapping[str, Any], notices: str) -> str:
    r = record["rights"]
    lines = ["# Rights", "", f"Licence: {r['licence']}", f"Redistribution: {r['redistribution']}"]
    if r.get("holders"):
        lines.append("Holders: " + "; ".join(r["holders"]))
    if r.get("notes"):
        lines += ["", r["notes"]]
    for t in r.get("third_party", []):
        lines += ["", f"Third-party material: {t['description']}" + (f" ({t['licence']})" if t.get("licence") else "") + (f" <{t['source_url']}>" if t.get("source_url") else "")]
    if notices:
        lines += ["", "## Third-party notices", "", notices.strip()]
    return "\n".join(lines) + "\n"


def build_package(
    *,
    alias: str,
    revision_label: str,
    record: Mapping[str, Any],
    files: Mapping[str, bytes],
    scientific_fingerprint: str,
    citation: CitationData,
    provenance: Mapping[str, Any],
    notices: str = "",
) -> Package:
    """Build the archive for one revision. ``files`` maps ``files/...`` paths to exact bytes."""
    root = f"{alias}-{revision_label}"
    contents: dict[str, bytes] = {"contribution.yaml": strict_yaml.dump(dict(record)).encode("utf-8")}
    contents.update(files)
    claim = record.get("claim")
    readme = [
        f"# {record['title']}",
        "",
        f"{alias}, revision {revision_label}: {citation.url}",
        "",
        DISCLAIMER,
        "",
        f"Type: {record['type']}",
    ]
    if claim:
        readme.append(f"Claim: {claim['type'].replace('_', ' ')}. {claim['scope_statement']}")
    readme += ["", "See ATTRIBUTION.md, RIGHTS.md and MANIFEST.json. Verify the files with `sha256sum -c SHA256SUMS`."]
    contents["README.md"] = ("\n".join(readme) + "\n").encode("utf-8")
    contents["ATTRIBUTION.md"] = _attribution_md(record).encode("utf-8")
    contents["RIGHTS.md"] = _rights_md(record, notices).encode("utf-8")
    contents["CITATION.cff"] = cff(citation).encode("utf-8")
    contents["citation.json"] = (json.dumps([csl_json(citation)], indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    contents["citation.bib"] = bibtex(citation).encode("utf-8")
    manifest = {
        "format": PACKAGE_FORMAT,
        "alias": alias,
        "revision_label": revision_label,
        "contribution_id": record["contribution_id"],
        "revision_id": record["revision_id"],
        "scientific_fingerprint": scientific_fingerprint,
        "licence": record["rights"]["licence"],
        "provenance": dict(provenance),
        "files": [{"path": p, "digest": sha256_digest(b), "bytes": len(b)} for p, b in sorted(contents.items())],
    }
    contents["MANIFEST.json"] = (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    contents["SHA256SUMS"] = "".join(f"{hashlib.sha256(b).hexdigest()}  {p}\n" for p, b in sorted(contents.items())).encode("utf-8")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path in sorted(contents):
            info = zipfile.ZipInfo(f"{root}/{path}", date_time=FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            info.create_system = 3
            archive.writestr(info, contents[path], compresslevel=9)
    data = buffer.getvalue()
    return Package(f"{root}.zip", data, sha256_digest(data), manifest)
