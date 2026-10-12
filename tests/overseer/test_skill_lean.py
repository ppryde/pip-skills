"""The lean overseer skills (WF-265 PR B): the cut cannot drop a rule the model relies on,
the generated CLI block cannot drift, every reference is wired, and no rule is stated twice."""
import re
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import models

OVERSEER = Path(__file__).resolve().parents[2] / "plugins" / "overseer"
ORCH = OVERSEER / "skills" / "orchestrate"
LEDGER = OVERSEER / "skills" / "ledger"
SKILL = (ORCH / "SKILL.md").read_text()
LEDGER_SKILL = (LEDGER / "SKILL.md").read_text()

# Rules taken from the pre-lean SKILL.md (0.28.2): each must still be stated.
REQUIRED_ORCHESTRATE = [
    "never search the filesystem for it",
    '"<base directory>/../../scripts/cli.py" --root . <verb>',
    "No `VAR=value` prefixes, no `$var` words",
    "`--brief-file` / `--text-file`",
    "<<'EOF'",
    "You dispatch; you never do the work",
    "**never fork**",
    "`release <card>` first",
    "Skip `policy.md` for S and M cards",
    "should need NONE of them",
    "Review gates (plan-review, impl-review) never shrink at any size",
    "`--chunk` defaults to `1`",
    "`--advance` runs `set-stage` first",
    "`set-field <child> --parent <this-card>`",
    "keeps a second planning pass",
    "empty cannot advance",
    "A `GATE:` refusal",
    "Never route around it",
    "Minors alone never force a round",
    "You do not read the findings",
    "WITHDRAW or MAINTAIN",
    'block <id> --reason "user: review deadlock',
    "never call `log-review`",
    "Never tell a reviewer what NOT to flag",
    "Never pre-rate severities",
    "`--var` is capped at 300 chars",
    "Dispatch in the foreground",
    "`run_in_background: false`",
    "**Never poll**",
    "facts --pending --card <id>",
    "`accept-fact <P-id>` / `reject-fact <P-id> --reason",
    "never `release` past it",
    "`TRIPWIRE: …`",
    "`depends`",
    "[<id>]",
    "`metadata: {card: <id>}`",
    "never hand-edit it",
    "`unclaim <id>`",
    "do not CC peer traffic",
    "overseer:overseer-planner|implementer|reviewer|fixer|verifier",
    "`vigil begin`",
    "**at every stage boundary**",
    "orchestrate owns the pipeline",
    "`test-driven-development`",
]
REQUIRED_LEDGER = [
    "Never edit `board.db`",
    'python3 "<base directory>/../../scripts/cli.py" --root . <verb>',
    "always check for in-flight work first",
    "**resume / park / block / abandon**",
    "Never silently start fresh",
    "Write a cold-pickup goal",
    "show it before saving",
    "bootstrap → planning → plan-review → implementation → impl-review",
    "Exit 2 = the 2× budget tripwire",
    "report hook",
    "automatically",
    "block <id> --reason \"user:",
    "never silently rewrite it",
    "`append-body <id> Decisions",
]


def _flat(text: str) -> str:
    """Collapse line wrapping: a rule split across two lines is still the same rule."""
    return " ".join(text.split())


@pytest.mark.parametrize("phrase", REQUIRED_ORCHESTRATE)
def test_orchestrate_keeps_the_rule(phrase):
    assert phrase in _flat(SKILL), phrase


@pytest.mark.parametrize("phrase", REQUIRED_LEDGER)
def test_ledger_keeps_the_rule(phrase):
    assert phrase in _flat(LEDGER_SKILL), phrase


def _gen(*args):
    return subprocess.run([sys.executable, str(OVERSEER / "scripts" / "gen_cli_ref.py"), *args],
                          capture_output=True, text=True, check=False)


def test_generated_cli_block_and_reference_are_current():
    proc = _gen("--check")
    assert proc.returncode == 0, proc.stderr


def test_generator_is_deterministic(tmp_path):
    from scripts import gen_cli_ref
    assert gen_cli_ref.reference() == gen_cli_ref.reference()
    assert gen_cli_ref.inline_block() == gen_cli_ref.inline_block()
    assert not re.search(r"\d{4}-\d\d-\d\d", gen_cli_ref.reference())


def test_every_inlined_verb_is_a_real_verb_and_none_is_a_hook_backend():
    from scripts import gen_cli_ref
    block = gen_cli_ref.inline_block()
    first_words = [ln.split()[0] for ln in block.splitlines()]
    assert first_words == list(gen_cli_ref.INLINE)
    assert not set(first_words) & gen_cli_ref.HOOK_BACKENDS


def test_the_skill_names_the_verbs_an_sm_card_needs():
    block = SKILL.split("<!-- cli:begin -->", 1)[1].split("<!-- cli:end -->", 1)[0]
    for verb in ("resume", "bootstrap", "dispatch-prep", "set-stage", "set-section", "set-field",
                 "show", "block", "release", "facts", "accept-fact", "reject-fact", "handover"):
        assert re.search(rf"(?m)^{re.escape(verb)}\b", block), verb
    assert "--brief" in block and "--advance" in block and "--section" in block


def test_tier_table_matches_the_code():
    rows = dict(re.findall(r"(?m)^\| (S|M) \|.*\| (\d+) \|$", SKILL))
    assert {k: int(v) for k, v in rows.items()} == {k: models.ROUND_CAPS[k] for k in ("S", "M")}
    policy = (ORCH / "policy.md").read_text()
    assert re.search(r"(?m)^\| L \|.*\| %d \|$" % models.ROUND_CAPS["L"], policy)


def test_references_table_and_directory_agree():
    table = SKILL.split("## References", 1)[1]
    named = set(re.findall(r"`references/([\w.-]+)`", table))
    on_disk = {p.name for p in (ORCH / "references").iterdir()}
    assert named == on_disk, (named ^ on_disk)
    ledger_table = LEDGER_SKILL.split("## Read when you reach it", 1)[1].split("\n## ", 1)[0]
    assert set(re.findall(r"`references/([\w.-]+)`", ledger_table)) == {
        p.name for p in (LEDGER / "references").iterdir()}


def test_sm_card_needs_no_reference_read():
    """The path an S/M card walks reads no reference: every read instruction is conditional."""
    assert "should need NONE of them" in SKILL
    for row in SKILL.split("## References", 1)[1].splitlines():
        if row.startswith("| `references/"):
            trigger = row.split("|")[2].strip()
            assert not re.match(r"(?i)^(always|every|at start|start of)", trigger), row


def test_cli_location_is_stated_once_per_skill():
    assert SKILL.count("scripts/cli.py") <= 3
    assert "find /" in SKILL  # why: the 120 s timeout a run once paid
    assert "plugins/overseer/scripts/cli.py" not in SKILL + LEDGER_SKILL  # repo-relative form (OL-6)
    assert not re.search(r"(?m)^\s*python \.\.\./cli\.py|\bpython \S*cli\.py", LEDGER_SKILL)


def test_ledger_description_no_longer_auto_triggers_at_session_start():
    desc = LEDGER_SKILL.split("---", 2)[1]
    assert "at the start of any session" not in desc
    assert "SessionStart" in desc


def test_unresponsive_watchdog_is_gone_and_policy_has_no_such_column():
    assert "Unresponsive" not in SKILL
    assert "Unresponsive after" not in (ORCH / "policy.md").read_text()


# --- one canonical statement per rule ------------------------------------------------------

def _words(text: str) -> list[str]:
    text = re.sub(r"<!-- cli:begin -->.*?<!-- cli:end -->", " ", text, flags=re.S)
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    return re.findall(r"[a-z0-9_`<>/-]+", text.lower())


def _shingles(path: Path, n: int = 12) -> set[tuple[str, ...]]:
    w = _words(path.read_text())
    return {tuple(w[i:i + n]) for i in range(len(w) - n + 1)}


def test_no_rule_paragraph_appears_in_two_files():
    files = [ORCH / "SKILL.md", ORCH / "policy.md", LEDGER / "SKILL.md",
             *sorted(p for p in (ORCH / "references").glob("*.md") if p.name != "cli.md"),
             *sorted((LEDGER / "references").glob("*.md"))]
    seen: dict[tuple[str, ...], Path] = {}
    dupes = []
    for f in files:
        for sh in _shingles(f):
            if sh in seen and seen[sh] != f:
                dupes.append((seen[sh].name, f.name, " ".join(sh)))
            seen.setdefault(sh, f)
    assert not dupes, "\n".join(f"{a} / {b}: {t}" for a, b, t in dupes[:10])


@pytest.mark.parametrize("ref", sorted(p.name for p in (ORCH / "references").iterdir()))
def test_each_orchestrate_reference_is_pointed_at_from_its_own_step(ref):
    """Wired twice: in the read-when table AND at the step that needs it."""
    body, _, table = SKILL.partition("## References")
    assert f"references/{ref}" in body, f"{ref}: only in the table, no step points at it"
    assert f"references/{ref}" in table


def test_ledger_points_at_its_references_from_the_steps_too():
    body, _, _ = LEDGER_SKILL.partition("## Read when you reach it")
    for ref in ("relationships.md",):
        assert f"references/{ref}" in body
