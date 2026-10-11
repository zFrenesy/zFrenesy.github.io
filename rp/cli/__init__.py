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


def _research(args: argparse.Namespace):
    from rp.contribute.workspace import Research

    return Research.here(Path(args.dir) if getattr(args, "dir", None) else None)


def cmd_start(args: argparse.Namespace) -> int:
    path = _research(args).start(args.alias)
    print(f"Wrote {path}")
    print("It holds the statement, sources and earlier contributions as quoted, untrusted material.")
    print(f"Next: rp new attempt {args.alias.upper()}")
    return 0


def cmd_new(args: argparse.Namespace) -> int:
    from rp.contribute.workspace import github_identity

    research = _research(args)
    identity = github_identity()
    if args.what == "attempt":
        folder = research.new_attempt(args.alias, identity)
    elif args.what == "review":
        folder = research.new_review(args.alias, identity)
    else:
        folder = research.new_problem(args.parent, identity)
    print(f"Created {folder.relative_to(research.root)}")
    print("Fill in every TODO, add your files under files/ and list them in the record, then run: rp check")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    from rp.contribute.check import changed_paths, check_changes
    from rp.contribute.submit import _default_base

    research = _research(args)
    base = args.base or (None if args.head else _default_base(research.root))
    report = check_changes(research.root, changed_paths(research.root, base, args.head))
    print(report.render())
    return 0 if report.ok else 1


def cmd_submit(args: argparse.Namespace) -> int:
    from rp.contribute.submit import submit

    try:
        submit(_research(args).root, yes=args.yes, dry_run=args.dry_run, base=args.base)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_intake(args: argparse.Namespace) -> int:
    from rp.intake.engine import process
    from rp.intake.github import GhReadOnly
    from rp.intake.publication import apply_plan
    from rp.timeutil import SystemClock

    research = _research(args)
    port = GhReadOnly(args.repo)
    if args.pr:
        snapshot, blobs = port.snapshot_pull(args.pr)
    else:
        snapshot, blobs = port.snapshot_issue(args.issue), None
    now = args.now or SystemClock().now().isoformat()
    plan = process(snapshot, research, app_id=args.app_id, now=now, blobs=blobs)
    print(f"{snapshot.kind} #{snapshot.number} by {snapshot.author.login} (ID {snapshot.author.id}): status {plan.state.status}")
    for warning in plan.warnings:
        print(f"warning: {warning}")
    outcome = plan.outcome
    if outcome is not None:
        for line in outcome.blocking:
            print(f"blocking: {line}")
        for number, question in enumerate(outcome.questions, 1):
            print(f"question {number} [{question.key}]: {question.text}" + (f" (default: {question.default})" if question.default else ""))
        if outcome.candidate is not None:
            print(f"candidate: {outcome.candidate.folder}")
            print(outcome.candidate.report.render())
    apply_plan(plan, port, snapshot, app_id=args.app_id)
    print("Nothing was changed on GitHub (dry run).")
    return 0


def cmd_intake_run(args: argparse.Namespace) -> int:
    """Process one event, or every open intake item (scheduled reconciliation). Used only by intake.yml."""
    from rp.intake.engine import process
    from rp.intake.github import GhLive
    from rp.intake.publication import apply_plan
    from rp.timeutil import SystemClock

    research = _research(args)
    port = GhLive(args.repo)
    numbers: list[int] = []
    if args.event:
        event = json.loads(Path(args.event).read_text(encoding="utf-8"))
        comment = event.get("comment") or {}
        if (comment.get("performed_via_github_app") or {}).get("id") == args.app_id:
            print("skipping the App's own comment")
            return 0
        item = event.get("issue") or event.get("pull_request") or {}
        if item.get("number"):
            numbers.append(int(item["number"]))
    else:
        for page in port.api.pages(f"repos/{args.repo}/issues?state=open&labels=intake"):
            numbers.extend(i["number"] for i in page)
    failed = 0
    for number in numbers:
        try:
            snapshot = port.snapshot_issue(number)
            blobs = None
            if snapshot.kind == "pull_request":
                snapshot, blobs = port.snapshot_pull(number)
            plan = process(snapshot, research, app_id=args.app_id, now=SystemClock().now().isoformat(), blobs=blobs)
            apply_plan(plan, port, snapshot, app_id=args.app_id)
            print(f"#{number}: {plan.state.status}")
        except Exception as exc:  # one failing item must not block the others; it is retried next run
            failed += 1
            print(f"#{number}: error: {exc}", file=sys.stderr)
    return 1 if failed else 0


def cmd_links(args: argparse.Namespace) -> int:
    from rp import strict_yaml
    from rp.contribute.check import changed_paths, folder_key, read_folder
    from rp.validation.links import BoundedHttp, check_external_links, verify_pins

    research = _research(args)
    folders = sorted({key[1] for _, path in changed_paths(research.root, args.base, args.head) if (key := folder_key(path))})
    failed = False
    http = BoundedHttp()
    for folder in folders:
        files = read_folder(research.root, folder)
        name = "contribution.yaml" if "contribution.yaml" in files else "problem.yaml"
        if name not in files:
            continue
        record = strict_yaml.load(files[name][0])
        texts = {n: c for n, (c, _m) in files.items()}
        report = verify_pins(check_external_links(record, texts, where=folder), http)
        for issue in report.issues:
            print(f"{issue.severity}: {issue}")
        for note in report.notes:
            print(f"note: {note}")
        failed |= not report.ok
    print("FAIL" if failed else f"PASS ({len(folders)} folder(s))")
    return 1 if failed else 0


def cmd_links_sweep(args: argparse.Namespace) -> int:
    from rp.validation.links import BoundedHttp, sweep_links

    research = _research(args)
    status = sweep_links(research.root, BoundedHttp())
    Path(args.out).write_text(json.dumps(status, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    counts: dict[str, int] = {}
    for entry in status["links"].values():
        counts[entry["state"]] = counts.get(entry["state"], 0) + 1
    print(f"Wrote {args.out}: " + (", ".join(f"{n} {s}" for s, n in sorted(counts.items())) or "no linked artifacts"))
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

    start = sub.add_parser("start", help="prepare a working context for a problem")
    start.add_argument("alias")
    start.add_argument("--dir", help="research repository (default: current directory)")
    start.set_defaults(func=cmd_start)

    create = sub.add_parser("new", help="create a new contribution, review or problem folder")
    create.add_argument("what", choices=["attempt", "review", "problem"])
    create.add_argument("alias", nargs="?", help="problem handle (attempt) or contribution handle (review)")
    create.add_argument("--parent", help="parent problem handle for a subproblem")
    create.add_argument("--dir")
    create.set_defaults(func=cmd_new)

    check = sub.add_parser("check", help="run the submission checks on your changes")
    check.add_argument("--base", help="compare against this commit (default: upstream/main or origin/main, plus uncommitted work)")
    check.add_argument("--head", help="compare up to this commit (CI); omit to include uncommitted work")
    check.add_argument("--dir")
    check.set_defaults(func=cmd_check)

    send = sub.add_parser("submit", help="open a pull request from your own GitHub account")
    send.add_argument("--yes", action="store_true", help="do not ask before pushing (declarations stay unconfirmed)")
    send.add_argument("--dry-run", action="store_true", help="show the commands without running them")
    send.add_argument("--base")
    send.add_argument("--dir")
    send.set_defaults(func=cmd_submit)

    intake = sub.add_parser("intake", help="intake bot tools")
    intake_sub = intake.add_subparsers(dest="intake_command", required=True)
    dry = intake_sub.add_parser("dry-run", help="show what the intake bot would do for an issue or pull request; changes nothing")
    dry.add_argument("--repo", required=True, help="OWNER/NAME of the research repository")
    target = dry.add_mutually_exclusive_group(required=True)
    target.add_argument("--issue", type=int)
    target.add_argument("--pr", type=int)
    dry.add_argument("--app-id", type=int, default=0, help="intake App ID whose state comments are trusted (default: none)")
    dry.add_argument("--now", help="UTC instant to evaluate reminders at (default: now)")
    dry.add_argument("--dir", help="local research checkout (default: current directory)")
    dry.set_defaults(func=cmd_intake)
    live = intake_sub.add_parser("run", help="(intake App workflow only) process an event or all open intake items")
    live.add_argument("--repo", required=True)
    live.add_argument("--app-id", type=int, required=True)
    live_target = live.add_mutually_exclusive_group(required=True)
    live_target.add_argument("--event", help="path to the GitHub event JSON")
    live_target.add_argument("--all-open", action="store_true")
    live.add_argument("--dir")
    live.set_defaults(func=cmd_intake_run)

    links = sub.add_parser("links", help="external link checks")
    links_sub = links.add_subparsers(dest="links_command", required=True)
    verify = links_sub.add_parser("verify", help="check pinned artifact links in new folders through the GitHub and Hugging Face APIs")
    verify.add_argument("--base")
    verify.add_argument("--head")
    verify.add_argument("--dir")
    verify.set_defaults(func=cmd_links)
    sweep = links_sub.add_parser("sweep", help="check every pinned artifact link and write an availability file for the site")
    sweep.add_argument("--out", required=True)
    sweep.add_argument("--dir")
    sweep.set_defaults(func=cmd_links_sweep)

    args = parser.parse_args(argv)
    if args.func is cmd_new and args.what != "problem" and not args.alias:
        parser.error(f"rp new {args.what} needs a handle")
    from rp.contribute.workspace import ContributorError

    try:
        return args.func(args)
    except ContributorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
