import hashlib
import io
import json
import zipfile
from pathlib import Path

from rp import strict_yaml
from rp.publication.citation import CitationData, bibtex, cff, csl_json
from rp.publication.packages import FIXED_TIME, build_package

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "records" / "valid" / "contribution" / "attempt-human-ai.yaml"
FILES = {"files/attempt.tex": b"\\section{Proof}\nLet $k=3$.\n", "files/refs.bib": b"@article{x}\n"}


def citation(date=None):
    return CitationData(
        alias="ERDOS-5-A1", revision_label="r1", title="Synthetic partial result for k = 3",
        url="https://we-solve.github.io/contributions/ERDOS-5-A1/r1/", authors=["Contributor A", "Contributor B"],
        institution=None, date=date, date_label="first posted (declared)", note="Not peer reviewed.",
        licence="CC-BY-4.0", contribution_id="con_x", revision_id="rev_x",
    )


def package(date=None):
    record = strict_yaml.load(FIXTURE.read_bytes())
    return build_package(alias="ERDOS-5-A1", revision_label="r1", record=record, files=FILES,
                         scientific_fingerprint="sha256:" + "1" * 64, citation=citation(date),
                         provenance={"legacy_path": "attacks/x.tex"}, notices="UnsolvedMath notice.")


def test_packages_are_byte_identical():
    a, b = package(), package()
    assert a.data == b.data and a.digest == b.digest and a.name == "ERDOS-5-A1-r1.zip"


def test_layout_checksums_and_manifest():
    pkg = package({"value": "2026-10-09", "precision": "day"})
    archive = zipfile.ZipFile(io.BytesIO(pkg.data))
    names = archive.namelist()
    assert names == sorted(names) and all(n.startswith("ERDOS-5-A1-r1/") for n in names)
    assert all(i.date_time == FIXED_TIME for i in archive.infolist())
    read = {n.split("/", 1)[1]: archive.read(n) for n in names}
    assert read["files/attempt.tex"] == FILES["files/attempt.tex"]
    for line in read["SHA256SUMS"].decode().splitlines():
        digest, path = line.split("  ", 1)
        assert hashlib.sha256(read[path]).hexdigest() == digest
    manifest = json.loads(read["MANIFEST.json"])
    assert manifest["scientific_fingerprint"] == "sha256:" + "1" * 64
    assert {f["path"] for f in manifest["files"]} == set(read) - {"MANIFEST.json", "SHA256SUMS"}
    assert "UnsolvedMath notice." in read["RIGHTS.md"].decode()
    assert "not mean the contribution is correct" in read["README.md"].decode()


def test_citations_never_carry_a_publication_date():
    no_date = citation()
    assert "year" not in bibtex(no_date) and "issued" not in csl_json(no_date)
    dated = citation({"value": "2026-10", "precision": "month"})
    assert csl_json(dated)["issued"] == {"date-parts": [[2026, 10]]}
    assert "year = {2026}" in bibtex(dated) and "month = {10}" in bibtex(dated)
    assert "date-released" not in cff(dated)
    assert csl_json(dated)["URL"].endswith("/r1/")
