"""Tier-0 checks for a contribution change set (spec §7, §8.1 tier 0, §16.1).

The same code runs locally (``rp check``) and in the pull-request check. A change
set may only *add* files inside new contribution, review or proposed-problem
folders; anything else (workflows, configuration, other people's records,
deletions, renames) fails. Each new folder is then validated in full: schema and
semantic rules, the exact artifact manifest, sizes, modes, link pins and hosts,
and its relationship to existing problems. Contributor files are never executed.
"""

from __future__ import annotations

import re
import stat
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from rp import strict_yaml
from rp.catalog import Catalog, default_catalog
from rp.fingerprint import ManifestError, manifest_from_directory
from rp.identity.ids import is_id
from rp.identity.paths import InvalidPath, check_relative_path, contribution_dir, problem_dir
from rp.strict_yaml import StrictYamlError
from rp.validation.records import publication_issues, validate_record

__all__ = ["CheckReport", "LIMITS", "changed_paths", "check_changes"]

LIMITS = {"files": 200, "file_bytes": 5 * 1024 * 1024, "total_bytes": 25 * 1024 * 1024}
ALLOWED_SUFFIXES = {".tex", ".bib", ".md", ".pdf", ".png", ".jpg", ".jpeg", ".csv", ".json", ".txt", ".yaml"}
LINK_HOSTS = {
    "github": {"github.com"},
    "hugging_face": {"huggingface.co"},
    "zenodo": {"zenodo.org", "doi.org"},
    "software_heritage": {"archive.softwareheritage.org"},
}
_FOLDER = re.compile(r"problems/([0-9a-f]{2})/(prb_[0-9a-f]{32})(?:/(contributions|reviews)/(con_[0-9a-f]{32}))?")


@dataclass
class CheckReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    folders: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def render(self) -> str:
        lines = [f"Checked {len(self.folders)} new folder(s): " + (", ".join(self.folders) or "none")]
        lines += [f"error: {e}" for e in self.errors]
        lines += [f"warning: {w}" for w in self.warnings]
        lines.append("PASS" if self.ok else "FAIL")
        return "\n".join(lines)


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(root), "-c", "core.quotePath=false", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:2])} failed: {proc.stderr.strip()[:300]}")
    return proc.stdout


def changed_paths(root: Path, base: str | None, head: str | None) -> list[tuple[str, str]]:
    """(status, path) for every change between base and head, plus uncommitted work when head is None.

    Renames and copies are reported as separate delete/add pairs (no rename detection),
    so a rename can never hide the removal of an existing file.
    """
    changes: list[tuple[str, str]] = []
    if base:
        target = head or "HEAD"
        out = _git(root, "diff", "--no-renames", "--name-status", "-z", f"{base}...{target}")
        parts = [p for p in out.split("\0") if p]
        changes += [(parts[i], parts[i + 1]) for i in range(0, len(parts), 2)]
    if head is None:
        out = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames")
        for entry in (e for e in out.split("\0") if e):
            code, path = entry[:2], entry[3:]
            changes.append(("A" if code == "??" else code.strip()[:1] or "M", path))
    seen: dict[str, str] = {}
    for status, path in changes:
        seen[path] = "A" if status == "A" and seen.get(path, "A") == "A" else status
    return sorted((s, p) for p, s in seen.items())


def _folder_key(path: str) -> tuple[str, str] | None:
    """The new folder a path belongs to: ('contribution', folder) or ('problem', folder)."""
    for end in range(len(path.split("/")), 2, -1):
        prefix = "/".join(path.split("/")[:end])
        match = _FOLDER.fullmatch(prefix)
        if match:
            return ("contribution" if match.group(4) else "problem", prefix)
    return None


def check_changes(root: Path, changes: list[tuple[str, str]], catalog: Catalog | None = None) -> CheckReport:
    catalog = catalog or default_catalog()
    report = CheckReport()
    folders: dict[tuple[str, str], list[str]] = defaultdict(list)
    for status, path in changes:
        try:
            check_relative_path(path)
        except InvalidPath as exc:
            report.errors.append(f"{path}: {exc}")
            continue
        key = _folder_key(path)
        if status != "A":
            report.errors.append(f"{path}: only new files may be added; existing files cannot be modified, renamed or deleted (status {status})")
        elif key is None:
            report.errors.append(f"{path}: outside a new contribution, review or problem folder")
        else:
            folders[key].append(path)
    if not changes:
        report.errors.append("no changes found; create a contribution with `rp new attempt <ALIAS>` first")
    problem_folders = {f for kind, f in folders if kind == "problem"}
    for (kind, folder), paths in sorted(folders.items()):
        if kind == "contribution":
            parent = "/".join(folder.split("/")[:3])
            if parent in problem_folders:
                report.errors.append(f"{folder}: a contribution and a new problem cannot be submitted together")
                continue
            _check_contribution(root, folder, paths, catalog, report)
        else:
            _check_problem(root, folder, paths, catalog, report)
        report.folders.append(folder)
    if len(folders) > 1:
        report.warnings.append("several new folders in one change; one contribution per pull request is easier to review")
    return report


def _limits(root: Path, folder: str, report: CheckReport) -> None:
    files = [p for p in (root / folder).rglob("*") if p.is_file() or p.is_symlink()]
    if len(files) > LIMITS["files"]:
        report.errors.append(f"{folder}: {len(files)} files exceeds the limit of {LIMITS['files']}")
    total = 0
    for path in files:
        rel = path.relative_to(root).as_posix()
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            report.errors.append(f"{rel}: symbolic links are not allowed")
            continue
        if info.st_mode & 0o111:
            report.errors.append(f"{rel}: executable files are not allowed")
        if path.suffix.lower() not in ALLOWED_SUFFIXES:
            report.errors.append(f"{rel}: file type {path.suffix or '(none)'} is not accepted; link code, notebooks and data instead")
        if info.st_size > LIMITS["file_bytes"]:
            report.errors.append(f"{rel}: {info.st_size} bytes exceeds the 5 MiB per-file limit")
        total += info.st_size
    if total > LIMITS["total_bytes"]:
        report.errors.append(f"{folder}: {total} bytes exceeds the 25 MiB limit")


def _todo(value: Any, where: str, report: CheckReport) -> None:
    if isinstance(value, str) and "TODO" in value:
        report.errors.append(f"{where}: placeholder not filled in ({value[:60]!r})")
    elif isinstance(value, dict):
        for k, v in value.items():
            _todo(v, f"{where}.{k}", report)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _todo(v, f"{where}[{i}]", report)


def _links(record: dict, folder: str, catalog: Catalog, report: CheckReport) -> None:
    hosts = set().union(*(LINK_HOSTS.get(h, set()) for h in catalog.platform["allowed_external_hosts"]))
    for index, artifact in enumerate(record.get("artifacts", [])):
        if artifact.get("location") != "external_pinned":
            continue
        host = (urlsplit(artifact["external"]["url"]).hostname or "").lower()
        if host not in hosts:
            report.errors.append(f"{folder}: artifact {index} links to {host or 'an invalid URL'}; allowed hosts are {', '.join(sorted(hosts))}")


def _load(root: Path, path: str, report: CheckReport) -> dict | None:
    try:
        return strict_yaml.load((root / path).read_bytes())
    except FileNotFoundError:
        report.errors.append(f"{path}: missing")
    except StrictYamlError as exc:
        report.errors.append(f"{path}: {exc}")
    return None


def _check_contribution(root: Path, folder: str, paths: list[str], catalog: Catalog, report: CheckReport) -> None:
    _limits(root, folder, report)
    record = _load(root, folder + "/contribution.yaml", report)
    if record is None:
        return
    _todo(record, folder + "/contribution.yaml", report)
    for issue in validate_record("contribution", record, catalog=catalog):
        (report.errors if issue.severity == "error" else report.warnings).append(f"{folder}/contribution.yaml {issue}")
    if any(i.startswith(f"{folder}/contribution.yaml error") for i in report.errors):
        return
    if record["type"] not in ("attempt", "counterexample", "review", "author_response", "correction", "replication"):
        report.errors.append(f"{folder}: contributions of type {record['type']} cannot be submitted")
    expected = contribution_dir(record["home_problem_id"], record["contribution_id"], record["type"]).as_posix()
    if folder != expected:
        report.errors.append(f"{folder}: must be {expected} (folder must match the record's home problem, type and ID)")
    if record["expected_predecessor"] is not None:
        report.errors.append(f"{folder}: a new contribution has no predecessor; revisions of existing contributions use the editor route")
    home = root / problem_dir(record["home_problem_id"]) / "problem.yaml"
    if not home.is_file():
        report.errors.append(f"{folder}: home problem {record['home_problem_id']} does not exist")
    for target in record["targets"]:
        if target["target_kind"] == "problem":
            problem_yaml = root / problem_dir(target["problem_id"]) / "problem.yaml"
            if not problem_yaml.is_file():
                report.errors.append(f"{folder}: target problem {target['problem_id']} does not exist")
                continue
            current = strict_yaml.load(problem_yaml.read_bytes())["statement_revision_id"]
            if target["statement_revision_id"] != current:
                report.errors.append(f"{folder}: target statement revision {target['statement_revision_id']} is not the current one ({current})")
    try:
        manifest_from_directory(root / folder, record["artifacts"])
    except ManifestError as exc:
        report.errors.append(f"{folder}: {exc}")
    _links(record, folder, catalog, report)
    report.warnings.extend(f"{folder}: {issue.message}; the submitter confirms this before publication" for issue in publication_issues(record))


def _check_problem(root: Path, folder: str, paths: list[str], catalog: Catalog, report: CheckReport) -> None:
    _limits(root, folder, report)
    record = _load(root, folder + "/problem.yaml", report)
    if record is None:
        return
    _todo(record, folder + "/problem.yaml", report)
    for issue in validate_record("problem", record, catalog=catalog):
        (report.errors if issue.severity == "error" else report.warnings).append(f"{folder}/problem.yaml {issue}")
    if record.get("kind") not in ("proposed", "derived", "literature"):
        report.errors.append(f"{folder}: contributors may propose literature, proposed or derived problems only")
    if is_id(record.get("problem_id"), "problem") and folder != problem_dir(record["problem_id"]).as_posix():
        report.errors.append(f"{folder}: must be {problem_dir(record['problem_id']).as_posix()}")
    statement = record.get("statement_artifact", {}).get("path")
    if statement and not (root / folder / statement).is_file():
        report.errors.append(f"{folder}: statement file {statement} is missing")
    extra = sorted(set(p.split("/", 3)[3] for p in paths) - {"problem.yaml", statement})
    if extra:
        report.errors.append(f"{folder}: unexpected files {extra}")
