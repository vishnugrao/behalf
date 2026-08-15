"""Render the one-page pre-read from ratified proposals."""
from __future__ import annotations

from datetime import datetime, timezone

from .convergence import ConvergenceTracker
from .protocol import Proposal

SECTIONS = [
    ("decision", "Decisions that already landed"),
    ("fact", "State of play"),
    ("risk", "Risks and open threads"),
    ("conflict", "Unresolved disagreement"),
    ("ask", "What this meeting needs to decide"),
]

MAX_LINES_PER_SECTION = 5


def _bullet(proposal: Proposal) -> str:
    evidence = ", ".join(proposal.evidence[:3])
    suffix = f" _[{evidence}]_" if evidence else ""
    return f"- {proposal.claim.rstrip('.')}.{suffix}"


def render_preread(
    *,
    meeting: str,
    tracker: ConvergenceTracker,
    store_stats: dict[str, object],
    reason: str,
) -> str:
    proposals = tracker.agreed_proposals()
    by_kind: dict[str, list[Proposal]] = {}
    for proposal in proposals:
        by_kind.setdefault(proposal.kind, []).append(proposal)

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# Pre-read — {meeting}",
        "",
        f"_Generated {generated} · agreed by {', '.join(tracker.ratifiers) or 'no one'} "
        f"across {tracker.round_index} rounds · {reason}._",
        "",
    ]

    for kind, heading in SECTIONS:
        items = by_kind.get(kind, [])
        if not items:
            continue
        lines.append(f"## {heading}")
        for proposal in items[:MAX_LINES_PER_SECTION]:
            lines.append(_bullet(proposal))
        if len(items) > MAX_LINES_PER_SECTION:
            lines.append(f"- _+{len(items) - MAX_LINES_PER_SECTION} more in the context store._")
        lines.append("")

    leftovers = [p for k, ps in by_kind.items() if k not in dict(SECTIONS) for p in ps]
    if leftovers:
        lines.append("## Also worth knowing")
        lines.extend(_bullet(p) for p in leftovers[:MAX_LINES_PER_SECTION])
        lines.append("")

    if tracker.holdouts:
        lines.append(f"> **Not ratified by:** {', '.join(tracker.holdouts)}. "
                     "Treat the lines above as provisional for their areas.")
        lines.append("")

    lines.append(
        f"<sub>Sourced from {store_stats.get('live_entries', '?')} live entries / "
        f"{store_stats.get('chunks', '?')} indexed chunks · "
        f"embedder {store_stats.get('embedder', '?')}.</sub>"
    )
    return "\n".join(lines).rstrip() + "\n"
