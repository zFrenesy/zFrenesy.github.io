from datetime import date

import pytest

from rp.identity.ids import new_id
from rp.reviews import ReviewInput, summarise_reviews

CID = new_id("contribution")
R1, R2 = new_id("revision"), new_id("revision")
ORDER = {CID: [R1, R2]}


def review(rid, finding, reviewer, on, *, kind="review", responds_to=None, retracts=None):
    record = {"contribution_id": new_id("contribution"), "revision_id": new_id("revision"), "type": kind,
              "targets": [{"target_kind": "contribution_revision", "contribution_id": CID, "revision_id": rid}],
              "review": {"finding": finding}}
    if responds_to:
        record["review"]["responds_to"] = {"contribution_id": responds_to.ref[0], "revision_id": responds_to.ref[1]}
    if retracts:
        record["review"]["retracts"] = {"contribution_id": retracts.ref[0], "revision_id": retracts.ref[1]}
    return ReviewInput(record, reviewer, on)


def summary(*reviews, today=date(2026, 6, 1)):
    return summarise_reviews(reviews, ORDER, today)


def test_objection_disputes_only_its_revision_and_counts_are_by_finding():
    gap = review(R1, "gap_found", "1", date(2026, 1, 1))
    support = review(R1, "supports", "2", date(2026, 1, 2))
    result = summary(gap, support)
    assert result[(CID, R1)].disputed and result[(CID, R1)].note == "Disputed"
    assert result[(CID, R1)].counts == {"gap_found": 1, "supports": 1}
    assert (CID, R2) not in result  # nothing transfers to R2


def test_favourable_reviews_do_not_transfer_to_a_new_revision():
    result = summary(review(R1, "supports", "2", date(2026, 1, 2)))
    assert (CID, R2) not in result and not result[(CID, R1)].disputed


def test_objector_retracts():
    gap = review(R1, "gap_found", "1", date(2026, 1, 1))
    result = summary(gap, review(R1, "comment", "1", date(2026, 1, 5), retracts=gap))
    assert not result[(CID, R1)].disputed and result[(CID, R1)].objections[0].state == "retracted"


def test_someone_else_cannot_retract():
    gap = review(R1, "gap_found", "1", date(2026, 1, 1))
    assert summary(gap, review(R1, "comment", "9", date(2026, 1, 5), retracts=gap))[(CID, R1)].disputed


def test_later_revision_resolves_when_a_reviewer_marks_it():
    gap = review(R1, "counterexample", "1", date(2026, 1, 1))
    fixed = review(R2, "supports", "7", date(2026, 2, 1), responds_to=gap)
    result = summary(gap, fixed)
    assert result[(CID, R1)].objections[0].state == "resolved" and not result[(CID, R1)].disputed
    same_revision = review(R1, "supports", "7", date(2026, 2, 1), responds_to=gap)
    assert summary(gap, same_revision)[(CID, R1)].disputed  # a third party on the same revision cannot resolve it
    objection_reply = review(R2, "error_found", "7", date(2026, 2, 1), responds_to=gap)
    assert summary(gap, objection_reply)[(CID, R1)].disputed


@pytest.mark.parametrize("today, objector_replies, expected", [
    (date(2026, 3, 1), False, "Disputed"),
    (date(2026, 6, 1), False, "Response given; objector has not replied"),
    (date(2026, 6, 1), True, "Disputed"),
])
def test_author_response_and_ninety_days(today, objector_replies, expected):
    gap = review(R1, "error_found", "1", date(2026, 1, 1))
    answer = review(R1, "comment", "author", date(2026, 1, 10), kind="author_response", responds_to=gap)
    items = [gap, answer]
    if objector_replies:
        items.append(review(R1, "comment", "1", date(2026, 2, 1)))
    result = summary(*items, today=today)
    assert result[(CID, R1)].note == expected
    assert result[(CID, R1)].counts == {"error_found": 1, **({"comment": 1} if objector_replies else {})}
    assert result[(CID, R1)].responses == [answer]
