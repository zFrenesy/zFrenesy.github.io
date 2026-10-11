"""Policy catalog: platform settings, disciplines, classifications, profiles and alias schemes.

Disciplines are configuration, not code (§14): adding one needs a file in
``policies/disciplines/``, optionally a classification vocabulary, and tests.
Every file is loaded with the strict YAML profile and validated against its
schema; cross-file consistency problems raise ``CatalogError``.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any

from rp import PACKAGE_ROOT, strict_yaml
from rp.identity.aliases import AliasError, AliasPolicy, AliasScheme
from rp.strict_yaml import StrictYamlError
from rp.validation.records import validate_record
from rp.vocab import OPEN_DISCIPLINE_STATUSES

__all__ = ["Catalog", "CatalogError", "default_catalog"]


class CatalogError(ValueError):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("invalid policy catalog:\n  " + "\n  ".join(problems))


def _yaml_files(directory: Traversable) -> list[Traversable]:
    if not directory.is_dir():
        return []
    return sorted((e for e in directory.iterdir() if e.name.endswith(".yaml")), key=lambda e: e.name)


def _load(entry: Traversable, record_type: str, problems: list[str]) -> dict[str, Any] | None:
    try:
        data = strict_yaml.load(entry.read_bytes())
    except (StrictYamlError, OSError) as exc:
        problems.append(f"{entry.name}: {exc}")
        return None
    issues = [i for i in validate_record(record_type, data, catalog=None) if i.severity == "error"]
    problems.extend(f"{entry.name}: {issue}" for issue in issues)
    return None if issues else data


@dataclass(frozen=True)
class Catalog:
    platform: Mapping[str, Any]
    disciplines: Mapping[str, Mapping[str, Any]]
    classifications: Mapping[str, Mapping[str, Any]]
    profiles: Mapping[tuple[str, int], Mapping[str, Any]]
    alias_policy: AliasPolicy
    external_hosts: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, policies_dir: str | Path | Traversable | None = None, profiles_dir: str | Path | Traversable | None = None) -> Catalog:
        policies = Path(policies_dir) if isinstance(policies_dir, str) else policies_dir or PACKAGE_ROOT / "policies"
        profile_root = Path(profiles_dir) if isinstance(profiles_dir, str) else profiles_dir or PACKAGE_ROOT / "profiles"
        problems: list[str] = []

        platform = _load(policies / "platform.yaml", "platform", problems)
        namespaces = _load(policies / "alias-namespaces.yaml", "alias_namespaces", problems)
        hosts = _load(policies / "external-hosts.yaml", "external_hosts", problems) if (policies / "external-hosts.yaml").is_file() else {}

        disciplines: dict[str, Mapping[str, Any]] = {}
        for entry in _yaml_files(policies / "disciplines"):
            if (data := _load(entry, "discipline", problems)) is not None:
                if entry.name != f"{data['slug']}.yaml":
                    problems.append(f"{entry.name}: file name must be {data['slug']}.yaml")
                disciplines[data["slug"]] = data

        classifications: dict[str, Mapping[str, Any]] = {}
        for entry in _yaml_files(policies / "classifications"):
            if (data := _load(entry, "classification", problems)) is not None:
                if entry.name != f"{data['scheme']}.yaml":
                    problems.append(f"{entry.name}: file name must be {data['scheme']}.yaml")
                bad = [c for c in data["top_level_codes"] if len(c) != data["top_level_length"]]
                if bad:
                    problems.append(f"{entry.name}: codes {bad} do not have length {data['top_level_length']}")
                classifications[data["scheme"]] = data

        profiles: dict[tuple[str, int], Mapping[str, Any]] = {}
        for entry in _yaml_files(profile_root):
            if (data := _load(entry, "profile", problems)) is not None:
                if entry.name != f"{data['id']}.yaml":
                    problems.append(f"{entry.name}: file name must be {data['id']}.yaml")
                profiles[(data["id"], data["version"])] = data

        if platform is None or namespaces is None or hosts is None:
            raise CatalogError(problems)

        profile_ids = {pid for pid, _ in profiles}
        prefixes: dict[str, str] = {}
        for slug, config in disciplines.items():
            if (other := prefixes.get(config["alias_prefix"])) is not None:
                problems.append(f"{slug}: alias prefix {config['alias_prefix']} is already used by {other}")
            prefixes[config["alias_prefix"]] = slug
            for pid in config["profiles"]:
                if pid not in profile_ids:
                    problems.append(f"{slug}: unknown profile {pid!r}")
            cls_config = config["classification"]
            if cls_config:
                vocab = cls_config["vocabulary"]
                if vocab is not None and (vocab not in classifications or classifications[vocab]["scheme"] != cls_config["scheme"]):
                    problems.append(f"{slug}: classification vocabulary {vocab!r} is missing or for another scheme")
        for host in platform["allowed_external_hosts"]:
            if hosts and host not in hosts["artifact_hosts"]:
                problems.append(f"platform.yaml: allowed external host {host!r} has no entry in external-hosts.yaml")
        for section in platform["site"]["discipline_sections"]:
            config = disciplines.get(section)
            if config is None or config["status"] not in OPEN_DISCIPLINE_STATUSES:
                problems.append(f"platform.yaml: site section {section!r} is not an active or pilot discipline")

        schemes = [
            AliasScheme(
                s["id"], s["prefix"], s["allocation"], s["allocation_authority"], s["local_pattern"], True, s["external_scheme"]
            )
            for s in namespaces["schemes"]
        ]
        schemes += [
            AliasScheme(
                f"discipline:{slug}",
                config["alias_prefix"],
                "counter",
                platform["organisation"],
                enabled=config["status"] in OPEN_DISCIPLINE_STATUSES,
            )
            for slug, config in sorted(disciplines.items())
        ]
        try:
            alias_policy = AliasPolicy(schemes, platform_authority=platform["organisation"])
        except AliasError as exc:
            problems.append(str(exc))
            alias_policy = None  # type: ignore[assignment]

        if problems:
            raise CatalogError(problems)
        return cls(platform, disciplines, classifications, profiles, alias_policy, hosts)

    def classification_problem(self, scheme: str, code: str) -> str | None:
        """Return why ``code`` is not a valid code of ``scheme``, or None when it is."""
        config = next(
            (d["classification"] for d in self.disciplines.values() if d["classification"] and d["classification"]["scheme"] == scheme),
            None,
        )
        if config is None:
            return f"unknown classification scheme {scheme!r}"
        if not re.fullmatch(config["code_pattern"], code):
            return f"{code!r} is not a {config['name']} code"
        vocab = self.classifications.get(config["vocabulary"]) if config["vocabulary"] else None
        if vocab is not None and code[: vocab["top_level_length"]] not in vocab["top_level_codes"]:
            return f"{code!r} is not under a known {config['name']} top-level class"
        return None

    def open_disciplines(self) -> list[str]:
        return sorted(slug for slug, d in self.disciplines.items() if d["status"] in OPEN_DISCIPLINE_STATUSES)


@functools.cache
def default_catalog() -> Catalog:
    return Catalog.load()
