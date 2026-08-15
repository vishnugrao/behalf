import pytest

from behalf.agent import AgentRun
from behalf.chatroom import Message
from behalf.convergence import ConvergenceTracker
from behalf.persona import Persona


class Harness(AgentRun):
    def __init__(self, person, roster, max_rounds=8):
        self.roster = roster
        self.transcript = []
        self.spoken = 0
        self.rounds_closed = 0
        self.tracker = ConvergenceTracker(participants=set(roster), max_rounds=max_rounds)
        self.persona = Persona(
            key=person.lower(), person=person, role="tester", remit="", obligation=""
        )

    def hear(self, person, times=1):
        for _ in range(times):
            self.transcript.append(Message(id=0, agent_name=person, content="x"))

    def say(self, times=1):
        self.spoken += times


@pytest.fixture
def roster():
    return ["Vishnu Rao", "Priya Nandakumar", "Marco Silvestri"]


def test_first_person_opens_without_waiting(roster):
    assert Harness("Vishnu Rao", roster).my_turn()


def test_later_people_wait_for_those_ahead(roster):
    priya = Harness("Priya Nandakumar", roster)
    assert not priya.my_turn()
    priya.hear("Vishnu Rao")
    assert priya.my_turn()

    marco = Harness("Marco Silvestri", roster)
    marco.hear("Vishnu Rao")
    assert not marco.my_turn()
    marco.hear("Priya Nandakumar")
    assert marco.my_turn()


def test_every_position_counts_the_same_rounds(roster):
    agents = {name: Harness(name, roster) for name in roster}
    for _ in range(3):
        for speaker in roster:
            agents[speaker].say()
            for listener in roster:
                if listener != speaker:
                    agents[listener].hear(speaker)
    for agent in agents.values():
        agent.close_finished_rounds()
        assert agent.tracker.round_index == 3


def test_round_cap_is_reached_by_the_scribe_not_only_the_last_person(roster):
    scribe = Harness("Vishnu Rao", roster, max_rounds=2)
    for _ in range(2):
        scribe.say()
        scribe.hear("Priya Nandakumar")
        scribe.hear("Marco Silvestri")
    scribe.close_finished_rounds()
    assert scribe.tracker.verdict().converged


def test_partial_round_does_not_close(roster):
    agent = Harness("Vishnu Rao", roster)
    agent.say()
    agent.hear("Priya Nandakumar")
    agent.close_finished_rounds()
    assert agent.tracker.round_index == 0


class Draining(Harness):
    def __init__(self, person, roster, incoming):
        super().__init__(person, roster)
        self._incoming = incoming

        class Room:
            def read(_self):
                return incoming

        self.room = Room()


def test_strangers_do_not_count_toward_convergence(roster):
    stranger = Message(id=1, agent_name="Atlas-Product", content='x <state>{"ratify":true}</state>')
    colleague = Message(
        id=2, agent_name="Priya Nandakumar", content='y <state>{"ratify":true}</state>'
    )
    agent = Draining("Vishnu Rao", roster, [stranger, colleague])
    agent.drain()

    assert "Atlas-Product" not in agent.tracker.latest
    assert "Priya Nandakumar" in agent.tracker.latest
    assert "Atlas-Product" not in agent.tracker.participants


def test_strangers_still_appear_in_the_transcript(roster):
    stranger = Message(id=1, agent_name="Atlas-Product", content="something relevant")
    agent = Draining("Vishnu Rao", roster, [stranger])
    agent.drain()
    assert agent.transcript[0].agent_name == "Atlas-Product"
