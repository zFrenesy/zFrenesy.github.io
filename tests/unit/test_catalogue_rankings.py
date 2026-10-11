"""Catalogue order is mutable; permanent aliases and scientific records are not."""

from types import SimpleNamespace

import pytest

from rp.site.rankings import (
    catalogue_rank, catalogue_sort_key, load_economics_jel_labels, load_economics_rankings,
)


def test_checked_in_economics_ranks_have_names_at_each_jel_level():
    ranks = load_economics_rankings()
    labels = load_economics_jel_labels()
    # Future rerankings need no test edits: exercise consistency, not a frozen order.
    assert ranks
    assert all(code[:level] in labels for alias in ranks
               for code in [alias.split("-")[1]] for level in (1, 2, 3))


def test_ranking_change_orders_by_config_without_renaming_or_inventing_a_rank(tmp_path):
    path = tmp_path / "ranks.csv"
    path.write_text("Problem ID,New rank\nC73-1,2\nC72-2,1\n", encoding="utf-8")
    ranks = load_economics_rankings(path)
    one = SimpleNamespace(alias="ECON-C73-1", collection="economics")
    two = SimpleNamespace(alias="ECON-C72-2", collection="economics")
    unranked = SimpleNamespace(alias="ECON-C73-1000", collection="economics")
    other = SimpleNamespace(alias="ECON-C72-2", collection="top")
    assert [p.alias for p in sorted([unranked, one, two], key=lambda p: catalogue_sort_key(p, ranks))] == [
        "ECON-C72-2", "ECON-C73-1", "ECON-C73-1000",
    ]
    assert catalogue_rank(one, ranks) == 2
    assert catalogue_rank(unranked, ranks) is None
    assert catalogue_rank(other, ranks) is None
    assert one.alias == "ECON-C73-1"


@pytest.mark.parametrize("csv", [
    "Problem ID,New rank\nC73-1,1\nC72-2,1\n",  # tied ranks
    "Problem ID,New rank\nC73-1,1\nC72-2,3\n",  # missing rank
    "Problem ID,New rank\nC73-1,1\nC73-1,2\n",  # duplicate identity
    "Problem ID,New rank\nOP-0001,1\n",  # reused source ID is not identity
    "Problem ID,New rank\nC73-1,1.0\n",
    "Problem ID,New rank\nC73-1,0\n",
    "Problem ID,New rank,JEL code\nC73-1,1,D63\n",
    "Problem ID,rank\nC73-1,1\n",
    "Problem ID,New rank,New rank\nC73-1,1,1\n",
    "Problem ID,New rank\nC73-1,1,extra\n",
    "Problem ID,New rank\n",
])
def test_invalid_rank_orders_fail_before_building(tmp_path, csv):
    path = tmp_path / "ranks.csv"
    path.write_text(csv, encoding="utf-8")
    with pytest.raises(ValueError):
        load_economics_rankings(path)


@pytest.mark.parametrize("data", [
    '{"schema_version":2,"labels":{"C73":"Games"}}',
    '{"schema_version":1,"labels":{"C733":"Games"}}',
    '{"schema_version":1,"labels":{"C73":""}}',
    '{"schema_version":1,"labels":{"C73":null}}',
    '{"schema_version":1,"labels":{}}',
    '[]',
])
def test_invalid_jel_labels_fail_before_building(tmp_path, data):
    path = tmp_path / "jel.json"
    path.write_text(data, encoding="utf-8")
    with pytest.raises(ValueError):
        load_economics_jel_labels(path)
