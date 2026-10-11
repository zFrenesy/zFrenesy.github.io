"""Source resolution flows into display status, never back into source observations."""

from copy import deepcopy
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader

from rp.site.model import Contribution, Problem


def problem_with(source_status, claim=None):
    problem = Problem(
        record={"sources": [] if source_status is None else [{
            "normalised_status": source_status, "authority": "Original catalogue",
        }]},
        alias="ERDOS-1", folder=Path("problem"), statement_name="statement.tex", statement=b"",
    )
    if claim:
        problem.contributions.append(Contribution(
            record={"type": "attempt", "claim": {"type": claim}},
            alias="ERDOS-1-A1", folder=Path("attempt"), files={},
            revision_label="r1", accepted_fingerprint="",
        ))
    return problem


@pytest.mark.parametrize("source_status", ["solved", "proved", "disproved", "independent"])
@pytest.mark.parametrize("claim", [None, "exploration", "partial_result"])
def test_solved_source_also_means_solved_llm_status(source_status, claim):
    problem = problem_with(source_status, claim)
    before = deepcopy(problem.record)
    assert problem.status_label == "Solved"
    assert problem.llm_status == "Solved"
    assert problem.record == before


@pytest.mark.parametrize("source_status", [None, "open", "partially_solved", "unknown", "other"])
@pytest.mark.parametrize("claim", ["full_solution", "full_disproof"])
def test_solution_claim_never_changes_source_status(source_status, claim):
    problem = problem_with(source_status, claim)
    before = deepcopy(problem.record)
    assert problem.llm_status == "Solved"
    assert problem.status_label != "Solved"
    assert problem.record == before


@pytest.mark.parametrize("claim,expected", [
    (None, "Open"),
    ("exploration", "Open"),
    ("partial_result", "Partially solved"),
    ("conditional_result", "Partially solved"),
])
def test_unsolved_source_keeps_claim_derived_llm_status(claim, expected):
    assert problem_with("open", claim).llm_status == expected


def test_status_line_distinguishes_source_resolution_from_an_llm_claim():
    templates = Path(__file__).resolve().parents[2] / "site" / "templates"
    environment = Environment(loader=FileSystemLoader(templates), autoescape=True)
    macros = environment.get_template("macros.html").make_module({"url": lambda path: path})
    solved_source = str(macros.status_line(problem_with("proved")))
    claimed_solution = str(macros.status_line(problem_with("open", "full_solution")))
    assert "LLM status <strong>Solved</strong>" in solved_source
    assert ">from source status</a>" in solved_source
    assert "unverified" not in solved_source
    assert ">unverified</a>" in claimed_solution
    assert "from source status" not in claimed_solution
