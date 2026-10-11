"""Static-site integration checks using synthetic history, never the live legacy tree."""

import hashlib
import html
import json
import shutil
import zipfile
from html.parser import HTMLParser
from pathlib import Path

import pytest

from rp import strict_yaml
from rp.identity.ids import SeededIdSource
from rp.migration.importer import LegacyImporter
from rp.migration.legacy_git import LegacyRepo
from rp.site.build import Builder, build_site, plain_document
from rp.site.model import load_model
from rp.timeutil import FixedClock
from tests.fixtures.legacy_repo import SNAPSHOT, build_legacy_repo


BASE_URL = "https://example.github.io/research/"


def tree_digest(root: Path, *, exclude_search: bool = False) -> str:
    digest = hashlib.sha256()
    for path in sorted(path for path in root.rglob("*") if path.is_file()):
        if exclude_search and path.relative_to(root).parts[0] == "pagefind":
            continue
        digest.update(path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()


@pytest.fixture(scope="module")
def imported(tmp_path_factory):
    legacy_path, commit = build_legacy_repo(tmp_path_factory.mktemp("site-legacy"))
    legacy = LegacyRepo(legacy_path, commit)
    work = tmp_path_factory.mktemp("site-work")
    LegacyImporter(legacy, work, id_source=SeededIdSource("site-build"),
                   clock=FixedClock("2026-10-11T00:00:00Z"), snapshot=SNAPSHOT).run()
    return work, legacy_path


@pytest.fixture(scope="module")
def built(imported, tmp_path_factory):
    work, legacy_path = imported
    out = tmp_path_factory.mktemp("site-output")
    cache = tmp_path_factory.mktemp("site-render-cache")
    packages = tmp_path_factory.mktemp("site-packages")
    before = tree_digest(work), tree_digest(legacy_path)
    report = build_site(work, out, base_url=BASE_URL, cache_dir=cache, packages_dir=packages, search=True)
    assert (tree_digest(work), tree_digest(legacy_path)) == before
    return {"work": work, "out": out, "cache": cache, "packages": packages,
            "report": report, "model": load_model(work)}


def read_route(built, route: str) -> str:
    return (built["out"] / route.lstrip("/") / "index.html").read_text()


def test_site_build_has_all_records_and_local_search(built):
    report, out = built["report"], built["out"]
    assert report["problems"] == 8
    assert report["contributions"] == 13
    assert report["checks"]["errors"] == []
    assert report["checks"]["max_initial_payload_bytes"] <= 200 * 1024
    assert report["checks"]["total_bytes"] < 800 * 1024 * 1024
    assert report["pagefind"] == "1.5.2"
    assert (out / "pagefind/pagefind.js").is_file()
    assert any((out / "pagefind").rglob("*.pf_fragment"))
    assert (out / ".nojekyll").is_file()
    for route in ("/mathematics/", "/economics/", "/computer-science/", "/people/", "/models/", "/search/"):
        assert (out / route.lstrip("/") / "index.html").is_file()
    homepage = read_route(built, "/")
    assert '<meta name="robots" content="noindex, nofollow">' in homepage
    assert 'href="/research/assets/site.css"' in homepage
    assert "mathjax-config.js" not in homepage


def test_every_problem_and_contribution_has_canonical_and_alias_routes(built):
    for problem in built["model"].problems.values():
        assert html.escape(problem.record["title"]) in read_route(built, problem.url)
        assert "/research" + problem.url in read_route(built, "/p/" + problem.hex + "/")
    for contribution in built["model"].contributions.values():
        assert contribution.alias in read_route(built, contribution.url)
        assert contribution.alias in read_route(built, contribution.revision_url)
        assert "/research" + contribution.url in read_route(built, "/c/" + contribution.hex + "/")


def test_published_source_bytes_and_rights_are_preserved(built):
    out = built["out"]
    for problem in built["model"].problems.values():
        page = read_route(built, problem.url)
        source = out / problem.url.lstrip("/") / "source" / problem.statement_name
        if problem.record["rights"]["redistribution"] == "permitted":
            assert source.read_bytes() == problem.statement
        else:
            assert not source.exists()
            assert "not reproduced here" in page
            for external in problem.record["external_ids"]:
                if external.get("url"):
                    assert html.escape(external["url"], quote=True) in page
        assert problem.record["rights"]["licence"] in page
    for contribution in built["model"].contributions.values():
        page = read_route(built, contribution.revision_url)
        folder = out / contribution.revision_url.lstrip("/")
        for name, original in contribution.files.items():
            if contribution.record["rights"]["redistribution"] == "permitted":
                assert (folder / "source" / name).read_bytes() == original
            else:
                assert not (folder / "source" / name).exists()
        published = strict_yaml.load((folder / "contribution.yaml").read_bytes())
        assert published == contribution.record
        assert contribution.record["rights"]["licence"] in page
        assert "Rights:" in page
    top = built["model"].by_alias()["TOP-10"]
    assert top.record["rights"]["licence"] == "CC-BY-SA-4.0"
    assert "CC-BY-SA-4.0" in read_route(built, top.url)


def test_citations_always_select_immutable_revision_and_original_date(built):
    for contribution in built["model"].contributions.values():
        folder = built["out"] / contribution.revision_url.lstrip("/")
        citation = json.loads((folder / "citation.json").read_text())
        expected = BASE_URL.rstrip("/") + contribution.revision_url
        assert citation["URL"] == expected
        assert expected in (folder / "citation.bib").read_text()
        assert expected in read_route(built, contribution.url)
        assert "date-released" not in (folder / "CITATION.cff").read_text()
        if "issued" in citation:
            assert citation["issued"]["date-parts"] != [[2026, 10, 11]]


def test_revision_packages_are_external_to_pages_with_exact_sources(built):
    assert len(built["report"]["packages"]) == 13
    assert not list(built["out"].rglob("*.zip"))
    assert not list(built["out"].rglob("*.pdf"))
    for contribution in built["model"].contributions.values():
        name = contribution.alias + "-" + contribution.revision_label
        with zipfile.ZipFile(built["packages"] / (name + ".zip")) as package:
            for path, source in contribution.files.items():
                assert package.read(name + "/" + path) == source
            manifest = json.loads(package.read(name + "/MANIFEST.json"))
            assert manifest["revision_id"] == contribution.record["revision_id"]
            assert manifest["licence"] == contribution.record["rights"]["licence"]
            rights = package.read(name + "/RIGHTS.md").decode()
            assert contribution.record["rights"]["licence"] in rights
            assert "Third-party" in rights
            assert "does not mean the contribution is correct" in package.read(name + "/README.md").decode()


def test_source_status_and_author_claim_remain_independent(built):
    model = built["model"]
    top = model.by_alias()["TOP-10"]
    solution = next(c for c in top.attempts if c.claim_type == "full_solution")
    assert top.source_status["normalised_status"] == "open"
    assert solution.claim_label == "Full solution claimed"
    page = read_route(built, solution.revision_url)
    assert "Unverified claim of a full solution" in page
    assert "Claims here do not change the source status" in page
    assert "open" in page
    erdos = model.by_alias()["ERDOS-5"]
    undeclared = next(c for c in erdos.attempts if c.legacy["source_path"].endswith("/5.tex"))
    assert undeclared.claim_type is None
    assert "No claim recorded" in read_route(built, undeclared.revision_url)
    assert erdos.source_status["normalised_status"] == "open"
    assert model.by_alias()["ERDOS-1"].source_status["normalised_status"] == "proved"


def test_reviews_reused_text_and_human_attribution_remain_distinct(built):
    contributions = list(built["model"].contributions.values())
    reused = next(c for c in contributions if c.cls == "reused_writeup")
    assert reused.model_names == ["gpt pro 5.2"]
    assert "gpt pro 5.2" in read_route(built, reused.revision_url)
    human = next(c for c in contributions if c.cls == "human_contribution")
    page = read_route(built, human.revision_url)
    assert "Human + AI" in page
    assert "listed by submitter" in page
    assert "Submitted by" in page
    assert len([c for c in contributions if c.is_review]) == 2
    for review in (c for c in contributions if c.is_review):
        assert review in review.problem.reviews
        assert review not in review.problem.attempts
        assert "A review records a finding" in read_route(built, review.revision_url)


def test_legacy_map_is_build_data_and_uses_project_prefix(built):
    mapping = json.loads((built["out"] / "api/v1/legacy-map.json").read_text())
    assert mapping["problem.html?id=5"] == "/problems/ERDOS-5/"
    redirects = (built["out"] / "api/v1/legacy-redirects.txt").read_text()
    assert "problem.html?id=5 /research/problems/ERDOS-5/" in redirects


def test_repeated_first_party_build_and_packages_are_byte_identical(built, tmp_path):
    report = build_site(built["work"], tmp_path / "site", base_url=BASE_URL,
                        cache_dir=built["cache"], packages_dir=tmp_path / "packages", search=True)
    # Pagefind 1.5.2's filter ordering changes index hashes/sizes between runs;
    # our generated pages, source files, citations and packages stay identical.
    assert {k: v for k, v in report.items() if k != "checks"} == {
        k: v for k, v in built["report"].items() if k != "checks"
    }
    assert report["checks"]["errors"] == []
    assert report["checks"]["html_pages"] == built["report"]["checks"]["html_pages"]
    assert tree_digest(tmp_path / "site", exclude_search=True) == tree_digest(built["out"], exclude_search=True)
    assert tree_digest(tmp_path / "packages") == tree_digest(built["packages"])


@pytest.mark.parametrize("statement_path", ["../../outside.tex", "/etc/passwd"])
def test_model_rejects_statement_path_traversal(imported, tmp_path, statement_path):
    work = tmp_path / "work"
    shutil.copytree(imported[0], work)
    record_path = next((work / "research").rglob("problem.yaml"))
    record = strict_yaml.load(record_path.read_bytes())
    record["statement_artifact"]["path"] = statement_path
    record_path.write_text(strict_yaml.dump(record))
    with pytest.raises(ValueError, match="escapes its document|statement_artifact/path"):
        load_model(work)


def test_model_rejects_symlink_source(imported, tmp_path):
    work = tmp_path / "work"
    shutil.copytree(imported[0], work)
    record_path = next((work / "research").rglob("problem.yaml"))
    record = strict_yaml.load(record_path.read_bytes())
    statement = record_path.parent / record["statement_artifact"]["path"]
    target = record_path.parent / "other.txt"
    target.write_bytes(statement.read_bytes())
    statement.unlink()
    statement.symlink_to(target)
    with pytest.raises(ValueError, match="symlink artifact"):
        load_model(work)


def test_builder_rejects_writing_over_inputs_or_packages_into_pages(imported, tmp_path):
    work, _ = imported
    for out in (work, work / "research" / "site", work / "ledger" / "site"):
        with pytest.raises(ValueError, match="separate from research inputs"):
            Builder(work, out, base_url=BASE_URL, search=False)
    with pytest.raises(ValueError, match="outside Pages and research"):
        Builder(work, tmp_path / "site", base_url=BASE_URL, packages_dir=tmp_path / "site/packages", search=False)
    builder = Builder(work, tmp_path / "site", base_url=BASE_URL, search=False)
    with pytest.raises(ValueError, match="output path escapes site"):
        builder.write("../outside.txt", b"outside")
    assert not (tmp_path / "outside.txt").exists()


@pytest.mark.parametrize("base_url", ["http://example.com/", "https://example.com/?token=x", "https://example.com/#page"])
def test_builder_requires_clean_https_base_url(imported, tmp_path, base_url):
    with pytest.raises(ValueError, match="HTTPS site URL"):
        Builder(imported[0], tmp_path / "site", base_url=base_url, search=False)


def test_restricted_markdown_escapes_author_html():
    output = plain_document('# Heading\n\n<script>alert(1)</script>\n\n[Source](https://example.com/)')
    assert "<script>" not in output
    assert "&lt;script&gt;" in output
    assert 'href="https://example.com/"' in output
    assert 'rel="noopener noreferrer nofollow ugc"' in output


class ReferenceLinks(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.links = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "a" and "data-tex-reference" in attributes:
            self.links.append(attributes)


@pytest.mark.parametrize("case, expected", [
    ("known", "external"),
    ("possible_revision", "unresolved_reference"),
    ("wrong_revision", "unresolved_reference"),
    ("ambiguous_sources", "ambiguous_reference"),
    ("local_override", "local"),
])
def test_builder_resolves_only_explicit_exact_reference_sources(imported, tmp_path, case, expected):
    builder = Builder(imported[0], tmp_path / "site", base_url=BASE_URL, search=False)
    manuscripts = [c for c in builder.model.contributions.values()
                   if any(a.get("path", "").endswith(".tex") for a in c.record["artifacts"])]
    earlier, second, current = manuscripts[:3]
    theorem = r"\begin{theorem}\label{thm:shared}A useful fact.\end{theorem}"
    for contribution in (earlier, second, current):
        contribution.record["extensions"] = {}
        contribution.record["lineage"] = []
        path = next(a["path"] for a in contribution.record["artifacts"] if a.get("path", "").endswith(".tex"))
        content = theorem if contribution is not current else r"Use Theorem~\ref{thm:shared}."
        if contribution is current and case == "local_override":
            content = theorem + "\n\n" + content
        contribution.files[path] = content.encode()
    relation = {"relation": "derivative_of", "contribution_id": earlier.id,
                "revision_id": earlier.record["revision_id"], "lineage_status": "known"}
    if case == "possible_revision":
        relation.update(relation="possible_revision_of", lineage_status="unknown")
    elif case == "wrong_revision":
        relation["revision_id"] = second.record["revision_id"]
    current.record["lineage"] = [relation]
    if case == "ambiguous_sources":
        current.record["lineage"].append({"relation": "reuses", "contribution_id": second.id,
                                         "revision_id": second.record["revision_id"], "lineage_status": "known"})
    # The target deliberately follows the referencing document in iteration order.
    builder.model.problems = {}
    builder.model.contributions = {c.id: c for c in (current, second, earlier)}
    builder.render_documents()
    links = ReferenceLinks(current.rendered.html).links
    assert len(links) == 1
    if expected == "external":
        assert links[0]["href"].startswith("/research" + earlier.revision_url + "#tex-label-")
        assert earlier.alias in links[0]["title"] and "r1" in links[0]["title"]
        assert not builder.diagnostics
    elif expected == "local":
        assert links[0]["href"].startswith("#tex-label-")
        assert "this document" in links[0]["title"]
        assert not builder.diagnostics
    else:
        assert "href" not in links[0]
        assert "tex-reference-unresolved" in links[0]["class"]
        assert expected in {diagnostic["code"] for diagnostic in builder.diagnostics}
    assert any(target["document_id"] == earlier.alias and target["revision"] == "r1"
               for target in builder.refs.values())


def test_older_revision_placeholder_never_substitutes_current_sources(imported, tmp_path):
    builder = Builder(imported[0], tmp_path / "site", base_url=BASE_URL, search=False)
    manuscripts = [c for c in builder.model.contributions.values()
                   if any(a.get("path", "").endswith(".tex") for a in c.record["artifacts"])]
    contribution, other = manuscripts[:2]
    # Retain its real r1 acceptance event, which stores the label as sequence_label.
    # Model a newer source record whose r1 snapshot is absent from this build.
    contribution.record["revision_id"] = other.record["revision_id"]
    contribution.revision_label = "r2"
    contribution.record["lineage"] = []
    builder.model.contributions = {contribution.id: contribution}
    builder.render_documents()
    builder.contribution_pages()
    older = builder.out / contribution.url.lstrip("/") / "r1"
    placeholder = (older / "index.html").read_text()
    assert "source snapshot is not included" in placeholder
    assert "no manuscript or package is substituted" in placeholder
    assert not (older / "source").exists()
    assert not (older / "citation.json").exists()
    current = builder.out / contribution.revision_url.lstrip("/")
    assert (current / "source").is_dir()
    assert json.loads((current / "citation.json").read_text())["URL"].endswith(contribution.revision_url)


@pytest.mark.parametrize("redistribution", ["link_only", "unclear"])
def test_restricted_sources_are_never_rendered_downloaded_or_packaged(imported, tmp_path, redistribution):
    builder = Builder(imported[0], tmp_path / "site", base_url=BASE_URL,
                      packages_dir=tmp_path / "packages", search=False)
    problem = builder.model.by_alias()["TOP-10"]
    contribution = problem.attempts[0]
    # These publication-policy inputs are changed only after strict model loading;
    # persisted record fingerprints and accepted source snapshots stay untouched.
    problem.record["rights"]["redistribution"] = redistribution
    contribution.record["rights"]["redistribution"] = redistribution
    problem.statement = b"RESTRICTED-STATEMENT-SENTINEL"
    contribution.files = {name: b"RESTRICTED-MANUSCRIPT-SENTINEL" for name in contribution.files}
    problem.contributions = [contribution]
    builder.model.problems = {problem.id: problem}
    builder.model.contributions = {contribution.id: contribution}
    builder.render_documents()
    builder.problem_pages()
    builder.contribution_pages()
    for path in builder.out.rglob("*"):
        if path.is_file():
            assert b"RESTRICTED-STATEMENT-SENTINEL" not in path.read_bytes()
            assert b"RESTRICTED-MANUSCRIPT-SENTINEL" not in path.read_bytes()
    problem_page = builder.out / problem.url.lstrip("/")
    contribution_page = builder.out / contribution.revision_url.lstrip("/")
    assert not (problem_page / "source").exists()
    assert not (contribution_page / "source").exists()
    assert "not reproduced here" in (problem_page / "index.html").read_text()
    assert "metadata" in (contribution_page / "index.html").read_text()
    assert (contribution_page / "contribution.yaml").exists()
    assert not builder.packages and not (tmp_path / "packages").exists()
