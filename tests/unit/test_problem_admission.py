from rp import strict_yaml
from rp.identity.ids import new_id
from rp.identity.paths import problem_dir
from rp.validation.problems import admission_issues, isbn_valid, shingles, similar_statements

STATEMENT = "Let $G$ be a finite group of odd order. Prove that every element of $G$ is a product of two squares in $G$."


def problem(kind="proposed", **extra):
    record = {"kind": kind, "disciplines": [{"discipline": "mathematics", "role": "primary"}],
              "classifications": [{"scheme": "msc2020", "code": "20D10"}]}
    record.update(extra)
    return record


def errors(issues):
    return [m for s, m in issues if s == "error"]


def test_isbn_check_digits():
    assert isbn_valid("9780306406157") and isbn_valid("0306406152") and isbn_valid("080442957X")
    assert not isbn_valid("9780306406158") and not isbn_valid("0306406153")


def test_statement_classification_and_kind():
    assert errors(admission_issues(problem(), STATEMENT)) == []
    assert any("too short" in m for m in errors(admission_issues(problem(), "# Title\n\nShow $n=3$.")))
    assert any("Subject Classification" in m for m in errors(admission_issues(problem(classifications=[]), STATEMENT)))
    assert errors(admission_issues(problem("derived", classifications=[]), STATEMENT)) == []
    assert errors(admission_issues(problem("catalogued"), STATEMENT)) == ["contributors may add literature, proposed or derived problems only"]
    notes = [m for s, m in admission_issues(problem(), STATEMENT) if s == "warning"]
    assert any("Not established as open or novel" in m for m in notes)


def test_literature_citation():
    good = problem("literature", citation={"reference": {"kind": "isbn", "value": "9780306406157"}, "locator": "Problem 4.2"})
    issues = admission_issues(good, STATEMENT)
    assert errors(issues) == [] and any("not independently checked" in m for _, m in issues)
    bad = problem("literature", citation={"reference": {"kind": "isbn", "value": "9780306406158"}, "locator": "p. 3"})
    assert errors(admission_issues(bad, STATEMENT)) == ["the ISBN check digit is wrong"]


def write_problem(root, title, statement, discipline="mathematics"):
    pid = new_id("problem")
    folder = root / problem_dir(pid)
    folder.mkdir(parents=True)
    (folder / "problem.yaml").write_text(strict_yaml.dump({
        "problem_id": pid, "title": title, "statement_artifact": {"path": "statement.md"},
        "disciplines": [{"discipline": discipline, "role": "primary"}]}))
    (folder / "statement.md").write_text(statement)
    return pid


def test_derived_parent_must_exist(tmp_path):
    parent = write_problem(tmp_path, "Parent", STATEMENT)
    ok = problem("derived", derivation={"parent_problem_id": parent, "nature": "special_case", "parent_status_unchanged": True})
    assert errors(admission_issues(ok, STATEMENT, root=tmp_path)) == []
    missing = problem("derived", derivation={"parent_problem_id": new_id("problem"), "nature": "step", "parent_status_unchanged": True})
    assert any("does not exist" in m for m in errors(admission_issues(missing, STATEMENT, root=tmp_path)))


def test_similar_statements_rank_within_the_discipline(tmp_path):
    same = write_problem(tmp_path, "Squares in odd groups", "% comment\n" + STATEMENT.replace("$G$", "\\(G\\)"))
    write_problem(tmp_path, "Unrelated", "Determine all primes $p$ such that $2^p - 1$ is prime and $p$ is a Sophie Germain prime.")
    write_problem(tmp_path, "Other discipline", STATEMENT, discipline="economics")
    found = similar_statements(STATEMENT, "mathematics", tmp_path)
    assert [f.problem_id for f in found] == [same] and found[0].score > 0.8
    assert similar_statements(STATEMENT, "mathematics", tmp_path, exclude=same) == []
    assert shingles("") == frozenset()
