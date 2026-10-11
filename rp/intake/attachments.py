"""Files attached to an issue form (spec §6, §7, §16.4).

Only GitHub's own upload URLs are fetched, through an injected fetcher with size,
time and redirect limits. Zip archives are expanded in memory with every entry
checked: no traversal or absolute paths, links, duplicates (including case-only),
nested archives, oversized entries, implausible compression ratios or unaccepted
file types. Nothing is executed, rendered or written outside the candidate.
"""

from __future__ import annotations

import io
import re
import stat
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from rp.contribute.check import ALLOWED_SUFFIXES, LIMITS
from rp.identity.paths import InvalidPath, check_relative_path

__all__ = ["Attachment", "AttachmentReport", "attachment_urls", "expand_zip", "fetch_attachments"]

_URL = re.compile(r"https://github\.com/(?:user-attachments/(?:files|assets)/[A-Za-z0-9/_.%-]+|[A-Za-z0-9-]+/[A-Za-z0-9._-]+/files/\d+/[A-Za-z0-9._%-]+)")
MAX_RATIO = 100
UPLOAD_SUFFIXES = ALLOWED_SUFFIXES - {".yaml"} | {".zip"}


@dataclass(frozen=True)
class Attachment:
    name: str
    content: bytes
    source_url: str


@dataclass
class AttachmentReport:
    files: list[Attachment] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def attachment_urls(text: str) -> list[str]:
    seen, found = set(), []
    for url in _URL.findall(text or ""):
        url = url.rstrip(".,)")
        if url not in seen:
            seen.add(url)
            found.append(url)
    return found


def _safe_name(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", PurePosixPath(name).name).strip("-.") or "attachment"
    return stem[:100]


def expand_zip(data: bytes, source_url: str, report: AttachmentReport, *, budget: list[int]) -> None:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        report.errors.append(f"{source_url}: not a readable zip archive")
        return
    seen: set[str] = set()
    infos = archive.infolist()
    if len(infos) > LIMITS["files"]:
        report.errors.append(f"{source_url}: {len(infos)} entries exceeds the limit of {LIMITS['files']}")
        return
    for info in infos:
        name = info.filename
        if info.is_dir():
            continue
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode):
            report.errors.append(f"{source_url}: {name} is a symbolic link")
            continue
        try:
            clean = check_relative_path(name)
        except InvalidPath as exc:
            report.errors.append(f"{source_url}: {name!r}: {exc}")
            continue
        folded = clean.as_posix().lower()
        if folded in seen:
            report.errors.append(f"{source_url}: {name} appears twice")
            continue
        seen.add(folded)
        suffix = clean.suffix.lower()
        if suffix == ".zip":
            report.errors.append(f"{source_url}: {name}: nested archives are not accepted")
            continue
        if suffix not in ALLOWED_SUFFIXES - {".yaml"}:
            report.errors.append(f"{source_url}: {name}: file type {suffix or '(none)'} is not accepted")
            continue
        if info.file_size > LIMITS["file_bytes"]:
            report.errors.append(f"{source_url}: {name} is larger than 5 MiB")
            continue
        if info.compress_size and info.file_size / info.compress_size > MAX_RATIO and info.file_size > 1024 * 1024:
            report.errors.append(f"{source_url}: {name} has an implausible compression ratio")
            continue
        with archive.open(info) as handle:
            content = handle.read(LIMITS["file_bytes"] + 1)
        if len(content) > LIMITS["file_bytes"] or len(content) != info.file_size:
            report.errors.append(f"{source_url}: {name} does not match its declared size")
            continue
        budget[0] -= len(content)
        if budget[0] < 0:
            report.errors.append(f"{source_url}: the attachments exceed the 25 MiB limit")
            return
        report.files.append(Attachment(clean.as_posix(), content, source_url))


def fetch_attachments(text: str, fetch: Callable[[str], tuple[str, bytes]] | None) -> AttachmentReport:
    """Fetch and expand attachments linked from contributor text. ``fetch(url) -> (filename, bytes)``."""
    report = AttachmentReport()
    urls = attachment_urls(text)
    if not urls:
        return report
    if fetch is None:
        report.errors.append(f"{len(urls)} attachment(s) not fetched in this run")
        return report
    budget = [LIMITS["total_bytes"]]
    for url in urls:
        try:
            filename, data = fetch(url)
        except OSError as exc:
            report.errors.append(f"{url}: could not be fetched ({exc}); this is not evidence of a problem, it will be retried")
            continue
        name = _safe_name(filename)
        suffix = PurePosixPath(name).suffix.lower()
        if suffix not in UPLOAD_SUFFIXES:
            report.errors.append(f"{url}: file type {suffix or '(none)'} is not accepted")
            continue
        if len(data) > LIMITS["total_bytes"]:
            report.errors.append(f"{url}: larger than the 25 MiB limit")
            continue
        if suffix == ".zip":
            expand_zip(data, url, report, budget=budget)
            continue
        if len(data) > LIMITS["file_bytes"]:
            report.errors.append(f"{url}: larger than the 5 MiB per-file limit")
            continue
        budget[0] -= len(data)
        if budget[0] < 0:
            report.errors.append("the attachments exceed the 25 MiB limit")
            break
        report.files.append(Attachment(name, data, url))
    return report
