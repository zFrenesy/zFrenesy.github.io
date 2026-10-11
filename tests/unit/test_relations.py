from rp.identity.relations import Relation, check_relations, subproblem_children


def codes(relations, known=None):
    return sorted(issue.code for issue in check_relations(relations, known))


def test_valid_tree_with_extra_edges():
    rels = [
        Relation("b", "subproblem_of", "a", primary=True),
        Relation("c", "subproblem_of", "a", primary=True),
        Relation("c", "subproblem_of", "b"),
        Relation("d", "variant_of", "a"),
        Relation("a", "generalises", "d"),
    ]
    assert codes(rels, {"a", "b", "c", "d"}) == []
    assert subproblem_children(rels) == {"a": ["b", "c"]}


def test_cycles_are_rejected():
    rels = [
        Relation("a", "subproblem_of", "b", primary=True),
        Relation("b", "subproblem_of", "c", primary=True),
        Relation("c", "subproblem_of", "a", primary=True),
    ]
    assert codes(rels) == ["relation.cycle"]


def test_secondary_edges_also_count_for_cycles():
    rels = [Relation("a", "subproblem_of", "b", primary=True), Relation("b", "subproblem_of", "a", primary=True)]
    assert "relation.cycle" in codes(rels)


def test_structural_errors():
    rels = [
        Relation("a", "subproblem_of", "b", primary=True),
        Relation("a", "subproblem_of", "c", primary=True),
        Relation("a", "related", "a"),
        Relation("a", "related", "x"),
        Relation("a", "related", "x"),
        Relation("a", "implies", "b", primary=True),
        Relation("a", "solves", "b"),
        Relation("e", "subproblem_of", "b"),
    ]
    assert codes(rels, {"a", "b", "c"}) == [
        "relation.duplicate",
        "relation.multiple_primary_parents",
        "relation.no_primary_parent",
        "relation.primary_misuse",
        "relation.self",
        "relation.unknown_target",
        "relation.unknown_type",
    ]


def test_reparenting_changes_only_edges():
    before = [Relation("b", "subproblem_of", "a", primary=True)]
    after = [Relation("b", "subproblem_of", "c", primary=True), Relation("b", "subproblem_of", "a")]
    assert subproblem_children(before) == {"a": ["b"]}
    assert subproblem_children(after) == {"c": ["b"]}
    assert codes(after) == []
