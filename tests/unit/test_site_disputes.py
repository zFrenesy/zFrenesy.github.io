"""Disputed revisions and subproblems on the site, published through the test publisher."""

import json
import shutil

import pytest

from rp import strict_yaml
from rp.contribute.workspace import Research
from rp.identity.ids import SeededIdSource
from rp.migration.importer import LegacyImporter
from rp.migration.legacy_git import LegacyRepo
from rp.site.build import build_site
from rp.timeutil import FixedClock
from tests.fixtures.legacy_repo import SNAPSHOT, build_legacy_repo
from tests.fixtures.publish import publish_contribution, publish_subproblem

REVIEWER = {"login": "reviewer-a", "id": 1001, "name": "Reviewer A"}


def filled(folder, name, **changes):
    text = (folder / name).read_text()
    record = strict_yaml.load(text.encode())

    def walk(value):
        if isinstance(value, dict):
            return {k: walk(v) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v) for v in value]
        return value.replace("TODO: ", "").replace("TODO", "Filled") if isinstance(value, str) else value

    record = walk(record)
    for path, value in changes.items():
        target = record
        *parents, last = path.split(".")
        for key in parents:
            target = target[key]
        target[last] = value
    shutil.rmtree(folder)
    return record


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    legacy_path, commit = build_legacy_repo(tmp_path_factory.mktemp("legacy"))
    work = tmp_path_factory.mktemp("work")
    LegacyImporter(LegacyRepo(legacy_path, commit), work, id_source=SeededIdSource("disputes"),
                   clock=FixedClock("2026-10-11T00:00:00Z"), snapshot=SNAPSHOT).run()
    research = Research(work / "research")
    index = json.loads((work / "research" / "browse" / "aliases.json").read_text())
    target_alias = next(a for a, c in index["contributions"].items() if "-A" in a)
    home = index["contributions"][target_alias]["home"]

    folder = research.new_review(target_alias, REVIEWER)
    review = filled(folder, "contribution.yaml", **{"review.finding": "gap_found", "review.location": "Lemma 2"})
    review_alias = publish_contribution(work, review, {"files/review.md": b"# Review\n\nLemma 2 does not cover $n=1$.\n"}, home, "2026-10-12T00:00:00Z")

    folder = research.new_problem(home, REVIEWER)
    problem = filled(folder, "problem.yaml", title="The case n = 3")
    statement = b"# The case n = 3\n\nLet $n = 3$. Determine whether the statement of the parent problem holds in this case, with all definitions unchanged.\n"
    sub_alias = publish_subproblem(work, problem, statement, home, "2026-10-12T00:00:00Z")

    out = tmp_path_factory.mktemp("out")
    build_site(work, out, base_url="https://example.github.io/", cache_dir=tmp_path_factory.mktemp("cache"),
               packages_dir=tmp_path_factory.mktemp("packages"), search=False)
    return {"out": out, "target": target_alias, "home": home, "review": review_alias, "sub": sub_alias}


def page(site, route):
    return (site["out"] / route.strip("/") / "index.html").read_text()


def test_objection_marks_only_that_revision_disputed(site):
    html = page(site, f"/contributions/{site['target']}/")
    assert ">Disputed</h2>" in html and "1 gap found" in html and "Open objection" in html
    assert site["review"] in html and "not as votes" in html
    problem = page(site, f"/problems/{site['home']}/")
    assert 'badge-warning">Disputed</span>' in problem and "Review: gap found" in problem
    assert "Historical problem-level reviews" not in problem
    others = [a for a in (site["out"] / "contributions").iterdir() if a.name not in (site["target"], site["review"])]
    assert all("badge-warning" not in (a / "index.html").read_text() for a in others if (a / "index.html").exists())


def test_subproblem_links_both_ways(site):
    assert site["sub"] == site["home"] + ".1"
    child = page(site, f"/problems/{site['sub']}/")
    assert "Subproblem of" in child and f">{site['home']}</a> (special case)" in child
    assert "Not established as open or novel" in child and "does not change its parent problem" in child
    assert "mathjax-init.js" in child and "Let $n = 3$" in child  # Markdown maths loads MathJax
    parent = page(site, f"/problems/{site['home']}/")
    assert f">{site['sub']}</a>" in parent
