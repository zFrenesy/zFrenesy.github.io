import subprocess
from pathlib import Path

import pytest

from rp.identity.ids import SeededIdSource
from rp.migration.erdos_statements import EXTENSION, migrate, statement_excerpt
from rp.migration.importer import LegacyImporter
from rp.migration.legacy_git import LegacyRepo
from rp.site.model import load_model
from rp.timeutil import FixedClock
from tests.fixtures.legacy_repo import SNAPSHOT, build_legacy_repo


@pytest.mark.parametrize('heading,next_heading', [
    (r'\section*{Formal restatement}', r'\section{Work}'),
    (r'\noindent\textbf{1) FORMAL RESTATEMENT.}', r'\noindent\textbf{2) WORK.}'),
    ('1) “FORMAL RESTATEMENT”', '2) “WORK”'),
    ('## 1) FORMAL RESTATEMENT', '## 2) WORK'),
    (r'\subsection{1) [Formal restatement]}', r'\subsection{2) [Work]}'),
    (r'\textbf{Erd\H{o}s problem 527.}', r'\textbf{Status and attribution.}'),
])
def test_statement_excerpt_keeps_exact_source_and_stops_before_proof(heading, next_heading):
    text = heading + '\n\nQuestion: is $n^{2} > n$?\n\n' + next_heading + '\nProof content.'
    excerpt = statement_excerpt(text)
    assert excerpt and excerpt.text == 'Question: is $n^{2} > n$?'
    assert text[excerpt.start:excerpt.end] == excerpt.text


def test_nested_subsections_and_balanced_braces_are_preserved():
    source = r'\section{Formal restatement}' + '\n' + r'\subsection{Definitions of $\{A\}$}' + '\nLet $A$ be finite.\n' + r'\section{Work}'
    excerpt = statement_excerpt(source)
    assert excerpt and r'\subsection{Definitions of $\{A\}$}' in excerpt.text


@pytest.mark.parametrize('source', [
    r'\section{Work} This is not the statement.',
    r'\section{Formal restatement} An unbounded excerpt.',
    '% ' + r'\section{Formal restatement}' + '\nHidden.\n' + r'\section{Work}',
    r'\section{Objective} Prove a special case.' + '\n' + r'\section{Work}',
])
def test_extractor_does_not_guess_a_statement(source):
    assert statement_excerpt(source) is None


def test_migration_preserves_history_and_attempts_and_is_idempotent(tmp_path):
    legacy_path, _ = build_legacy_repo(tmp_path)
    for number in (1, 3, 5):
        path = legacy_path / f'attacks/open_problems/erdos/gpt_pro_5.2/{number}.tex'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(r'\section{Formal restatement}' + '\nIs $n>1$?\n' + r'\section{Work}' + '\nAn attempt.\n')
    subprocess.run(['git', '-C', str(legacy_path), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(legacy_path), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.org', 'commit', '-m', 'Update fixtures'], check=True, capture_output=True)
    commit = subprocess.check_output(['git', '-C', str(legacy_path), 'rev-parse', 'HEAD'], text=True).strip()
    work = tmp_path / 'work'
    LegacyImporter(LegacyRepo(legacy_path, commit), work, id_source=SeededIdSource('statements'),
                   clock=FixedClock('2026-10-11T00:00:00Z'), snapshot=SNAPSHOT).run()
    before = load_model(work)
    ledger = (work / 'ledger/events.jsonl').read_bytes()
    old_descriptors = {p.name:p.read_bytes() for p in (work / 'ledger/statement-revisions').iterdir()}
    result = migrate(work, source_commit=commit, apply=True, clock=FixedClock('2026-10-11T12:00:00Z'), id_source=SeededIdSource('new-statements'))
    assert result['migrated'] == 3 and not result['missing']
    after = load_model(work)
    assert (work / 'ledger/events.jsonl').read_bytes().startswith(ledger)
    for name, data in old_descriptors.items():
        assert (work / 'ledger/statement-revisions' / name).read_bytes() == data
    for cid, original in before.contributions.items():
        assert after.contributions[cid].record == original.record
        assert after.contributions[cid].files == original.files
    for pid, problem in before.problems.items():
        updated = after.problems[pid]
        assert updated.alias == problem.alias
        if problem.collection == 'erdos':
            assert updated.statement == b'Is $n>1$?\n'
            assert updated.record['expected_statement_predecessor'] == problem.record['statement_revision_id']
            assert updated.record['rights']['redistribution'] == 'permitted'
            assert updated.record['extensions'][EXTENSION]['source_commit'] == commit
    frozen = (work / 'ledger/events.jsonl').read_bytes()
    repeated = migrate(work, source_commit=commit, apply=True)
    assert repeated['migrated'] == 0 and repeated['existing'] == 3
    assert (work / 'ledger/events.jsonl').read_bytes() == frozen
