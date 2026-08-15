"""Scaling test: N process-isolated agents against one room."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import Config
from .roster import Roster


@dataclass
class AgentResult:
    name: str
    key: str
    pid: int
    exit_code: int
    seconds: float
    log_path: str


@dataclass
class ScaleReport:
    agents: int
    meeting: str
    started: str
    wall_seconds: float
    converged: bool
    rounds_cap: int
    results: list[AgentResult] = field(default_factory=list)
    preread_bytes: int = 0

    def table(self) -> str:
        rows = [f"{'agent':<22}{'pid':>8}{'exit':>6}{'seconds':>10}"]
        rows += [
            f"{r.name:<22}{r.pid:>8}{r.exit_code:>6}{r.seconds:>10.1f}" for r in self.results
        ]
        failures = sum(1 for r in self.results if r.exit_code != 0)
        rows.append("")
        rows.append(
            f"{self.agents} agents · {self.wall_seconds:.1f}s wall · "
            f"{failures} failed · pre-read {self.preread_bytes} bytes · "
            f"converged={self.converged}"
        )
        return "\n".join(rows)


def run_scale_test(cfg: Config, roster: Roster, size: int, stagger: float = 1.5) -> ScaleReport:
    grown = roster.grown_to(size)
    names = ",".join(grown.names)
    log_dir = cfg.out_dir / "agents"
    log_dir.mkdir(parents=True, exist_ok=True)

    cfg.preread_path.unlink(missing_ok=True)
    started = time.time()
    procs: list[tuple[subprocess.Popen, Path, float, object]] = []

    for index, agent in enumerate(grown.agents):
        log_path = log_dir / f"{agent.name}.log"
        handle = log_path.open("w", encoding="utf-8")
        command = [
            sys.executable, "-m", "behalf.cli", "agent",
            "--role", agent.key,
            "--roster", names,
            "--meeting", grown.meeting,
        ]
        if agent.scribe:
            command.append("--scribe")
        env = {**os.environ, "BEHALF_AGENT_INDEX": str(index)}
        proc = subprocess.Popen(command, stdout=handle, stderr=subprocess.STDOUT, env=env)
        procs.append((proc, log_path, time.time(), handle))
        time.sleep(stagger)

    results = []
    for proc, log_path, launch, handle in procs:
        code = proc.wait()
        handle.close()
        name = log_path.stem
        results.append(
            AgentResult(
                name=name,
                key=next((a.key for a in grown.agents if a.name == name), name),
                pid=proc.pid,
                exit_code=code,
                seconds=time.time() - launch,
                log_path=str(log_path),
            )
        )

    preread_bytes = cfg.preread_path.stat().st_size if cfg.preread_path.exists() else 0
    report = ScaleReport(
        agents=size,
        meeting=grown.meeting,
        started=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)),
        wall_seconds=time.time() - started,
        converged=preread_bytes > 0,
        rounds_cap=cfg.max_rounds,
        results=results,
        preread_bytes=preread_bytes,
    )
    (cfg.out_dir / "scale-report.json").write_text(
        json.dumps(asdict(report), indent=2), encoding="utf-8"
    )
    return report
