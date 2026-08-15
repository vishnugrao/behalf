import subprocess
import sys

import pytest

from behalf.persona import load_room

CONFIG = """
room:
  base: https://example.test/api
  meeting: Test review
me: priya
personas:
  - key: vishnu
    person: Vishnu Rao
    role: engineering lead
    remit: delivery risk
    obligation: Refuse unsupported dates.
    scribe: true
  - key: priya
    person: Priya Nandakumar
    role: product
    remit: customer commitments
    obligation: Hold the line on promises.
"""


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(CONFIG)
    return path


def test_turn_order_follows_config_order(config):
    assert load_room(config).names == ["Vishnu Rao", "Priya Nandakumar"]


def test_me_selects_this_machines_persona(config):
    room = load_room(config)
    assert room.by_key(room.me).person == "Priya Nandakumar"


def test_first_persona_is_scribe_when_none_declared(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text(CONFIG.replace("    scribe: true\n", ""))
    assert load_room(path).personas[0].scribe


def test_unknown_persona_is_rejected(config):
    with pytest.raises(SystemExit, match="no persona"):
        load_room(config).by_key("nobody")


def test_brief_is_written_in_the_persons_voice(config):
    brief = load_room(config).by_key("vishnu").brief()
    assert brief.startswith("You are Vishnu Rao, engineering lead.")
    assert "on behalf of" not in brief


def test_one_process_runs_exactly_one_named_persona(tmp_path, config):
    result = subprocess.run(
        [sys.executable, "-m", "behalf.cli", "agent", "--persona", "vishnu", "--dry-run"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={
            "PATH": "/usr/bin:/bin",
            "BEHALF_CONFIG": str(config),
            "BEHALF_STATE_DIR": str(tmp_path / "state"),
            "BEHALF_LEDGER_DIR": str(tmp_path / "ledger"),
            "BEHALF_OUT_DIR": str(tmp_path / "out"),
            "BEHALF_PROVIDER": "scripted",
            "PYTHONPATH": str(__import__("pathlib").Path(__file__).resolve().parents[1] / "src"),
        },
    )
    assert result.returncode == 0, result.stderr
    assert "persona   Vishnu Rao (vishnu)" in result.stdout
    assert "You are Vishnu Rao, engineering lead." in result.stdout
    assert "Priya Nandakumar" not in result.stdout.split("roster")[0]


def test_a_second_process_runs_the_other_persona(tmp_path, config):
    launches = []
    for key, person in (("vishnu", "Vishnu Rao"), ("priya", "Priya Nandakumar")):
        result = subprocess.run(
            [sys.executable, "-m", "behalf.cli", "agent", "--persona", key, "--dry-run"],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            env={
                "PATH": "/usr/bin:/bin",
                "BEHALF_CONFIG": str(config),
                "BEHALF_STATE_DIR": str(tmp_path / f"state-{key}"),
                "BEHALF_LEDGER_DIR": str(tmp_path / "ledger"),
                "BEHALF_OUT_DIR": str(tmp_path / "out"),
                "BEHALF_PROVIDER": "scripted",
                "PYTHONPATH": str(
                    __import__("pathlib").Path(__file__).resolve().parents[1] / "src"
                ),
            },
        )
        assert result.returncode == 0, result.stderr
        launches.append((person, result.stdout))

    for person, output in launches:
        assert f"persona   {person}" in output
    assert launches[0][1] != launches[1][1]
