"""Citation metadata for one immutable contribution revision (BibTeX, CSL-JSON, CFF).

A citation names the exact revision URL. Its date is the work's own date (a
declared or repository date with its precision), never a platform publication
time: packages are built before deployment, and a deployment time written into
them would be a guess (spec §4).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

__all__ = ["CitationData", "bibtex", "cff", "csl_json"]


class CitationData:
    def __init__(
        self,
        *,
        alias: str,
        revision_label: str,
        title: str,
        url: str,
        authors: list[str],
        institution: str | None,
        date: Mapping[str, str] | None,
        date_label: str,
        note: str,
        licence: str,
        contribution_id: str,
        revision_id: str,
    ):
        self.alias = alias
        self.revision_label = revision_label
        self.title = title
        self.url = url
        self.authors = authors
        self.institution = institution
        self.date = date
        self.date_label = date_label
        self.note = note
        self.licence = licence
        self.contribution_id = contribution_id
        self.revision_id = revision_id

    @property
    def key(self) -> str:
        return f"wesolve:{self.alias}-{self.revision_label}"

    def date_parts(self) -> list[int]:
        if not self.date:
            return []
        return [int(x) for x in re.findall(r"\d+", self.date["value"][:10])][: {"year": 1, "month": 2}.get(self.date["precision"], 3)]


_BIB_ESCAPES = str.maketrans({
    "\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "#": r"\#", "%": r"\%",
    "&": r"\&", "$": r"\$", "_": r"\_", "^": r"\^{}", "~": r"\~{}",
})


def _bib_escape(text: str) -> str:
    return text.translate(_BIB_ESCAPES)


def bibtex(c: CitationData) -> str:
    fields: list[tuple[str, str]] = [("title", "{" + _bib_escape(c.title) + "}")]  # extra braces keep capitals
    if c.authors:
        fields.append(("author", " and ".join(_bib_escape(a) for a in c.authors)))
    elif c.institution:
        fields.append(("author", "{" + _bib_escape(c.institution) + "}"))
    parts = c.date_parts()
    if parts:
        fields.append(("year", str(parts[0])))
        if len(parts) > 1:
            fields.append(("month", str(parts[1])))
    fields += [
        ("howpublished", "\\url{" + c.url + "}"),
        ("note", _bib_escape(f"Revision {c.revision_label} of {c.alias}. {c.note}")),
    ]
    body = ",\n".join(f"  {name} = {{{value}}}" for name, value in fields)
    return f"@misc{{{c.key},\n{body}\n}}\n"


def csl_json(c: CitationData) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": c.key,
        "type": "document",
        "title": c.title,
        "URL": c.url,
        "note": f"Revision {c.revision_label} of {c.alias}. {c.note} Date: {c.date_label}.",
        "license": c.licence,
        "number": f"{c.alias} {c.revision_label}",
    }
    if c.authors:
        item["author"] = [{"literal": a} for a in c.authors]
    elif c.institution:
        item["author"] = [{"literal": c.institution}]
    if c.date_parts():
        item["issued"] = {"date-parts": [c.date_parts()]}
    return item


def cff(c: CitationData) -> str:
    def q(text: str) -> str:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'

    lines = [
        "cff-version: 1.2.0",
        "message: Cite this exact revision. It has not been peer reviewed.",
        "type: dataset",
        f"title: {q(c.title)}",
        "authors:",
    ]
    names = c.authors or ([c.institution] if c.institution else ["Unknown"])
    lines += [f"  - name: {q(n)}" for n in names]
    lines += [f"url: {q(c.url)}", f"license: {c.licence}", f"version: {q(c.revision_label)}"]
    lines += ["identifiers:", "  - type: other", f"    value: {q(c.revision_id)}", f"    description: {q('Platform revision identifier')}"]
    return "\n".join(lines) + "\n"
