from pathlib import Path

import pytest

from rp.catalog import default_catalog
from rp.validation.records import validate_file

ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "records"
VALID = sorted((ROOT / "valid").rglob("*.yaml"))
INVALID = sorted((ROOT / "invalid").rglob("*.yaml"))


def expected_code(path: Path) -> str:
    first = path.read_text(encoding="utf-8").splitlines()[0]
    assert first.startswith("# expect: "), f"{path} must start with '# expect: <code>'"
    return first.removeprefix("# expect: ").strip()


def test_fixture_sets_are_present():
    assert len(VALID) >= 14
    assert len(INVALID) >= 50


@pytest.mark.parametrize("path", VALID, ids=lambda p: str(p.relative_to(ROOT)))
def test_valid_fixture(path):
    errors = [i for i in validate_file(path, catalog=default_catalog()) if i.severity == "error"]
    assert errors == []


@pytest.mark.parametrize("path", INVALID, ids=lambda p: str(p.relative_to(ROOT)))
def test_invalid_fixture_fails_with_expected_code(path):
    issues = validate_file(path, catalog=default_catalog())
    codes = {i.code for i in issues if i.severity == "error"}
    assert expected_code(path) in codes, [str(i) for i in issues]
