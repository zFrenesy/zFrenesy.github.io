import shutil
from pathlib import Path

import pytest

from rp import PACKAGE_ROOT, strict_yaml
from rp.catalog import Catalog, CatalogError, default_catalog
from rp.identity.aliases import plan_counter_alias
from rp.identity.ids import SeededIdSource, new_id
from rp.validation.records import validate_record

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "records" / "valid"


@pytest.fixture
def policies(tmp_path):
    target = tmp_path / "policies"
    shutil.copytree(Path(str(PACKAGE_ROOT / "policies")), target)
    return target


def test_default_catalog():
    catalog = default_catalog()
    assert catalog.platform["organisation"] == "we-solve"
    assert catalog.platform["site"]["base_url"] == "https://we-solve.github.io/"
    assert catalog.open_disciplines() == ["computer-science", "economics", "mathematics"]
    assert catalog.disciplines["biology"]["status"] == "planned"
    assert catalog.alias_policy.counter_scheme("CS").allocation_authority == "we-solve"
    assert not catalog.alias_policy.counter_scheme("BIO").enabled


class EmptyRegistry:
    def alias_record(self, alias):
        return None

    def counter_value(self, key):
        return 0

    def live_alias_of(self, entity_id):
        return None


def test_dummy_discipline_end_to_end(policies):
    """Adding a discipline needs only a config file, a vocabulary and tests (§14)."""
    (policies / "disciplines" / "dummy.yaml").write_text(
        strict_yaml.dump(
            {
                "schema_version": 1,
                "slug": "dummy",
                "name": "Dummy Studies",
                "alias_prefix": "DUMMY",
                "status": "active",
                "usable_as_secondary": True,
                "classification": {"scheme": "dummy-codes", "name": "Dummy codes", "code_pattern": "^D[0-9]{2}$", "vocabulary": "dummy-codes"},
                "profiles": ["mathematical_argument", "review"],
                "accepted_formats": {"stored": ["md", "pdf"], "linked": ["code"]},
                "rubric_addendum": "Dummy rubric addendum.",
                "disclaimer": "Dummy disclaimer.",
                "stewards": [{"login": "dummy-steward"}],
            }
        )
    )
    (policies / "classifications" / "dummy-codes.yaml").write_text(
        strict_yaml.dump(
            {
                "schema_version": 1,
                "scheme": "dummy-codes",
                "name": "Dummy codes",
                "source_note": "Test vocabulary.",
                "top_level_length": 2,
                "top_level_codes": ["D1", "D2"],
            }
        )
    )
    catalog = Catalog.load(policies)
    assert "dummy" in catalog.open_disciplines()

    entity = new_id("problem", SeededIdSource("dummy"))
    reservation = plan_counter_alias(catalog.alias_policy, EmptyRegistry(), prefix="DUMMY", entity_id=entity)
    assert reservation.alias == "DUMMY-1"

    problem = strict_yaml.load((FIXTURES / "problem" / "proposed.yaml").read_bytes())
    problem["disciplines"] = [{"discipline": "dummy", "role": "primary"}]
    problem["classifications"] = [{"scheme": "dummy-codes", "code": "D17"}]
    assert validate_record("problem", problem, catalog=catalog) == []
    problem["classifications"] = [{"scheme": "dummy-codes", "code": "D37"}]
    assert [i.code for i in validate_record("problem", problem, catalog=catalog)] == ["problem.classification_code"]

    attempt = strict_yaml.load((FIXTURES / "contribution" / "attempt-ai-only.yaml").read_bytes())
    assert validate_record("contribution", attempt, catalog=catalog) == []

    # The default catalog knows nothing about it: no core code holds discipline lists.
    problem["classifications"] = [{"scheme": "dummy-codes", "code": "D17"}]
    codes = {i.code for i in validate_record("problem", problem, catalog=default_catalog())}
    assert "problem.unknown_discipline" in codes


def edit(path: Path, **changes):
    data = strict_yaml.load(path.read_bytes())
    data.update(changes)
    path.write_text(strict_yaml.dump(data))


@pytest.mark.parametrize(
    "file, changes, message",
    [
        ("disciplines/economics.yaml", {"alias_prefix": "MATH"}, "already used"),
        ("disciplines/economics.yaml", {"profiles": ["no_such_profile"]}, "unknown profile"),
        ("disciplines/computer-science.yaml", {"status": "planned", "hold_reason": "x"}, "site section"),
        ("disciplines/economics.yaml", {"slug": "econ"}, "file name must be"),
        ("disciplines/economics.yaml", {"status": "launched"}, "schema.enum"),
        ("platform.yaml", {"analytics": "google"}, "schema.const"),
    ],
)
def test_broken_catalogs_fail_loudly(policies, file, changes, message):
    edit(policies / file, **changes)
    with pytest.raises(CatalogError, match=message):
        Catalog.load(policies)


def test_external_scheme_cannot_overlap_counter_scheme(policies):
    path = policies / "alias-namespaces.yaml"
    data = strict_yaml.load(path.read_bytes())
    data["schemes"][1]["local_pattern"] = "[1-9][0-9]*"
    path.write_text(strict_yaml.dump(data))
    with pytest.raises(CatalogError, match="could mint the same aliases"):
        Catalog.load(policies)


def test_unsafe_yaml_in_policy_is_rejected(policies):
    path = policies / "disciplines" / "economics.yaml"
    path.write_text(path.read_text().replace("usable_as_secondary: true", "usable_as_secondary: yes"))
    with pytest.raises(CatalogError, match="yaml.ambiguous_scalar"):
        Catalog.load(policies)
