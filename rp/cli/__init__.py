"""Command-line interface (``python -m rp``).

Milestone 1 provides diagnostics only: ``validate``, ``fingerprint`` and
``id new``. ``rp start``, ``rp check``, ``rp submit`` and ``rp export`` arrive
in milestone 3. The CLI never executes anything found in research content.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path

from rp.catalog import default_catalog
from rp.fingerprint import ManifestError, manifest_from_directory, scientific_fingerprint, scientific_metadata_digest
from rp.identity.ids import KIND_PREFIXES, new_id
from rp.strict_yaml import StrictYamlError
from rp.validation.records import RECORD_TYPES, RecordLoadError, load_record, validate_file, validate_record

RECORD_SUFFIXES = (".yaml", ".yml", ".json")


def _record_files(paths: Sequence[str]) -> Iterator[Path]:
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            yield from sorted(p for p in path.rglob("*") if p.suffix in RECORD_SUFFIXES and p.is_file())
        else:
            yield path


def cmd_validate(args: argparse.Namespace) -> int:
    catalog = default_catalog()
    failed = 0
    count = 0
    for path in _record_files(args.paths):
        count += 1
        issues = validate_file(path, record_type=args.type, catalog=catalog)
        errors = [i for i in issues if i.severity == "error"]
        failed += bool(errors)
        if issues:
            print(f"{path}:")
            for issue in issues:
                print(f"  {issue}")
        elif args.verbose:
            print(f"{path}: ok")
    print(f"{count - failed} of {count} files valid")
    return 1 if failed or count == 0 else 0


def cmd_fingerprint(args: argparse.Namespace) -> int:
    folder = Path(args.directory)
    try:
        contribution = load_record(folder / "contribution.yaml")
    except (StrictYamlError, RecordLoadError, OSError) as exc:
        print(exc, file=sys.stderr)
        return 1
    errors = [i for i in validate_record("contribution", contribution, catalog=default_catalog()) if i.severity == "error"]
    if errors:
        for issue in errors:
            print(issue, file=sys.stderr)
        return 1
    try:
        manifest = manifest_from_directory(folder, contribution["artifacts"])
    except ManifestError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "scientific_fingerprint": scientific_fingerprint(contribution, manifest),
                "scientific_metadata_digest": scientific_metadata_digest(contribution),
                "artifact_manifest": manifest,
            },
            indent=2,
        )
    )
    return 0


def cmd_id(args: argparse.Namespace) -> int:
    print(new_id(args.kind))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rp", description="we-solve research platform tools")
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate", help="validate records against schemas and policy")
    validate.add_argument("paths", nargs="+", help="files or directories")
    validate.add_argument("--type", choices=sorted(RECORD_TYPES), help="record type (default: inferred from the path)")
    validate.add_argument("-v", "--verbose", action="store_true")
    validate.set_defaults(func=cmd_validate)

    fingerprint = sub.add_parser("fingerprint", help="print the scientific fingerprint S of a contribution folder")
    fingerprint.add_argument("directory")
    fingerprint.set_defaults(func=cmd_fingerprint)

    ident = sub.add_parser("id", help="identifier tools")
    ident_sub = ident.add_subparsers(dest="id_command", required=True)
    new = ident_sub.add_parser("new", help="print a new identifier")
    new.add_argument("kind", choices=sorted(KIND_PREFIXES))
    new.set_defaults(func=cmd_id)

    args = parser.parse_args(argv)
    return args.func(args)
