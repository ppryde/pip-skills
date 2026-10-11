"""Hard stage gates (WF-265 PR D2, OL-10 / OR-2). Pure: no I/O, no clock.

A gate is a rule a card must satisfy before it moves FORWARD into a stage.
Rules read the card text and the ``stage_evidence`` rows the report hook (and
``dispatch-prep``) record, never prose alone: a verifier's FAIL is also written
into ``## Verification``, so "non-empty" proves nothing.

====================  =========================================================
Move into             Requires
====================  =========================================================
``implementation``    ``## Plan`` real; plan-review latest round clean and
                      complete -- unless a ``brief`` row exists (the S shortcut)
``verification``      impl-review latest round clean and complete (all sizes)
``awaiting-merge``    ``## Verification`` real AND the latest verifier PASSed
====================  =========================================================

"Complete" is the crashed-reviewer rule: ``dispatch-prep`` records one
``dispatch`` row per reviewer slot, and a slot with a dispatch but no later
``review`` row blocks the gate -- an absent verdict is never an approval.

Dispatch gates (``check_dispatch``): reviewer round n needs n <= cap and, past
round 1, a fixer report for round n-1; a fixer for round n needs n < cap (at
the cap the loop is a deadlock: block the card).

Skipped stages do not skip gates: jumping over a gated stage checks its rules
too. Only forward moves are gated; moving back (re-work) never is.
"""
from __future__ import annotations

from typing import NamedTuple, Sequence

from scripts.models import DEFAULT_ROUND_CAP, ROUND_CAPS, STAGES, Card

PLAN_PENDING = "_(pending)_"
MODES = ("hard", "warn", "off")
REVIEW_STAGES = ("plan-review", "impl-review")
# Evidence kinds: review | fix | verify | brief | plan | dispatch | force
GATED_STAGES = ("implementation", "verification", "awaiting-merge")


class Evidence(NamedTuple):
    id: int
    stage: str
    kind: str
    round: "int | None"
    slot: str
    status: str
    critical: "int | None"
    important: "int | None"
    minor: "int | None"
    detail: str


class GateRefused(Exception):
    """Raised inside the card's transaction to roll it back; the CLI prints one
    ``GATE:`` line per problem and exits 3."""

    def __init__(self, problems: "list[str]"):
        super().__init__("; ".join(problems))
        self.problems = problems


def cap_for(card: Card) -> int:
    return ROUND_CAPS.get(card.complexity or "", DEFAULT_ROUND_CAP)


def _real(text: "str | None") -> bool:
    t = (text or "").strip()
    return bool(t) and t != PLAN_PENDING


def _block_cmd(card: Card, why: str) -> str:
    return f'block {card.id} --reason "user: review deadlock - {why}"'


def _review_problems(card: Card, stage: str, ev: "Sequence[Evidence]") -> "list[str]":
    reviews = [e for e in ev if e.stage == stage and e.kind == "review" and e.round is not None]
    dispatches = [e for e in ev if e.stage == stage and e.kind == "dispatch"
                  and e.detail == "reviewer" and e.round is not None]
    rounds = [e.round for e in reviews + dispatches if e.round is not None]
    if not rounds:
        return [f"GATE: {stage} has no reviewer evidence - run the {stage} review loop "
                f"(dispatch-prep {card.id} --stage {stage} --role reviewer --slot A --round 1)"]
    latest = max(rounds)
    problems: list[str] = []
    last_dispatch: dict[str, int] = {}
    for e in dispatches:
        if e.round == latest:
            last_dispatch[e.slot] = max(last_dispatch.get(e.slot, 0), e.id)
    in_round = [e for e in reviews if e.round == latest]
    for slot, did in sorted(last_dispatch.items()):
        if not any(r.slot == slot and r.id > did for r in in_round):
            problems.append(
                f"GATE: {stage} round {latest} reviewer {slot} never reported - "
                f"re-run dispatch-prep {card.id} --stage {stage} --role reviewer "
                f"--slot {slot} --round {latest}")
    crit = imp = 0
    for e in in_round:
        if e.critical is None or e.important is None:  # legacy verdict line
            if not e.status.lower().startswith("approved"):
                imp += 1
        else:
            crit += e.critical
            imp += e.important
    if crit or imp:
        problems.append(
            f"GATE: {stage} round {latest} has open findings ({crit}C {imp}I) - "
            f"dispatch-prep {card.id} --stage {stage} --role fixer --round {latest}, "
            f"then re-review round {latest + 1}")
    return problems


def _verify_problems(card: Card, ev: "Sequence[Evidence]") -> "list[str]":
    problems: list[str] = []
    if not _real(card.sections.get("## Verification")):
        problems.append(f"GATE: ## Verification is empty - dispatch-prep {card.id} "
                        "--stage verification --role verifier --advance")
    verifies = [e for e in ev if e.kind == "verify"]
    dispatches = [e for e in ev if e.kind == "dispatch" and e.detail == "verifier"]
    last_v = max((e.id for e in verifies), default=0)
    last_d = max((e.id for e in dispatches), default=0)
    if last_d > last_v:
        problems.append("GATE: the verifier was dispatched but never reported - "
                        f"re-run dispatch-prep {card.id} --stage verification --role verifier")
    elif not verifies:
        problems.append("GATE: no verifier PASS is recorded - "
                        f"dispatch-prep {card.id} --stage verification --role verifier --advance")
    else:
        latest = max(verifies, key=lambda e: e.id)
        if latest.status.strip().upper() != "PASS":
            problems.append(f"GATE: the latest verification is {latest.status or 'not PASS'} - "
                            "fix and re-run the verifier")
    return problems


def _stage_problems(card: Card, gated: str, ev: "Sequence[Evidence]") -> "list[str]":
    if gated == "implementation":
        problems: list[str] = []
        if not _real(card.sections.get("## Plan")):
            problems.append(f"GATE: ## Plan is empty - dispatch-prep {card.id} "
                            "--stage planning --role planner --advance")
        # The S shortcut skips plan-review by design; an M/L card does not get to.
        if not (card.complexity in (None, "S") and any(e.kind == "brief" for e in ev)):
            problems += _review_problems(card, "plan-review", ev)
        return problems
    if gated == "verification":
        return _review_problems(card, "impl-review", ev)
    return _verify_problems(card, ev)


def check_transition(card: Card, target: str, ev: "Sequence[Evidence]") -> "list[str]":
    """Problems (``GATE: ...`` lines) blocking ``card`` from moving to ``target``;
    empty = free to move. Non-moves and backward moves are never gated."""
    if target not in STAGES or card.stage == target:
        return []
    cur = STAGES.index(card.stage) if card.stage in STAGES else -1
    new = STAGES.index(target)
    if new <= cur:
        return []
    problems: list[str] = []
    for gated in GATED_STAGES:
        if cur < STAGES.index(gated) <= new:
            problems += _stage_problems(card, gated, ev)
    return problems


def check_dispatch(card: Card, stage: str, role: str, round_no: int,
                   ev: "Sequence[Evidence]") -> "list[str]":
    if stage not in REVIEW_STAGES or role not in ("reviewer", "fixer"):
        return []
    cap = cap_for(card)
    problems: list[str] = []
    if round_no < 1:
        return [f"GATE: --round must be >= 1 (got {round_no})"]
    if role == "reviewer":
        if round_no > cap:
            problems.append(
                f"GATE: {stage} round {round_no} exceeds the cap ({cap}) for a "
                f"{card.complexity or 'M'} card - "
                + _block_cmd(card, f"{stage} still open after {cap} rounds"))
        elif round_no > 1 and not any(
                e.kind == "fix" and e.stage == stage and e.round == round_no - 1 for e in ev):
            problems.append(
                f"GATE: {stage} round {round_no} needs a fixer report for round "
                f"{round_no - 1} - dispatch-prep {card.id} --stage {stage} --role fixer "
                f"--round {round_no - 1}")
    elif round_no >= cap:
        problems.append(
            f"GATE: {stage} round {round_no} is the last allowed round ({cap}) for a "
            f"{card.complexity or 'M'} card; no fixer - "
            + _block_cmd(card, f"{stage} still open after {cap} rounds"))
    return problems
