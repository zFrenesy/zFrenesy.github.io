"""Artifact manifests, the scientific fingerprint S and the authorization binding K (§4, docs/adr/0004).

S identifies *what* is being published: all authored metadata except the
identity fields, plus attribution, target statement revisions, dependency
references and the sorted manifest of exact artifact bytes and external pins.
Identity-only changes (a new revision ID for identical content) leave S
unchanged, so screening reports cached by S stay reusable.

K binds an authorization decision to *where and how* it was made: repository,
pull request, head and base commits, S, expected predecessor, policy and
rubric versions, review-context digest and editor state. Any change to any
input produces a different K, so a stale decision can never be matched.
"""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from rp.canonical import canonical_json, digest, is_digest, sha256_digest
from rp.identity.ids import is_id
from rp.identity.paths import InvalidPath, check_relative_path

__all__ = [
    "BindingError",
    "ManifestError",
    "authorization_binding",
    "editor_state_digest",
    "manifest_from_blobs",
    "manifest_from_directory",
    "manifest_sort_key",
    "problem_fingerprint",
    "scientific_fingerprint",
    "scientific_metadata",
    "scientific_metadata_digest",
]

IDENTITY_FIELDS = ("contribution_id", "revision_id", "expected_predecessor")
ATTRIBUTION_FIELDS = ("attribution", "model_uses")
STRUCTURE_FIELDS = ("targets", "lineage")
PROBLEM_IDENTITY_FIELDS = ("problem_id", "statement_revision_id", "expected_statement_predecessor")
REGULAR_MODES = ("100644", "100755")
_SHA = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_REPOSITORY = re.compile(r"[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}")
_POLICY = re.compile(r"policy/[1-9][0-9]*")
_RUBRIC = re.compile(r"rubric/[1-9][0-9]*")


class ManifestError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


class BindingError(ValueError):
    pass


def manifest_sort_key(entry: Mapping[str, Any]) -> tuple[str, ...]:
    if entry["location"] == "in_repository":
        return ("0", entry["logical_path"])
    return ("1", entry["url"], entry["pin"]["kind"], entry["pin"]["value"])


def manifest_from_blobs(blobs: Mapping[str, tuple[bytes, str]], declared_artifacts: Iterable[Mapping[str, Any]]) -> list[dict]:
    """Build the sorted manifest from exact blobs.

    ``blobs`` maps each path relative to the contribution folder (``files/...``)
    to ``(content, git_mode)``. Every blob must be declared and every declared
    in-repository artifact must be present; symlinks (mode 120000), submodules
    (160000) and paths outside ``files/`` are rejected.
    """
    entries: list[dict] = []
    for path, (content, mode) in blobs.items():
        try:
            clean = check_relative_path(path)
        except InvalidPath as exc:
            raise ManifestError("manifest.path", str(exc)) from exc
        if clean.parts[0] != "files" or len(clean.parts) < 2:
            raise ManifestError("manifest.outside_files", f"{path} is outside files/")
        if mode not in REGULAR_MODES:
            raise ManifestError("manifest.mode", f"{path} has mode {mode}; only regular files are allowed")
        entries.append(
            {"location": "in_repository", "logical_path": path, "digest": sha256_digest(content), "bytes": len(content), "mode": mode}
        )
    declared = list(declared_artifacts)
    declared_paths = {a["path"] for a in declared if a["location"] == "in_repository"}
    present = set(blobs)
    if missing := sorted(declared_paths - present):
        raise ManifestError("manifest.missing_file", f"declared but absent: {', '.join(missing)}")
    if undeclared := sorted(present - declared_paths):
        raise ManifestError("manifest.undeclared_file", f"present but not declared: {', '.join(undeclared)}")
    seen_links: set[bytes] = set()
    for artifact in declared:
        if artifact["location"] == "external_pinned":
            entry = {"location": "external_pinned", "url": artifact["external"]["url"], "pin": dict(artifact["external"]["pin"])}
            key = canonical_json(entry)
            if key in seen_links:
                raise ManifestError("manifest.duplicate", f"external link {entry['url']} declared twice")
            seen_links.add(key)
            entries.append(entry)
    return sorted(entries, key=manifest_sort_key)


def manifest_from_directory(contribution_dir: str | Path, declared_artifacts: Iterable[Mapping[str, Any]]) -> list[dict]:
    """Build the manifest from a local contribution folder (CLI use). Never follows symlinks."""
    root = Path(contribution_dir)
    files_root = root / "files"
    blobs: dict[str, tuple[bytes, str]] = {}
    if os.path.lexists(files_root):
        if not stat.S_ISDIR(os.lstat(files_root).st_mode):
            raise ManifestError("manifest.special_file", "files/ must be a real directory")
        for current, dirnames, filenames in os.walk(files_root, followlinks=False):
            for name in sorted(dirnames + filenames):
                full = Path(current) / name
                info = os.lstat(full)
                relative = full.relative_to(root).as_posix()
                if stat.S_ISLNK(info.st_mode):
                    raise ManifestError("manifest.symlink", f"{relative} is a symbolic link")
                if stat.S_ISDIR(info.st_mode):
                    continue
                if not stat.S_ISREG(info.st_mode):
                    raise ManifestError("manifest.special_file", f"{relative} is not a regular file")
                mode = "100755" if info.st_mode & 0o111 else "100644"
                blobs[relative] = (full.read_bytes(), mode)
    return manifest_from_blobs(blobs, declared_artifacts)


def scientific_metadata(contribution: Mapping[str, Any]) -> dict[str, Any]:
    """The authored document without identity fields or platform-assigned artifact IDs."""
    meta = {key: value for key, value in contribution.items() if key not in IDENTITY_FIELDS}
    meta["artifacts"] = [{k: v for k, v in a.items() if k != "artifact_id"} for a in contribution.get("artifacts", [])]
    return meta


def scientific_metadata_digest(contribution: Mapping[str, Any]) -> str:
    return digest(scientific_metadata(contribution))


def scientific_fingerprint(contribution: Mapping[str, Any], manifest: list[Mapping[str, Any]]) -> str:
    meta = scientific_metadata(contribution)
    return digest(
        {
            "version": "S/1",
            "metadata": {k: v for k, v in meta.items() if k not in ATTRIBUTION_FIELDS + STRUCTURE_FIELDS},
            "attribution": {"attribution": meta["attribution"], "model_uses": meta["model_uses"]},
            "target_statement_revisions": sorted(meta["targets"], key=canonical_json),
            "dependencies": sorted(meta["lineage"], key=canonical_json),
            "manifest": sorted(manifest, key=manifest_sort_key),
        }
    )


def problem_fingerprint(problem: Mapping[str, Any], statement: bytes) -> str:
    """Fingerprint of a proposed problem candidate: metadata without identity fields plus the statement bytes."""
    meta = {key: value for key, value in problem.items() if key not in PROBLEM_IDENTITY_FIELDS}
    return digest({"version": "P/1", "metadata": meta, "statement": sha256_digest(statement)})


def editor_state_digest(*, owner: str, editors: Iterable[str]) -> str:
    """Digest of who may edit a contribution, read from the ledger (never from author YAML)."""
    people = [owner, *editors]
    if not all(is_id(p, "person") for p in people):
        raise BindingError("editor state lists person identifiers only")
    return digest({"version": "E/1", "owner": owner, "editors": sorted(set(editors))})


def authorization_binding(
    *,
    repository: str,
    pull_request: int,
    head_sha: str,
    base_sha: str,
    scientific_fingerprint: str,
    expected_predecessor: str | None,
    policy_version: str,
    rubric_version: str,
    review_context_digest: str,
    editor_state_digest: str,
) -> str:
    """Compute K. Every input is validated; anything missing or malformed raises (fail closed)."""
    checks = [
        (isinstance(repository, str) and _REPOSITORY.fullmatch(repository), "repository"),
        (isinstance(pull_request, int) and not isinstance(pull_request, bool) and pull_request > 0, "pull_request"),
        (isinstance(head_sha, str) and _SHA.fullmatch(head_sha), "head_sha"),
        (isinstance(base_sha, str) and _SHA.fullmatch(base_sha), "base_sha"),
        (is_digest(scientific_fingerprint), "scientific_fingerprint"),
        (expected_predecessor is None or is_id(expected_predecessor, "revision"), "expected_predecessor"),
        (isinstance(policy_version, str) and _POLICY.fullmatch(policy_version), "policy_version"),
        (isinstance(rubric_version, str) and _RUBRIC.fullmatch(rubric_version), "rubric_version"),
        (is_digest(review_context_digest), "review_context_digest"),
        (is_digest(editor_state_digest), "editor_state_digest"),
    ]
    if bad := [name for ok, name in checks if not ok]:
        raise BindingError(f"invalid authorization binding inputs: {', '.join(bad)}")
    return digest(
        {
            "version": "K/1",
            "repository": repository,
            "pull_request": pull_request,
            "head_sha": head_sha,
            "base_sha": base_sha,
            "scientific_fingerprint": scientific_fingerprint,
            "expected_predecessor": expected_predecessor,
            "policy_version": policy_version,
            "rubric_version": rubric_version,
            "review_context_digest": review_context_digest,
            "editor_state_digest": editor_state_digest,
        }
    )
