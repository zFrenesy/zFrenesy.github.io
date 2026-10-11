"""Migrate attributed statement excerpts from already accepted legacy manuscripts.

This never fetches or relicenses erdosproblems.com. The legacy website displays
an explicitly labelled restatement from a manuscript; we preserve that text and
its source identity in an append-only statement revision.
"""
from __future__ import annotations

import re
import copy
import json
from dataclasses import dataclass
from pathlib import Path

from rp import strict_yaml
from rp.canonical import canonical_json, sha256_digest
from rp.identity.ids import new_id
from rp.ledger.events import make_event
from rp.site.model import load_model
from rp.timeutil import SystemClock
from rp.validation.records import validate_record

EXTENSION = 'org.we-solve.erdos-statement'
MIGRATION = 'erdos-statements-v1'
# Reviewed opening sections for seven manuscripts without a standard statement
# heading. These retain the source's qualifications and known-result context.
REVIEWED_HEADINGS = {
    '777': 'The three questions',
    '834': 'The two precise questions',
    '981': 'The eventual threshold',
    '1028': 'The necessary convention',
    '1042': 'The two conclusions, with their quantifiers',
    '1046': 'Separate the questions on the current page',
    '1187': 'The two answers',
}


@dataclass(frozen=True)
class Excerpt:
    text: str
    start: int
    end: int
    heading: str


_HEADING = re.compile(r"\\(section|subsection|subsubsection|paragraph|textbf|textit|emph)\*?\{")
_STATEMENT = re.compile(r"^(?:formal restatement|restatement|(?:(?:the\s+)?(?:exact|literal|original|precise|displayed)\s+)?statement|target|problem(?:$|\s*[(:]|\s+(?:and|statement|setup|formulation)\b))", re.I)
_OTHER = re.compile(r"^(?:(?:quick\s+)?(?:literature|context)|attack plan|objective|work|status|known extremal input|(?:adversarial\s+)?verification|final|sources|references|completion|(?:round[-\s–]*\d+\s+)?foundation|new insight)\b", re.I)


def statement_excerpt(source: str, *, reviewed_heading: str | None = None) -> Excerpt | None:
    """Require an explicit statement heading and a following section boundary.

    Return an exact source slice; nested braces and lower-level subsections stay
    intact. Never use an objective, proof, arbitrary opening paragraph or a
    whole manuscript as a substitute for a statement.
    """
    headings = []
    for match in _HEADING.finditer(source):
        # Ignore commented markers and inline emphasis within prose.
        prefix = source[source.rfind('\n', 0, match.start()) + 1:match.start()]
        if re.search(r"(?<!\\)%", prefix):
            continue
        depth, end = 1, match.end()
        while end < len(source) and depth:
            if source[end] == '\\':
                end += 2
                continue
            depth += (source[end] == '{') - (source[end] == '}')
            end += 1
        if depth:
            continue
        label = source[match.end():end - 1].strip()
        label = re.sub(r"^(?:OUTPUT\s+)?\d+[.)]\s*", '', label, flags=re.I)
        label = re.sub(r"\s+", ' ', label).strip(' .:[]')
        section = match[1] in {'section', 'subsection', 'subsubsection', 'paragraph'}
        label = re.sub(r"^Erd(?:\\H\{o\}|ő|o)s\s+problem\s+\d+$", 'Statement', label, flags=re.I)
        if not section and not (_STATEMENT.match(label) or _OTHER.match(label)):
            continue
        level = {'section': 1, 'subsection': 2, 'subsubsection': 3, 'paragraph': 4}.get(match[1], 1)
        headings.append((match.start(), end, label, level))
    # Earlier manuscripts use standalone uppercase or numbered prose headings.
    for match in re.finditer(r"(?m)^[ \t]*(#{1,6}\s+)?([^\n\\{}]{1,140})[ \t]*$", source):
        label = re.sub(r"^(?:OUTPUT\s+)?\d+[.)]\s*", '', match[2], flags=re.I).strip(' .:“”‘’\"\'*')
        marked = match[1] or label.upper() == label or re.match(r'\d+[.)]', match[2])
        if marked and (_STATEMENT.match(label) or _OTHER.match(label) or match[1]):
            headings.append((match.start(), match.end(), label, len(match[1].strip()) if match[1] else 1))
    headings.sort()
    candidates = []
    for i, (start, body, label, level) in enumerate(headings):
        if not (_STATEMENT.match(label) or label == reviewed_heading):
            continue
        following = next((h for h in headings[i + 1:] if h[3] <= level), None)
        if following is None:
            continue
        end = following[0]
        # Drop only layout commands belonging to the next paragraph heading.
        tail = re.search(r"(?:\s|\\(?:medskip|bigskip|smallskip|noindent))*$", source[body:end])
        if tail:
            end = body + tail.start()
        while body < end and source[body].isspace():
            body += 1
        text = source[body:end]
        if text and not re.search(r"\\(?:begin|end)\{document\}", text):
            candidates.append(Excerpt(text, body, end, label))
    return next((c for c in candidates if c.heading.lower().startswith('formal restatement')), candidates[0] if candidates else None)


def migrate(work: Path, *, source_commit: str, apply: bool = False, clock=None, id_source=None) -> dict:
    """Plan all changes before writing; reruns reuse recorded revisions unchanged.

    Run in disposable research/ledger checkouts and commit both results together.
    Existing events, descriptors, aliases and contribution bytes are untouched.
    """
    if not re.fullmatch(r'[0-9a-f]{40}', source_commit):
        raise ValueError('source_commit must be a full research commit SHA')
    work = Path(work).resolve()
    model = load_model(work)
    clock = clock or SystemClock()
    planned, missing, existing = [], [], []
    for problem in sorted(model.problems.values(), key=lambda p: p.alias):
        if problem.collection != 'erdos':
            continue
        if problem.record.get('extensions', {}).get(EXTENSION):
            existing.append(problem.alias)
            continue
        number = problem.alias.removeprefix('ERDOS-')
        candidates = []
        for contribution in problem.attempts:
            if contribution.cls == 'reused_writeup' or contribution.record['rights']['redistribution'] != 'permitted':
                continue
            source_path = contribution.legacy.get('source_path', '')
            reviewed = REVIEWED_HEADINGS.get(number) if source_path.endswith('/GPT_6_Astra_Ultra/' + number + '.tex') else None
            for name, raw in contribution.files.items():
                if not name.endswith('.tex'):
                    continue
                excerpt = statement_excerpt(raw.decode('utf-8'), reviewed_heading=reviewed)
                if excerpt:
                    rank = (not excerpt.heading.lower().startswith('formal restatement'),
                            '/gpt_pro_5.2/' not in source_path, source_path, name)
                    candidates.append((rank, contribution, name, raw, excerpt))
        if not candidates:
            missing.append(problem.alias)
            continue
        _, contribution, name, raw, excerpt = min(candidates, key=lambda c: c[0])
        body = (excerpt.text + '\n').encode('utf-8')
        predecessor = problem.record['statement_revision_id']
        sid = new_id('statement_revision', id_source)
        record = copy.deepcopy(problem.record)
        provenance = dict(migration=MIGRATION, contribution_id=contribution.id,
                          revision_id=contribution.record['revision_id'], alias=contribution.alias,
                          revision_label=contribution.revision_label, source_file=name,
                          source_commit=source_commit, source_digest=sha256_digest(raw),
                          start_character=excerpt.start, end_character=excerpt.end, heading=excerpt.heading)
        record.update(statement_revision_id=sid, expected_statement_predecessor=predecessor,
                      statement_artifact={'path': 'statement.tex'}, rights=copy.deepcopy(contribution.record['rights']))
        record['rights']['notes'] = ('Attributed statement excerpt from ' + contribution.alias + ' ' + contribution.revision_label
                                    + '. Original problem and current status: https://www.erdosproblems.com/' + number
                                    + '. The excerpt retains the source manuscript’s wording and qualifications.')
        record.setdefault('extensions', {})[EXTENSION] = provenance
        source_url = 'https://github.com/we-solve-staging/research/blob/' + source_commit + '/' + (contribution.folder.relative_to(work / 'research') / name).as_posix()
        event = make_event(event_type='statement_revised', actor={'kind': 'system'},
                           targets=[problem.id, sid], payload={'problem_id': problem.id, 'statement_revision_id': sid, 'predecessor': predecessor},
                           scope={'migration': MIGRATION, 'problem_id': problem.id, 'predecessor': predecessor},
                           policy_version='policy/1', clock=clock, id_source=id_source,
                           evidence=[{'kind': 'git_commit', 'ref': source_url}])
        descriptor = dict(schema_version=1, problem_id=problem.id, statement_revision_id=sid, predecessor=predecessor,
                          statement_artifact=dict(path='statement.tex', digest=sha256_digest(body), bytes=len(body)),
                          change_kind='editorial', change_note='Restore an attributed statement excerpt from the accepted legacy manuscript.',
                          source_commit=source_commit, recorded_at=event['recorded_at'])
        for kind, value in [('problem', record), ('statement_revision', descriptor)]:
            errors = [i for i in validate_record(kind, value, catalog=None) if i.severity == 'error']
            if errors:
                raise ValueError(str(errors))
        planned.append((problem, record, body, event, descriptor, provenance))
    report = dict(migration=MIGRATION, source_commit=source_commit, migrated=len(planned), existing=len(existing), missing=missing,
                  statements=[dict(problem_alias=p.alias, statement_revision_id=r['statement_revision_id'], **provenance)
                              for p, r, _, _, _, provenance in planned])
    if apply:
        if missing:
            raise ValueError('No statement excerpt for: ' + ', '.join(missing))
        ledger = work / 'ledger/events.jsonl'
        original = ledger.read_bytes()
        if original and not original.endswith(b'\n'):
            raise ValueError('ledger must end with a newline')
        for problem, record, body, _, descriptor, _ in planned:
            (problem.folder / 'statement.tex').write_bytes(body)
            (problem.folder / 'problem.yaml').write_text(strict_yaml.dump(record), encoding='utf-8')
            if problem.statement_name != 'statement.tex':
                (problem.folder / problem.statement_name).unlink()
            (work / 'ledger/statement-revisions' / (record['statement_revision_id'] + '.json')).write_bytes(canonical_json(descriptor) + b'\n')
        if planned:
            ledger.write_bytes(original + b''.join(canonical_json(row[3]) + b'\n' for row in planned))
            manifest = work / 'research/migration' / MIGRATION / 'statements.json'
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        # The ordinary site builder validates the complete new checkpoint before
        # publication; no source, descriptor or event bypasses that gate.
    return report


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    result = migrate(args.work, source_commit=args.source_commit, apply=args.apply)
    print(json.dumps({k: v for k, v in result.items() if k != 'statements'}, indent=2))
