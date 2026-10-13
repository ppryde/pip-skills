"""``next <card>`` (WF-280): the orchestrator's one-line answer to "what now?".

Pure: no I/O, no clock. Reads the card and its ``stage_evidence`` rows and
prints the stage, the verdict state of the review loop and the exact next call
with the agent and model tier to dispatch it to. It moves the tier table, the
panel shape and the review-loop decision rule out of SKILL prose and into code,
so the orchestrator spends a lookup instead of a turn of deliberation.

The rules mirror ``gates.py`` (what a gate demands) and ``policy.md`` /
``SKILL.md`` (tiers and panels); the verdict state uses the same "latest round
is the newest evidence row" reading as the gates.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from scripts.gates import PLAN_PENDING, Evidence, cap_for
from scripts.models import Card

AGENT_PREFIX = "overseer:overseer-"
GATE_ROLES = ("implementer", "verifier", "fixer")
LENSES = ("correctness", "spec-compliance", "maintainability/security")
_CHUNK_RE = re.compile(r"— chunk (\d+) —")


@dataclass(frozen=True)
class Slot:
    slot: str
    lens: "str | None"
    model: str


def _big(card: Card) -> bool:
    return card.complexity in ("L", "XL")


def model_for(card: Card, role: str) -> str:
    """Tier -> model: cheap = haiku, mid = sonnet, strong = opus."""
    if role == "planner":
        return "opus" if _big(card) else "sonnet"
    if role == "implementer":
        return "haiku" if card.complexity == "S" else "sonnet"
    return "sonnet"


def panel(card: Card, round_no: int) -> "list[Slot]":
    """The reviewer slots of one round: S one; M two with distinct lenses; L
    three in round 1 (slot A strong) then two with the strong one retained."""
    if card.complexity == "S":
        return [Slot("A", None, "sonnet")]
    count = 3 if _big(card) and round_no == 1 else 2
    return [
        Slot("ABC"[i], LENSES[i], "opus" if _big(card) and i == 0 else "sonnet")
        for i in range(count)
    ]


def _real(text: "str | None") -> bool:
    t = (text or "").strip()
    return bool(t) and t != PLAN_PENDING


def _prep(card: Card, stage: str, role: str, *, round_no: "int | None" = None,
          slot: "Slot | None" = None, chunk: "int | None" = None, panel_: bool = False,
          advance: bool = False) -> str:
    parts = [f"dispatch-prep {card.id} --stage {stage} --role {role}"]
    if panel_:
        parts.append("--panel")
    if slot is not None:
        parts.append(f"--slot {slot.slot}")
    if round_no is not None:
        parts.append(f"--round {round_no}")
    if slot is not None and slot.lens:
        parts.append(f"--lens {slot.lens}")
    if chunk is not None:
        parts.append(f"--chunk {chunk}")
    if role in GATE_ROLES:
        parts.append('--var gate_commands="…"')  # the repo's gates, as SKILL.md says to pass
    if advance:
        parts.append("--advance")
    target = f"{AGENT_PREFIX}{role}"
    models = ([s.model for s in panel(card, round_no or 1)] if panel_ else
              [slot.model if slot else model_for(card, role)])
    model = "+".join(dict.fromkeys(models))
    return f"{' '.join(parts)} → {target} {model}"


@dataclass(frozen=True)
class _Round:
    number: int
    slots: "dict[str, tuple[str, int, int]]"  # slot -> (status text, critical, important)
    pending: "list[str]"
    fixed: bool

    @property
    def open_findings(self) -> bool:
        return any(c or i for _, c, i in self.slots.values())


def _round_of(stage: str, ev: "Sequence[Evidence]") -> "_Round | None":
    rows = [e for e in ev if e.stage == stage and e.round is not None
            and (e.kind == "review" or (e.kind == "dispatch" and e.detail == "reviewer"))]
    if not rows:
        return None
    latest = max(rows, key=lambda e: e.id).round
    assert latest is not None
    sent: dict[str, int] = {}
    got: dict[str, Evidence] = {}
    for e in rows:
        if e.round != latest:
            continue
        if e.kind == "dispatch":
            sent[e.slot] = max(sent.get(e.slot, 0), e.id)
        elif e.slot not in got or e.id > got[e.slot].id:
            got[e.slot] = e
    pending = sorted(s for s, did in sent.items() if s not in got or got[s].id < did)
    slots: dict[str, tuple[str, int, int]] = {}
    for slot, e in sorted(got.items()):
        if slot in pending:
            continue
        approved = e.status.lower().startswith("approved")
        crit, imp = e.critical or 0, e.important or 0
        if e.critical is None or e.important is None or not (crit or imp):
            if not approved:  # a legacy line, or "found wanting" with no counts: never an approval
                imp = max(imp, 1)
        slots[slot] = ("approved" if approved else "found wanting", crit, imp)
    fixed = any(e.kind == "fix" and e.stage == stage and e.round == latest for e in ev)
    return _Round(latest, slots, pending, fixed)


def _verdicts(r: _Round) -> str:
    parts = []
    for slot in sorted({*r.slots, *r.pending}):
        if slot in r.pending:
            parts.append(f"{slot} pending")
            continue
        status, crit, imp = r.slots[slot]
        parts.append(f"{slot} approved" if status == "approved"
                     else f"{slot} found wanting {crit}C/{imp}I")
    return ", ".join(parts)


def _review_loop(card: Card, stage: str, ev: "Sequence[Evidence]") -> "tuple[str, str]":
    """``(state, action)``; ``state`` continues the ``<id> <stage>`` head."""
    cap = cap_for(card)
    r = _round_of(stage, ev)
    if r is None:
        state = f": no reviewers dispatched (cap {cap})"
        return state, _prep(card, stage, "reviewer", round_no=1, panel_=True)
    state = f" r{r.number}: {_verdicts(r)}"
    if r.pending:
        known = {s.slot: s for s in panel(card, r.number)}
        calls = [_prep(card, stage, "reviewer", round_no=r.number,
                       slot=known.get(p) or Slot(p, None, "sonnet")) for p in r.pending]
        return f"{state} ({len(r.pending)} pending: {', '.join(r.pending)}; cap {cap})", "; ".join(calls)
    if r.open_findings:
        if r.number >= cap:
            return (f"{state} (cap {cap} reached)",
                    f'block {card.id} --reason "user: review deadlock — {stage} still open '
                    f'after {cap} rounds"')
        if r.fixed:
            return (f"{state}; fixed, re-review (cap {cap})",
                    _prep(card, stage, "reviewer", round_no=r.number + 1, panel_=True))
        return f"{state} (cap {cap})", _prep(card, stage, "fixer", round_no=r.number)
    if stage == "plan-review":
        return (f"{state} (cap {cap})",
                f"PLAN GATE: present plan, estimate and PR decomposition to the user, then "
                f"set-stage {card.id} implementation")
    return (f"{state} (cap {cap})",
            _prep(card, "verification", "verifier", advance=True))


def _verification(card: Card, ev: "Sequence[Evidence]") -> "tuple[str, str]":
    verifies = [e for e in ev if e.kind == "verify"]
    sent = [e for e in ev if e.kind == "dispatch" and e.detail == "verifier"]
    last_v = max((e.id for e in verifies), default=0)
    last_d = max((e.id for e in sent), default=0)
    if last_d > last_v:
        return "verification: verifier dispatched, never reported", _prep(
            card, "verification", "verifier")
    if not verifies:
        return "verification: not run", _prep(card, "verification", "verifier")
    status = max(verifies, key=lambda e: e.id).status.strip().upper()
    if status == "PASS":
        return "verification: PASS", f"set-stage {card.id} awaiting-merge"
    return f"verification: {status or 'not PASS'}", (
        "rework: " + _prep(card, "implementation", "implementer", chunk=_chunks_done(card) + 1,
                           advance=True))


def _chunks_done(card: Card) -> int:
    return max((int(n) for n in _CHUNK_RE.findall(card.body)), default=0)


def next_step(card: Card, ev: "Sequence[Evidence]") -> str:
    """One line: ``<id> <stage state> · next: <call> → <agent> <model>``."""
    stage = card.stage or "unstarted"
    head = f"{card.id} {stage}"
    if card.status in ("done", "abandoned"):
        return f"{head}: {card.status} · nothing to dispatch"
    if card.status == "blocked":
        return (f"{head}: blocked: {card.blocked_on or 'no reason recorded'} · next: "
                f"resolve it with the user, then unblock {card.id}")
    if card.status == "parked":
        return f"{head}: parked · next: unpark {card.id} to resume"
    if card.tripwire_breached:
        return (f"{head}: TRIPWIRE, spent {card.budget_actual} of an estimate of "
                f"{card.budget_estimate} tokens · next: stop and escalate to the user")
    if card.stage in (None, "bootstrap"):
        if not card.worktree:
            return f"{head}: no worktree · next: bootstrap --card {card.id}"
        return f"{head}: bootstrapped · next: " + _prep(card, "planning", "planner", advance=True)
    if card.stage == "planning":
        if _real(card.sections.get("## Plan")):
            return (f"{head}: plan written · next: " + _prep(
                card, "plan-review", "reviewer", round_no=1, panel_=True, advance=True))
        return f"{head}: no plan yet · next: " + _prep(card, "planning", "planner")
    if card.stage in ("plan-review", "impl-review"):
        state, action = _review_loop(card, card.stage, ev)
        return f"{head}{state} · next: {action}"
    if card.stage == "implementation":
        done = _chunks_done(card)
        then = _prep(card, "impl-review", "reviewer", round_no=1, panel_=True, advance=True)
        return (f"{head}: chunks done: {done} · next: "
                + _prep(card, "implementation", "implementer", chunk=done + 1)
                + f"; then: {then}")
    if card.stage == "verification":
        state, action = _verification(card, ev)
        return f"{card.id} {state} · next: {action}"
    if card.pr:
        return f"{head}: PR {card.pr} · next: the merge is the user's; `done {card.id}` after it lands"
    return f"{head}: no PR yet · next: raise the PR, set-field {card.id} --pr <url>; the merge is the user's"
