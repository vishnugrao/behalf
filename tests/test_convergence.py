import pytest

from behalf.convergence import ConvergenceTracker
from behalf.protocol import AgentState, Proposal, render_message, strip_state
from behalf.brain import extract_json


def state(agent, *, intent="propose", claims=(), ratify=False, concerns=()):
    return AgentState(
        agent=agent,
        intent=intent,
        proposals=[Proposal(claim=c, evidence=["e1"]) for c in claims],
        concerns=list(concerns),
        ratify=ratify,
    )


@pytest.fixture
def tracker():
    return ConvergenceTracker(
        participants={"A", "B", "C"}, stability_rounds=2, ratify_threshold=0.67, max_rounds=8
    )


def test_duplicate_claims_are_not_counted_as_new(tracker):
    assert tracker.observe(state("A", claims=["launch is 17 March"])) == 1
    assert tracker.observe(state("B", claims=["Launch is 17 March."])) == 0


def test_agreement_alone_does_not_converge(tracker):
    for _ in range(3):
        for name in "ABC":
            tracker.observe(state(name, intent="ratify", ratify=True))
        tracker.close_round()
    verdict = tracker.verdict()
    assert not verdict.converged
    assert "challenge" in verdict.reason


def test_stable_scrutinised_and_ratified_converges(tracker):
    tracker.observe(state("A", claims=["launch is 17 March"]))
    tracker.observe(state("B", intent="challenge", concerns=["who owns comms?"]))
    tracker.observe(state("C", claims=["security fix blocks GA"]))
    tracker.close_round()

    tracker.observe(state("A", intent="revise", ratify=True))
    tracker.observe(state("B", intent="support", ratify=True))
    tracker.observe(state("C", intent="ratify", ratify=True))
    tracker.close_round()

    tracker.observe(state("A", intent="ratify", ratify=True))
    tracker.observe(state("B", intent="ratify", ratify=True))
    tracker.observe(state("C", intent="ratify", ratify=True))
    tracker.close_round()

    verdict = tracker.verdict()
    assert verdict.converged, verdict.reason
    assert verdict.ratified == ["A", "B", "C"]


def test_holdout_below_threshold_blocks_convergence(tracker):
    tracker.observe(state("A", intent="challenge", concerns=["unowned"]))
    tracker.observe(state("B", intent="revise"))
    tracker.close_round()
    tracker.observe(state("A", intent="ratify", ratify=True))
    tracker.observe(state("B", intent="abstain", ratify=False))
    tracker.observe(state("C", intent="abstain", ratify=False))
    tracker.close_round()
    tracker.close_round()

    verdict = tracker.verdict()
    assert not verdict.converged
    assert "ratification" in verdict.reason
    assert set(verdict.outstanding) == {"B", "C"}


def test_round_cap_forces_a_verdict():
    tracker = ConvergenceTracker(participants={"A"}, max_rounds=2)
    tracker.observe(state("A", claims=["x"]))
    tracker.close_round()
    tracker.observe(state("A", claims=["y"]))
    tracker.close_round()
    assert tracker.verdict().converged
    assert "cap" in tracker.verdict().reason


def test_message_round_trips_through_the_wire_format():
    original = state("A", claims=["launch is 17 March"], concerns=["comms"], ratify=True)
    wire = render_message("Here is my view.", original)
    assert strip_state(wire) == "Here is my view."
    parsed = AgentState.from_dict("A", extract_json(wire))
    assert parsed.ratify is True
    assert parsed.proposals[0].claim == "launch is 17 March"
    assert parsed.concerns == ["comms"]


def test_missing_trailer_is_an_abstention():
    parsed = AgentState.from_dict("A", extract_json("just prose, no json here"))
    assert parsed.intent == "abstain"
    assert parsed.ratify is False
