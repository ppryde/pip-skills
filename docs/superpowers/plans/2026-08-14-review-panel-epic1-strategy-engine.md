# review-panel Epic 1 — Strategy Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the orchestration spine of the `review-panel` plugin so every review strategy runs end-to-end against a real diff using a single `general` reviewer and/or a review-clone persona, in all three output modes.

**Architecture:** Deterministic parts (config/profile resolution, discovery, finding contract, strictness, persona reading) live in small, unit-tested Python helpers under `plugins/review-panel/scripts/`. The reasoning-heavy orchestration (invocation parsing, scope via git, subagent dispatch, output rendering) lives as prose in `skills/convene/SKILL.md`, which reads swappable strategy and reviewer markdown files. This mirrors how `review-clone` pairs testable `scripts/` with prose skills.

**Tech Stack:** Python 3.11+ (stdlib + PyYAML), pytest, Claude Code plugin (SKILL.md + commands), `gh` CLI (only for `inline` output), git.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-08-14-review-panel-design.md` — this plan implements its §13 "Epic 1" scope only.
- **Python floor:** 3.11+. Only third-party dependency is `PyYAML`.
- **Neutral voice:** no Witchfinder/persona flavour anywhere in shipped output. Findings render plainly.
- **No repo hardcoding:** nothing references `pip-skills`; all project config lives in the *target* repo's `.review-panel/`.
- **Reviewer sources:** a reviewer key is either a built-in name (`general`) or `clone:<alias>`. Both produce the identical finding contract.
- **Review-clone root resolution (parity + isolation):** `REVIEW_CLONE_ROOT` if set, else `$CLAUDE_CONFIG_DIR/review-clone`, else `~/.claude/review-clone`.
- **Subagent model:** every reviewer/critic/judge/arbiter subagent is dispatched with `model: sonnet` (never Fable). SKILL.md prose must state this.
- **Strategies (v1):** `committee` (default), `blind`, `informed`, `adversarial`, `dual-tiebreaker`.
- **Strictness:** `strict` (keep), `pragmatic` (allowed-exception ids → warning), `aspirational` (all → warning). Default `pragmatic`.
- **Severities:** `error`, `warning`, `info`.
- **Test isolation (CLAUDE.md law):** any test that reads a config/state dir MUST pin `CLAUDE_CONFIG_DIR`, `REVIEW_CLONE_ROOT`, `OVERSEER_*` into `tmp_path` via an autouse fixture *before* the code runs. Create nothing outside `tmp_path`.
- **Tooling:** run tests with the worktree venv: `.venv/bin/pytest plugins/review-panel/tests -q` (poetry is unusable here). Create the venv in Task 1.

---

## File Structure

```
plugins/review-panel/
  .claude-plugin/plugin.json           # plugin manifest
  README.md                            # user-facing overview
  commands/review-panel.md             # /review-panel slash command
  templates/config.yml                 # shipped default .review-panel/config.yml
  skills/
    convene/SKILL.md                   # orchestrator (prose workflow + triggers)
    reviewers/
      _template.md                     # reviewer authoring template
      general.md                       # broad-spectrum starter reviewer
    strategies/
      _template.md                     # strategy authoring template
      committee.md  blind.md  informed.md  adversarial.md  dual-tiebreaker.md
  scripts/
    __init__.py
    config.py                          # load + resolve profile/ad-hoc → ResolvedReview
    discovery.py                       # discover strategies + reviewers + clone personas
    contract.py                        # Finding, parse_reviewer_result, collate, render_report
    strictness.py                      # apply strictness + decisions.yml overrides
    personas.py                        # resolve/read a clone persona PERSONA.md
    doclint.py                         # structural lint for strategy/reviewer markdown
  tests/
    conftest.py                        # autouse isolation fixture
    test_config.py  test_discovery.py  test_contract.py
    test_strictness.py  test_personas.py  test_docs.py  test_smoke.py
```

Responsibilities are one-per-file. `config.py` never touches disk beyond the given path; `discovery.py`/`personas.py` own all filesystem/config-dir resolution; `contract.py` is pure data; SKILL.md owns everything that needs a live model or git.

---

### Task 1: Plugin scaffold + isolated test harness

**Files:**
- Create: `plugins/review-panel/.claude-plugin/plugin.json`
- Create: `plugins/review-panel/README.md`
- Create: `plugins/review-panel/scripts/__init__.py` (empty)
- Create: `plugins/review-panel/tests/conftest.py`
- Create: `plugins/review-panel/tests/test_smoke.py` (temporary import guard, replaced in Task 10)

**Interfaces:**
- Produces: an importable package `plugins/review-panel/scripts` and a passing pytest run with the isolation fixture active.

- [ ] **Step 1: Create the plugin manifest**

`plugins/review-panel/.claude-plugin/plugin.json`:
```json
{
  "name": "review-panel",
  "version": "0.1.0",
  "description": "Composable code review: swappable reviewer lenses × orchestration strategies, composed into named profiles.",
  "author": "Pip"
}
```

- [ ] **Step 2: Create a minimal README**

`plugins/review-panel/README.md`:
```markdown
# review-panel

Composable code review. A review is built from two axes bundled into a
named **profile**:

- **Reviewers** — *what* to examine (a lens: concern + voice).
- **Strategies** — *how* to orchestrate (committee, blind, informed,
  adversarial, dual+tiebreaker).

Reviewers come from `skills/reviewers/*.md` or a review-clone persona
(`clone:<alias>`). Configure via `.review-panel/config.yml`. Run with
`/review-panel [profile]`.

See `docs/superpowers/specs/2026-08-14-review-panel-design.md`.
```

- [ ] **Step 3: Create the isolation fixture**

`plugins/review-panel/tests/conftest.py`:
```python
"""Test isolation: pin every state/config dir into tmp_path BEFORE any code
runs, so a test never reads or writes the developer's real ~/.claude* tree.
See pip-skills CLAUDE.md 'Test isolation' for why this is mandatory."""
import pytest


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    cfg.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("REVIEW_CLONE_ROOT", str(cfg / "review-clone"))
    monkeypatch.delenv("OVERSEER_CENTRAL", raising=False)
    monkeypatch.delenv("OVERSEER_DB", raising=False)
    return cfg
```

- [ ] **Step 4: Create the empty package init and a temporary import guard**

`plugins/review-panel/scripts/__init__.py`: empty file.

`plugins/review-panel/tests/test_smoke.py`:
```python
def test_package_imports():
    import scripts  # noqa: F401
```

- [ ] **Step 5: Create the worktree venv and run the harness**

Run:
```bash
cd plugins/review-panel
python3 -m venv .venv
.venv/bin/pip install -q pyyaml pytest
.venv/bin/pytest tests -q -p no:cacheprovider -o addopts="" \
  --rootdir . --import-mode=importlib
```
Expected: 1 passed. (Run pytest from `plugins/review-panel` so `import scripts` resolves.)

- [ ] **Step 6: Commit**

```bash
git add plugins/review-panel/.claude-plugin plugins/review-panel/README.md \
  plugins/review-panel/scripts/__init__.py plugins/review-panel/tests
git commit -m "feat(review-panel): plugin scaffold + isolated test harness"
```

---

### Task 2: Config loader + profile/ad-hoc resolution

**Files:**
- Create: `plugins/review-panel/scripts/config.py`
- Test: `plugins/review-panel/tests/test_config.py`

**Interfaces:**
- Produces:
  - `class ConfigError(Exception)`
  - `@dataclass(frozen=True) ReviewerRef(key: str, source: str, name: str, strictness: str)` where `source ∈ {"builtin","clone"}`
  - `@dataclass(frozen=True) ResolvedReview(strategy: str, scope: str, targets: tuple[str,...], reviewers: tuple[ReviewerRef,...], context: tuple[str,...], output: str)`
  - `load_config(path: Path) -> dict`
  - `parse_reviewer_key(key: str, strictness: str) -> ReviewerRef`
  - `resolve_profile(config: dict, profile: str | None) -> ResolvedReview`
  - `resolve_adhoc(config: dict, reviewer_keys: list[str]) -> ResolvedReview`
- Consumes: nothing from other tasks.

- [ ] **Step 1: Write the failing test**

`plugins/review-panel/tests/test_config.py`:
```python
import textwrap
from pathlib import Path

import pytest

from scripts.config import (
    ConfigError, ReviewerRef, ResolvedReview,
    load_config, parse_reviewer_key, resolve_profile, resolve_adhoc,
)


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "config.yml"
    p.write_text(textwrap.dedent(text))
    return p


def test_parse_builtin_reviewer_key():
    ref = parse_reviewer_key("general", "strict")
    assert ref == ReviewerRef("general", "builtin", "general", "strict")


def test_parse_clone_reviewer_key():
    ref = parse_reviewer_key("clone:danvk", "pragmatic")
    assert ref == ReviewerRef("clone:danvk", "clone", "danvk", "pragmatic")


def test_resolve_profile_merges_defaults_and_strictness(tmp_path):
    cfg = load_config(_write(tmp_path, """
        defaults: { strategy: committee, scope: changed }
        profiles:
          pre-merge:
            strategy: adversarial
            reviewers: { general: strict, "clone:danvk": pragmatic }
    """))
    r = resolve_profile(cfg, "pre-merge")
    assert r.strategy == "adversarial"
    assert r.scope == "changed"
    assert set(r.reviewers) == {
        ReviewerRef("general", "builtin", "general", "strict"),
        ReviewerRef("clone:danvk", "clone", "danvk", "pragmatic"),
    }


def test_resolve_profile_uses_default_profile_when_none(tmp_path):
    cfg = load_config(_write(tmp_path, """
        defaults: { strategy: committee, scope: changed, profile: quick }
        profiles:
          quick: { reviewers: { general: pragmatic } }
    """))
    r = resolve_profile(cfg, None)
    assert r.reviewers == (ReviewerRef("general", "builtin", "general", "pragmatic"),)


def test_resolve_profile_unknown_raises(tmp_path):
    cfg = load_config(_write(tmp_path, "profiles: { a: { reviewers: { general: strict } } }"))
    with pytest.raises(ConfigError, match="unknown profile"):
        resolve_profile(cfg, "nope")


def test_resolve_profile_bad_strictness_raises(tmp_path):
    cfg = load_config(_write(tmp_path, "profiles: { a: { reviewers: { general: harsh } } }"))
    with pytest.raises(ConfigError, match="strictness"):
        resolve_profile(cfg, "a")


def test_resolve_adhoc_defaults_to_committee_changed(tmp_path):
    cfg = load_config(_write(tmp_path, "defaults: {}"))
    r = resolve_adhoc(cfg, ["general", "clone:danvk"])
    assert r.strategy == "committee" and r.scope == "changed"
    assert r.output == "report"
    assert [x.name for x in r.reviewers] == ["general", "danvk"]


def test_load_config_missing_returns_empty(tmp_path):
    assert load_config(tmp_path / "absent.yml") == {}


def test_load_config_malformed_raises(tmp_path):
    bad = tmp_path / "config.yml"
    bad.write_text("profiles: [unbalanced")
    with pytest.raises(ConfigError):
        load_config(bad)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/review-panel && .venv/bin/pytest tests/test_config.py -q --import-mode=importlib`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.config'`.

- [ ] **Step 3: Write the implementation**

`plugins/review-panel/scripts/config.py`:
```python
"""Load .review-panel/config.yml and resolve a profile (or an ad-hoc
reviewer list) into a ResolvedReview the orchestrator can execute."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

VALID_STRICTNESS = {"strict", "pragmatic", "aspirational"}
VALID_SCOPE = {"changed", "full"}
VALID_OUTPUT = {"report", "inline", "interactive"}
DEFAULT_STRATEGY = "committee"
DEFAULT_SCOPE = "changed"
DEFAULT_OUTPUT = "report"
DEFAULT_STRICTNESS = "pragmatic"


class ConfigError(Exception):
    """Raised on malformed config or an impossible resolution request."""


@dataclass(frozen=True)
class ReviewerRef:
    key: str
    source: str  # "builtin" | "clone"
    name: str
    strictness: str


@dataclass(frozen=True)
class ResolvedReview:
    strategy: str
    scope: str
    targets: tuple[str, ...]
    reviewers: tuple[ReviewerRef, ...]
    context: tuple[str, ...]
    output: str


def load_config(path: Path) -> dict:
    if not Path(path).exists():
        return {}
    try:
        data = yaml.safe_load(Path(path).read_text()) or {}
    except yaml.YAMLError as exc:  # noqa: BLE001 - re-raise as our type
        raise ConfigError(f"malformed config: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError("config root must be a mapping")
    return data


def parse_reviewer_key(key: str, strictness: str) -> ReviewerRef:
    if strictness not in VALID_STRICTNESS:
        raise ConfigError(
            f"invalid strictness {strictness!r} for reviewer {key!r}; "
            f"expected one of {sorted(VALID_STRICTNESS)}"
        )
    if key.startswith("clone:"):
        alias = key[len("clone:"):]
        if not alias:
            raise ConfigError("clone reviewer key needs an alias, e.g. clone:danvk")
        return ReviewerRef(key, "clone", alias, strictness)
    return ReviewerRef(key, "builtin", key, strictness)


def _reviewers(raw: dict) -> tuple[ReviewerRef, ...]:
    if not isinstance(raw, dict) or not raw:
        raise ConfigError("a profile needs a non-empty 'reviewers' mapping")
    return tuple(parse_reviewer_key(k, str(v)) for k, v in raw.items())


def resolve_profile(config: dict, profile: str | None) -> ResolvedReview:
    defaults = config.get("defaults", {}) or {}
    profiles = config.get("profiles", {}) or {}
    name = profile or defaults.get("profile")
    if name is None:
        raise ConfigError("no profile given and no defaults.profile set")
    if name not in profiles:
        raise ConfigError(f"unknown profile {name!r}; have {sorted(profiles)}")
    spec = profiles[name] or {}
    strategy = spec.get("strategy", defaults.get("strategy", DEFAULT_STRATEGY))
    scope = spec.get("scope", defaults.get("scope", DEFAULT_SCOPE))
    if scope not in VALID_SCOPE:
        raise ConfigError(f"invalid scope {scope!r}; expected {sorted(VALID_SCOPE)}")
    output = (config.get("output", {}) or {}).get("default", DEFAULT_OUTPUT)
    if output not in VALID_OUTPUT:
        raise ConfigError(f"invalid output {output!r}; expected {sorted(VALID_OUTPUT)}")
    return ResolvedReview(
        strategy=strategy,
        scope=scope,
        targets=tuple(spec.get("targets", []) or []),
        reviewers=_reviewers(spec.get("reviewers", {})),
        context=tuple(spec.get("context", []) or []),
        output=output,
    )


def resolve_adhoc(config: dict, reviewer_keys: list[str]) -> ResolvedReview:
    defaults = config.get("defaults", {}) or {}
    if not reviewer_keys:
        raise ConfigError("ad-hoc review needs at least one reviewer")
    return ResolvedReview(
        strategy=defaults.get("strategy", DEFAULT_STRATEGY),
        scope=defaults.get("scope", DEFAULT_SCOPE),
        targets=(),
        reviewers=tuple(parse_reviewer_key(k, DEFAULT_STRICTNESS) for k in reviewer_keys),
        context=(),
        output=(config.get("output", {}) or {}).get("default", DEFAULT_OUTPUT),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd plugins/review-panel && .venv/bin/pytest tests/test_config.py -q --import-mode=importlib`
Expected: PASS (9 passed).

- [ ] **Step 5: Commit**

```bash
git add plugins/review-panel/scripts/config.py plugins/review-panel/tests/test_config.py
git commit -m "feat(review-panel): config loader + profile/ad-hoc resolution"
```

---

### Task 3: Discovery of strategies, built-in reviewers, and clone personas

**Files:**
- Create: `plugins/review-panel/scripts/discovery.py`
- Test: `plugins/review-panel/tests/test_discovery.py`

**Interfaces:**
- Produces:
  - `discover_strategies(strategies_dir: Path) -> list[str]`
  - `discover_builtin_reviewers(reviewers_dir: Path) -> list[str]`
  - `discover_clone_personas() -> list[str]` (reads the review-clone root via env, see personas.py in Task 6 — but Task 3 implements a local root resolver to avoid a forward dependency; Task 6 reuses it)
  - `available_reviewers(reviewers_dir: Path) -> list[str]` → built-in names + `clone:<alias>` entries
- Consumes: nothing.

- [ ] **Step 1: Write the failing test**

`plugins/review-panel/tests/test_discovery.py`:
```python
import os
from pathlib import Path

from scripts.discovery import (
    discover_strategies, discover_builtin_reviewers,
    discover_clone_personas, available_reviewers, review_clone_root,
)


def _touch(p: Path, name: str):
    (p / name).parent.mkdir(parents=True, exist_ok=True)
    (p / name).write_text("x")


def test_discover_excludes_underscore_and_nonmd(tmp_path):
    d = tmp_path / "strategies"
    d.mkdir()
    for f in ["committee.md", "blind.md", "_template.md", "README.txt"]:
        _touch(d, f)
    assert discover_strategies(d) == ["blind", "committee"]


def test_discover_builtin_reviewers(tmp_path):
    d = tmp_path / "reviewers"
    d.mkdir()
    for f in ["general.md", "_template.md"]:
        _touch(d, f)
    assert discover_builtin_reviewers(d) == ["general"]


def test_discover_missing_dir_is_empty(tmp_path):
    assert discover_strategies(tmp_path / "absent") == []


def test_review_clone_root_prefers_env(tmp_path):
    # REVIEW_CLONE_ROOT is pinned into tmp_path by the isolation fixture.
    assert review_clone_root() == Path(os.environ["REVIEW_CLONE_ROOT"])


def test_discover_clone_personas(tmp_path):
    root = Path(os.environ["REVIEW_CLONE_ROOT"])
    for alias in ["danvk", "kentbeck"]:
        (root / alias).mkdir(parents=True)
        (root / alias / "PERSONA.md").write_text("---\n---\n")
    (root / "empty").mkdir()  # no PERSONA.md -> ignored
    assert discover_clone_personas() == ["danvk", "kentbeck"]


def test_available_reviewers_merges_sources(tmp_path):
    rd = tmp_path / "reviewers"
    rd.mkdir()
    _touch(rd, "general.md")
    root = Path(os.environ["REVIEW_CLONE_ROOT"])
    (root / "danvk").mkdir(parents=True)
    (root / "danvk" / "PERSONA.md").write_text("---\n---\n")
    assert available_reviewers(rd) == ["general", "clone:danvk"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/review-panel && .venv/bin/pytest tests/test_discovery.py -q --import-mode=importlib`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.discovery'`.

- [ ] **Step 3: Write the implementation**

`plugins/review-panel/scripts/discovery.py`:
```python
"""Discover the two reviewer sources and the strategy set from disk.

Discovery is dynamic: dropping a new `strategies/<name>.md` or
`reviewers/<name>.md` makes it available with no code change. Files whose
basename starts with '_' (e.g. _template.md) are authoring templates and
are excluded."""
from __future__ import annotations

import os
from pathlib import Path


def _stems(directory: Path) -> list[str]:
    if not Path(directory).is_dir():
        return []
    return sorted(
        p.stem for p in Path(directory).glob("*.md")
        if not p.name.startswith("_")
    )


def discover_strategies(strategies_dir: Path) -> list[str]:
    return _stems(strategies_dir)


def discover_builtin_reviewers(reviewers_dir: Path) -> list[str]:
    return _stems(reviewers_dir)


def review_clone_root() -> Path:
    """Resolve the review-clone persona root, matching review-clone's own
    resolution: REVIEW_CLONE_ROOT, else $CLAUDE_CONFIG_DIR/review-clone,
    else ~/.claude/review-clone."""
    env = os.environ.get("REVIEW_CLONE_ROOT")
    if env:
        return Path(env)
    cfg = os.environ.get("CLAUDE_CONFIG_DIR")
    if cfg:
        return Path(cfg) / "review-clone"
    return Path.home() / ".claude" / "review-clone"


def discover_clone_personas() -> list[str]:
    root = review_clone_root()
    if not root.is_dir():
        return []
    return sorted(
        p.name for p in root.iterdir()
        if p.is_dir() and (p / "PERSONA.md").exists()
    )


def available_reviewers(reviewers_dir: Path) -> list[str]:
    return discover_builtin_reviewers(reviewers_dir) + [
        f"clone:{a}" for a in discover_clone_personas()
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd plugins/review-panel && .venv/bin/pytest tests/test_discovery.py -q --import-mode=importlib`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add plugins/review-panel/scripts/discovery.py plugins/review-panel/tests/test_discovery.py
git commit -m "feat(review-panel): dynamic discovery of strategies + reviewer sources"
```

---

### Task 4: Finding contract, parsing, collation, and report rendering

**Files:**
- Create: `plugins/review-panel/scripts/contract.py`
- Test: `plugins/review-panel/tests/test_contract.py`

**Interfaces:**
- Produces:
  - `@dataclass Finding(reviewer, id, file, rule, actual, severity, category, suggestion, line: int|None=None, citation: str|None=None, verdict: str|None=None, reason: str|None=None)`
  - `class ContractError(Exception)`
  - `parse_reviewer_result(payload: dict) -> tuple[list[Finding], list[str], list[str]]` → `(findings, clean_files, notes)`
  - `collate(findings: list[Finding]) -> dict` → `{reviewer: {severity: [Finding, ...]}}`
  - `render_report(collated: dict, meta: dict) -> str`
- Consumes: nothing (pure data).

- [ ] **Step 1: Write the failing test**

`plugins/review-panel/tests/test_contract.py`:
```python
import pytest

from scripts.contract import (
    Finding, ContractError, parse_reviewer_result, collate, render_report,
)

PAYLOAD = {
    "reviewer": "general",
    "files_scanned": 2,
    "findings": [
        {"id": "GEN-001", "file": "a.py", "line": 5, "rule": "bug",
         "actual": "x=1", "severity": "error", "category": "correctness",
         "suggestion": "fix"},
        {"id": "GEN-002", "file": "b.py", "line": None, "rule": "nit",
         "actual": "y", "severity": "info", "category": "style",
         "suggestion": "tidy"},
    ],
    "clean_files": ["c.py"],
    "notes": ["skipped d.py"],
}


def test_parse_valid_payload():
    findings, clean, notes = parse_reviewer_result(PAYLOAD)
    assert [f.id for f in findings] == ["GEN-001", "GEN-002"]
    assert findings[0].reviewer == "general"
    assert clean == ["c.py"] and notes == ["skipped d.py"]


def test_parse_rejects_bad_severity():
    bad = {"reviewer": "general", "findings": [
        {"id": "X", "file": "a", "rule": "r", "actual": "a",
         "severity": "nuclear", "category": "c", "suggestion": "s"}]}
    with pytest.raises(ContractError, match="severity"):
        parse_reviewer_result(bad)


def test_parse_rejects_missing_field():
    bad = {"reviewer": "general", "findings": [{"id": "X"}]}
    with pytest.raises(ContractError, match="missing"):
        parse_reviewer_result(bad)


def test_collate_groups_by_reviewer_then_severity():
    findings, _, _ = parse_reviewer_result(PAYLOAD)
    grouped = collate(findings)
    assert grouped["general"]["error"][0].id == "GEN-001"
    assert grouped["general"]["info"][0].id == "GEN-002"


def test_render_report_includes_counts_and_ids():
    findings, _, _ = parse_reviewer_result(PAYLOAD)
    out = render_report(collate(findings), {"strategy": "committee", "scope": "changed"})
    assert "committee" in out
    assert "GEN-001" in out and "GEN-002" in out
    assert "1 error" in out and "1 info" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/review-panel && .venv/bin/pytest tests/test_contract.py -q --import-mode=importlib`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.contract'`.

- [ ] **Step 3: Write the implementation**

`plugins/review-panel/scripts/contract.py`:
```python
"""The shared finding contract every reviewer subagent returns, plus
collation and neutral-voice report rendering."""
from __future__ import annotations

from dataclasses import dataclass

VALID_SEVERITY = ("error", "warning", "info")
_REQUIRED = ("id", "file", "rule", "actual", "severity", "category", "suggestion")


class ContractError(Exception):
    """Raised when a reviewer payload violates the finding contract."""


@dataclass
class Finding:
    reviewer: str
    id: str
    file: str
    rule: str
    actual: str
    severity: str
    category: str
    suggestion: str
    line: int | None = None
    citation: str | None = None
    verdict: str | None = None
    reason: str | None = None


def parse_reviewer_result(payload: dict) -> tuple[list[Finding], list[str], list[str]]:
    reviewer = payload.get("reviewer")
    if not reviewer:
        raise ContractError("payload missing 'reviewer'")
    findings: list[Finding] = []
    for raw in payload.get("findings", []) or []:
        missing = [k for k in _REQUIRED if k not in raw]
        if missing:
            raise ContractError(f"finding missing {missing} in {raw!r}")
        if raw["severity"] not in VALID_SEVERITY:
            raise ContractError(
                f"invalid severity {raw['severity']!r}; expected {VALID_SEVERITY}"
            )
        findings.append(Finding(
            reviewer=reviewer,
            id=raw["id"], file=raw["file"], rule=raw["rule"],
            actual=raw["actual"], severity=raw["severity"],
            category=raw["category"], suggestion=raw["suggestion"],
            line=raw.get("line"), citation=raw.get("citation"),
            verdict=raw.get("verdict"), reason=raw.get("reason"),
        ))
    clean = list(payload.get("clean_files", []) or [])
    notes = list(payload.get("notes", []) or [])
    return findings, clean, notes


def collate(findings: list[Finding]) -> dict:
    grouped: dict[str, dict[str, list[Finding]]] = {}
    for f in findings:
        grouped.setdefault(f.reviewer, {s: [] for s in VALID_SEVERITY})
        grouped[f.reviewer][f.severity].append(f)
    return grouped


def _counts(findings: list[Finding]) -> str:
    tally = {s: 0 for s in VALID_SEVERITY}
    for f in findings:
        tally[f.severity] += 1
    parts = [f"{tally[s]} {s}" for s in VALID_SEVERITY if tally[s]]
    return ", ".join(parts) if parts else "no findings"


def render_report(collated: dict, meta: dict) -> str:
    all_findings = [f for revs in collated.values() for fs in revs.values() for f in fs]
    lines = [
        "# review-panel",
        "",
        f"Strategy: **{meta.get('strategy','?')}** · Scope: **{meta.get('scope','?')}** · "
        f"{_counts(all_findings)}",
        "",
    ]
    for reviewer, by_sev in collated.items():
        rev_findings = [f for fs in by_sev.values() for f in fs]
        lines.append(f"## {reviewer} — {_counts(rev_findings)}")
        for sev in VALID_SEVERITY:
            for f in by_sev[sev]:
                loc = f"{f.file}:{f.line}" if f.line is not None else f.file
                verdict = f" _({f.verdict})_" if f.verdict else ""
                lines.append(f"- **[{f.id}] {sev}**{verdict} — {f.rule} — `{loc}`")
                lines.append(f"  - found: `{f.actual}`")
                lines.append(f"  - fix: {f.suggestion}")
                if f.citation:
                    lines.append(f"  - citation: {f.citation}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd plugins/review-panel && .venv/bin/pytest tests/test_contract.py -q --import-mode=importlib`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add plugins/review-panel/scripts/contract.py plugins/review-panel/tests/test_contract.py
git commit -m "feat(review-panel): finding contract, collation, report rendering"
```

---

### Task 5: Strictness application + decisions.yml overrides

**Files:**
- Create: `plugins/review-panel/scripts/strictness.py`
- Test: `plugins/review-panel/tests/test_strictness.py`

**Interfaces:**
- Produces:
  - `apply_strictness(findings: list[Finding], strictness_by_reviewer: dict[str,str], allowed_exceptions: dict[str,set[str]] | None = None) -> list[Finding]`
  - `load_decisions(path: Path) -> dict`
  - `apply_decisions(findings: list[Finding], decisions: dict) -> list[Finding]`
- Consumes: `Finding` from `scripts.contract` (Task 4).

Strictness rules (from spec): `strict` → keep severities; `aspirational` → every finding becomes `warning`; `pragmatic` → a finding whose `id` is in that reviewer's `allowed_exceptions` becomes `warning`, others unchanged. `decisions.yml` overrides a finding's severity by `id` and attaches a reason.

- [ ] **Step 1: Write the failing test**

`plugins/review-panel/tests/test_strictness.py`:
```python
import textwrap
from pathlib import Path

from scripts.contract import Finding
from scripts.strictness import apply_strictness, load_decisions, apply_decisions


def _f(id_, reviewer="general", severity="error"):
    return Finding(reviewer=reviewer, id=id_, file="a.py", rule="r",
                   actual="x", severity=severity, category="c", suggestion="s")


def test_strict_keeps_severity():
    out = apply_strictness([_f("G1")], {"general": "strict"})
    assert out[0].severity == "error"


def test_aspirational_downgrades_everything():
    out = apply_strictness([_f("G1"), _f("G2", severity="info")], {"general": "aspirational"})
    assert [f.severity for f in out] == ["warning", "warning"]


def test_pragmatic_downgrades_only_allowed_exceptions():
    out = apply_strictness(
        [_f("G1"), _f("G2")],
        {"general": "pragmatic"},
        allowed_exceptions={"general": {"G2"}},
    )
    sev = {f.id: f.severity for f in out}
    assert sev == {"G1": "error", "G2": "warning"}


def test_default_strictness_is_pragmatic():
    out = apply_strictness([_f("G1")], {})  # missing reviewer -> pragmatic
    assert out[0].severity == "error"


def test_decisions_override_by_id(tmp_path):
    p = tmp_path / "decisions.yml"
    p.write_text(textwrap.dedent("""
        overrides:
          G1: { severity: info, reason: "team decision" }
    """))
    decisions = load_decisions(p)
    out = apply_decisions([_f("G1"), _f("G2")], decisions)
    by_id = {f.id: f for f in out}
    assert by_id["G1"].severity == "info"
    assert by_id["G1"].reason == "team decision"
    assert by_id["G2"].severity == "error"


def test_load_decisions_missing_is_empty(tmp_path):
    assert load_decisions(tmp_path / "absent.yml") == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/review-panel && .venv/bin/pytest tests/test_strictness.py -q --import-mode=importlib`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.strictness'`.

- [ ] **Step 3: Write the implementation**

`plugins/review-panel/scripts/strictness.py`:
```python
"""Apply per-reviewer strictness and decisions.yml overrides to findings."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import yaml

from scripts.contract import Finding

_DEFAULT = "pragmatic"


def apply_strictness(
    findings: list[Finding],
    strictness_by_reviewer: dict[str, str],
    allowed_exceptions: dict[str, set[str]] | None = None,
) -> list[Finding]:
    exceptions = allowed_exceptions or {}
    out: list[Finding] = []
    for f in findings:
        level = strictness_by_reviewer.get(f.reviewer, _DEFAULT)
        if level == "aspirational":
            out.append(replace(f, severity="warning"))
        elif level == "pragmatic" and f.id in exceptions.get(f.reviewer, set()):
            out.append(replace(f, severity="warning"))
        else:  # strict, or pragmatic non-exception
            out.append(f)
    return out


def load_decisions(path: Path) -> dict:
    if not Path(path).exists():
        return {}
    data = yaml.safe_load(Path(path).read_text()) or {}
    return data if isinstance(data, dict) else {}


def apply_decisions(findings: list[Finding], decisions: dict) -> list[Finding]:
    overrides = (decisions or {}).get("overrides", {}) or {}
    out: list[Finding] = []
    for f in findings:
        ov = overrides.get(f.id)
        if ov:
            out.append(replace(
                f,
                severity=ov.get("severity", f.severity),
                reason=ov.get("reason", f.reason),
            ))
        else:
            out.append(f)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd plugins/review-panel && .venv/bin/pytest tests/test_strictness.py -q --import-mode=importlib`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add plugins/review-panel/scripts/strictness.py plugins/review-panel/tests/test_strictness.py
git commit -m "feat(review-panel): strictness levels + decisions.yml overrides"
```

---

### Task 6: Clone-persona reader (adapter data layer)

**Files:**
- Create: `plugins/review-panel/scripts/personas.py`
- Test: `plugins/review-panel/tests/test_personas.py`

**Interfaces:**
- Produces:
  - `@dataclass Persona(alias: str, frontmatter: dict, body: str)`
  - `persona_path(alias: str) -> Path`
  - `read_persona(alias: str) -> Persona | None` (None if the PERSONA.md is absent — the orchestrator warns and skips)
- Consumes: `review_clone_root` from `scripts.discovery` (Task 3).

- [ ] **Step 1: Write the failing test**

`plugins/review-panel/tests/test_personas.py`:
```python
import os
from pathlib import Path

from scripts.personas import Persona, persona_path, read_persona


def _persona(alias: str, text: str):
    root = Path(os.environ["REVIEW_CLONE_ROOT"])
    (root / alias).mkdir(parents=True, exist_ok=True)
    (root / alias / "PERSONA.md").write_text(text)


def test_persona_path_under_root():
    p = persona_path("danvk")
    assert p == Path(os.environ["REVIEW_CLONE_ROOT"]) / "danvk" / "PERSONA.md"


def test_read_missing_persona_returns_none():
    assert read_persona("ghost") is None


def test_read_persona_splits_frontmatter_and_body():
    _persona("danvk", "---\nalias: danvk\nrules: 12\n---\n## Rules\n- prefer X\n")
    p = read_persona("danvk")
    assert isinstance(p, Persona)
    assert p.alias == "danvk"
    assert p.frontmatter["rules"] == 12
    assert "prefer X" in p.body


def test_read_persona_without_frontmatter_is_all_body():
    _persona("plain", "## Rules\n- do the thing\n")
    p = read_persona("plain")
    assert p.frontmatter == {}
    assert "do the thing" in p.body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/review-panel && .venv/bin/pytest tests/test_personas.py -q --import-mode=importlib`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.personas'`.

- [ ] **Step 3: Write the implementation**

`plugins/review-panel/scripts/personas.py`:
```python
"""Read a review-clone persona so the orchestrator can seat it as a
reviewer. This layer only READS persona files — it never scrapes GitHub or
refreshes them (that stays review-clone's job)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from scripts.discovery import review_clone_root

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)


@dataclass
class Persona:
    alias: str
    frontmatter: dict
    body: str


def persona_path(alias: str) -> Path:
    return review_clone_root() / alias / "PERSONA.md"


def read_persona(alias: str) -> Persona | None:
    path = persona_path(alias)
    if not path.exists():
        return None
    text = path.read_text()
    match = _FRONTMATTER_RE.match(text)
    if match:
        front = yaml.safe_load(match.group(1)) or {}
        body = match.group(2)
    else:
        front, body = {}, text
    return Persona(alias=alias, frontmatter=front if isinstance(front, dict) else {}, body=body)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd plugins/review-panel && .venv/bin/pytest tests/test_personas.py -q --import-mode=importlib`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add plugins/review-panel/scripts/personas.py plugins/review-panel/tests/test_personas.py
git commit -m "feat(review-panel): clone-persona reader for the reviewer adapter"
```

---

### Task 7: Strategy files + doclint

**Files:**
- Create: `plugins/review-panel/skills/strategies/_template.md`
- Create: `plugins/review-panel/skills/strategies/{committee,blind,informed,adversarial,dual-tiebreaker}.md`
- Create: `plugins/review-panel/scripts/doclint.py`
- Test: `plugins/review-panel/tests/test_docs.py`

**Interfaces:**
- Produces: `required_sections(kind: str) -> list[str]` and `lint_doc(path: Path, kind: str) -> list[str]` (returns a list of missing-section error strings; empty = clean) in `doclint.py`.
- Consumes: `discover_strategies` from Task 3.

Each strategy file MUST contain these `##` sections: `Summary`, `When to use`, `Context handling`, `Stages`, `Reconciliation`, `Cost`.

- [ ] **Step 1: Write the failing test**

`plugins/review-panel/tests/test_docs.py`:
```python
from pathlib import Path

from scripts.discovery import discover_strategies
from scripts.doclint import required_sections, lint_doc

PLUGIN = Path(__file__).resolve().parents[1]
STRATEGIES = PLUGIN / "skills" / "strategies"


def test_five_strategies_present():
    assert discover_strategies(STRATEGIES) == [
        "adversarial", "blind", "committee", "dual-tiebreaker", "informed",
    ]


def test_every_strategy_has_required_sections():
    problems = []
    for name in discover_strategies(STRATEGIES):
        problems += lint_doc(STRATEGIES / f"{name}.md", "strategy")
    assert problems == [], problems


def test_required_sections_known_kind():
    assert "Stages" in required_sections("strategy")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/review-panel && .venv/bin/pytest tests/test_docs.py -q --import-mode=importlib`
Expected: FAIL (`ModuleNotFoundError: scripts.doclint`, and the strategy files do not exist yet).

- [ ] **Step 3: Write doclint**

`plugins/review-panel/scripts/doclint.py`:
```python
"""Structural lint for reviewer/strategy markdown: verify required '##'
sections are present so a dropped-in lens/strategy is well-formed."""
from __future__ import annotations

import re
from pathlib import Path

_SECTIONS = {
    "strategy": ["Summary", "When to use", "Context handling", "Stages",
                 "Reconciliation", "Cost"],
    "reviewer": ["Concern", "When to seat", "Techniques", "What to look for",
                 "Severity", "Voice", "Allowed exceptions"],
}


def required_sections(kind: str) -> list[str]:
    return list(_SECTIONS[kind])


def lint_doc(path: Path, kind: str) -> list[str]:
    if not Path(path).exists():
        return [f"{path}: file missing"]
    text = Path(path).read_text()
    headings = set(re.findall(r"^##\s+(.+?)\s*$", text, re.MULTILINE))
    problems = []
    for want in required_sections(kind):
        if not any(h.startswith(want) for h in headings):
            problems.append(f"{path.name}: missing '## {want}' section")
    return problems
```

- [ ] **Step 4: Write the strategy template**

`plugins/review-panel/skills/strategies/_template.md`:
```markdown
# <Strategy Name> Strategy

## Summary
One line: what this orchestration pattern does.

## When to use
Risk level and change type this suits; when NOT to use it.

## Context handling
What context each reviewer subagent receives (diff only vs diff + spec/arch).

## Stages
Ordered dispatch. For each stage: the subagent role, its inputs, and its
output. All subagents run with `model: sonnet`.

## Reconciliation
How findings are merged / confirmed / dropped into the final set.

## Cost
Relative speed/expense vs committee.
```

- [ ] **Step 5: Write the five strategy files**

`plugins/review-panel/skills/strategies/committee.md`:
```markdown
# Committee Strategy

## Summary
Every seated reviewer examines the same change in parallel; the orchestrator
merges their structured findings. The default, and the strongest pattern for
quality.

## When to use
General-purpose reviews. The default when a profile names no other strategy.

## Context handling
Informed by default: each reviewer receives the diff plus the file at HEAD
for context. No spec/architecture unless the profile sets `context:`.

## Stages
1. **Reviewers (parallel).** One subagent per seated reviewer, `model: sonnet`.
   Input: the in-scope diff + changed files at HEAD (+ any `context:` files).
   Output: the finding contract JSON.

## Reconciliation
None beyond collation: all findings are kept and grouped by reviewer →
severity. Strictness and decisions overrides are then applied.

## Cost
Baseline. N reviewers ≈ N parallel subagents, one pass.
```

`plugins/review-panel/skills/strategies/blind.md`:
```markdown
# Blind Strategy

## Summary
Committee, but each reviewer sees only the diff and the acceptance criteria —
no author rationale, no surrounding architecture — to reduce bias.

## When to use
High-volume or low-risk changes; maker-checker flows where independence
matters more than design-context depth.

## Context handling
Blind: reviewer subagents receive ONLY the unified diff and the acceptance
criteria (PR body or `context: [criteria]`). Do NOT pass whole files at HEAD,
spec, or architecture notes.

## Stages
1. **Reviewers (parallel).** One subagent per seated reviewer, `model: sonnet`,
   prompted with diff + acceptance criteria only. Output: the finding contract.

## Reconciliation
Same as committee: collate, then apply strictness/decisions.

## Cost
Baseline; often faster because less context is loaded per reviewer.
```

`plugins/review-panel/skills/strategies/informed.md`:
```markdown
# Informed Strategy

## Summary
Committee enriched with design context — spec, architecture notes, intent —
so reviewers judge design-heavy changes accurately.

## When to use
Complex or design-heavy changes where correctness depends on intent the diff
alone doesn't carry.

## Context handling
Informed: each reviewer receives the diff, changed files at HEAD, AND every
file listed in the profile's `context:` (e.g. docs/spec.md). Summarise long
context files before dispatch to stay within budget.

## Stages
1. **Reviewers (parallel).** One subagent per seated reviewer, `model: sonnet`,
   prompted with diff + HEAD files + context files. Output: finding contract.

## Reconciliation
Same as committee: collate, then apply strictness/decisions.

## Cost
Higher than committee: more context tokens per reviewer.
```

`plugins/review-panel/skills/strategies/adversarial.md`:
```markdown
# Adversarial Strategy

## Summary
Reviewers find issues; a critic subagent tries to refute each finding; a judge
keeps only what survives. Catches plausible-but-wrong findings.

## When to use
High-risk changes: security, auth, payments, large refactors.

## Context handling
Informed (as committee). The critic additionally receives the diff so it can
check each finding against reality.

## Stages
1. **Reviewers (parallel).** As committee. Output: candidate findings.
2. **Critic (per finding).** One `model: sonnet` subagent per finding,
   prompted to REFUTE it (default to refuted when uncertain). Output:
   `{verdict: confirmed|refuted|weakened, reason}`.
3. **Judge.** Attach each verdict+reason to its finding.

## Reconciliation
Drop `refuted` findings; downgrade `weakened` findings one severity step;
keep `confirmed`. Then collate and apply strictness/decisions.

## Cost
Highest: N reviewers + one critic per candidate finding.
```

`plugins/review-panel/skills/strategies/dual-tiebreaker.md`:
```markdown
# Dual-Tiebreaker Strategy

## Summary
Two independent committee passes review the change; an arbiter resolves
disagreements. Robust through independent checks.

## When to use
Medium-to-high risk changes where a single pass may miss or over-call.

## Context handling
Informed (as committee). Both passes get identical context; keep them
independent (do not let pass B see pass A's findings).

## Stages
1. **Pass A (parallel).** The seated reviewers. Output: finding set A.
2. **Pass B (parallel).** The same reviewers again, independently. Output: set B.
3. **Arbiter.** A `model: sonnet` subagent compares A and B keyed by
   (file, line, category). Output per finding: `{verdict: confirmed|refuted,
   reason}` — confirmed when both passes agree or the arbiter upholds a
   single-pass finding.

## Reconciliation
Keep `confirmed`; drop `refuted`. Deduplicate agreed findings. Then collate
and apply strictness/decisions.

## Cost
~2× committee plus one arbiter pass.
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd plugins/review-panel && .venv/bin/pytest tests/test_docs.py -q --import-mode=importlib`
Expected: PASS (3 passed).

- [ ] **Step 7: Commit**

```bash
git add plugins/review-panel/skills/strategies plugins/review-panel/scripts/doclint.py \
  plugins/review-panel/tests/test_docs.py
git commit -m "feat(review-panel): five strategy recipes + structural doclint"
```

---

### Task 8: The `general` reviewer + reviewer template

**Files:**
- Create: `plugins/review-panel/skills/reviewers/_template.md`
- Create: `plugins/review-panel/skills/reviewers/general.md`
- Modify: `plugins/review-panel/tests/test_docs.py` (add reviewer lint)

**Interfaces:**
- Consumes: `discover_builtin_reviewers`, `lint_doc` (Tasks 3, 7).

- [ ] **Step 1: Extend the failing test**

Append to `plugins/review-panel/tests/test_docs.py`:
```python
REVIEWERS = PLUGIN / "skills" / "reviewers"


def test_general_reviewer_present():
    assert discover_builtin_reviewers(REVIEWERS) == ["general"]


def test_general_reviewer_has_required_sections():
    assert lint_doc(REVIEWERS / "general.md", "reviewer") == []
```

Add the import at the top of the file:
```python
from scripts.discovery import discover_builtin_reviewers
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/review-panel && .venv/bin/pytest tests/test_docs.py -q --import-mode=importlib`
Expected: FAIL (reviewer files do not exist yet).

- [ ] **Step 3: Write the reviewer template**

`plugins/review-panel/skills/reviewers/_template.md`:
```markdown
# <Reviewer Name>

## Concern
One paragraph: what this reviewer cares about.

## When to seat
Which changes this reviewer adds value to; when to leave it off.

## Techniques
Which review techniques it employs (data-flow, control-flow, change-impact,
checklist, test-driven, top-down, bottom-up, trace-based, use-case-driven,
cross-referencing).

## What to look for
| ID | category | rule | default severity | what to scan for |
|----|----------|------|------------------|------------------|
| XXX-001 | category | one-line rule | error/warning/info | the pattern to detect |

## Severity
How this reviewer grades error vs warning vs info.

## Voice
Tone. Default: neutral, professional, direct. No persona flavour.

## Allowed exceptions
Finding ids (or patterns) this reviewer lets go under `pragmatic` strictness.
```

- [ ] **Step 4: Write the general reviewer**

`plugins/review-panel/skills/reviewers/general.md`:
```markdown
# General

## Concern
A broad, single-pass reviewer with a generalist rubric. It catches the
issues any competent engineer would flag on a first read: obvious
correctness bugs, unclear or misleading code, glaring security or
performance problems, and missing tests for changed behaviour. It is the
default reviewer and the catch-all lens when no specialist is seated.

## When to seat
Always safe to seat. Ideal for small-to-medium changes, or as the single
reviewer in a quick pass. For high-risk or specialised changes, add
specialist reviewers alongside it (Epic 2).

## Techniques
Checklist (the rubric below), control-flow (trace the changed paths),
change-impact (what else this diff touches), test-driven (are the new
paths tested?).

## What to look for
| ID | category | rule | default severity | what to scan for |
|----|----------|------|------------------|------------------|
| GEN-001 | correctness | Logic error or wrong result on a changed path | error | off-by-one, inverted conditions, wrong operator, unhandled branch |
| GEN-002 | correctness | Unhandled None/empty/error case | error | value used without a null/empty guard; ignored error return |
| GEN-003 | correctness | Edge case in new behaviour is unhandled | warning | boundaries: empty input, zero, max, concurrent, retry |
| GEN-004 | security | Untrusted input reaches a dangerous sink | error | user input into SQL/shell/eval/path without validation |
| GEN-005 | security | Secret or credential committed | error | literal tokens, keys, passwords in the diff |
| GEN-006 | performance | Obvious hot-path inefficiency | warning | N+1 I/O in a loop, needless O(n^2), repeated recompute |
| GEN-007 | clarity | Misleading name or unclear intent | warning | name contradicts behaviour; magic number without meaning |
| GEN-008 | clarity | Dead or unreachable code introduced | info | code after return; unused new symbol |
| GEN-009 | tests | Changed behaviour has no test | warning | new branch/function with no covering test in the diff |
| GEN-010 | tests | Test asserts nothing meaningful | info | test with no assertion, or asserting a tautology |

## Severity
`error` — will produce a wrong result, a vulnerability, or data loss.
`warning` — likely defect, missing test, or real maintainability cost.
`info` — worth noting; safe to defer.

## Voice
Neutral, professional, direct. State the problem, the location, and the fix.
No praise sandwiching; no persona flavour.

## Allowed exceptions
- `GEN-008`, `GEN-010` — under `pragmatic` strictness these drop to warnings
  (info already), i.e. never block.
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd plugins/review-panel && .venv/bin/pytest tests/test_docs.py -q --import-mode=importlib`
Expected: PASS (5 passed).

- [ ] **Step 6: Commit**

```bash
git add plugins/review-panel/skills/reviewers plugins/review-panel/tests/test_docs.py
git commit -m "feat(review-panel): general reviewer + reviewer authoring template"
```

---

### Task 9: Shipped default config + slash command

**Files:**
- Create: `plugins/review-panel/templates/config.yml`
- Create: `plugins/review-panel/commands/review-panel.md`
- Test: `plugins/review-panel/tests/test_docs.py` (add: shipped config resolves)

**Interfaces:**
- Consumes: `load_config`, `resolve_profile` (Task 2).

The shipped config seeds a target repo's `.review-panel/config.yml`. Every shipped profile must resolve without error, and profiles that name `clone:<alias>` must NOT appear in the shipped defaults (a fresh repo has no personas) — personas are opt-in via the docs example.

- [ ] **Step 1: Write the failing test**

Append to `plugins/review-panel/tests/test_docs.py`:
```python
from scripts.config import load_config, resolve_profile

SHIPPED_CONFIG = PLUGIN / "templates" / "config.yml"


def test_shipped_profiles_all_resolve():
    cfg = load_config(SHIPPED_CONFIG)
    profiles = cfg["profiles"]
    assert "pre-merge" in profiles
    for name in profiles:
        r = resolve_profile(cfg, name)
        assert r.reviewers  # non-empty
        assert r.strategy in {
            "committee", "blind", "informed", "adversarial", "dual-tiebreaker"}


def test_shipped_default_profile_is_set():
    cfg = load_config(SHIPPED_CONFIG)
    # resolve_profile(None) must work -> defaults.profile present
    assert resolve_profile(cfg, None).reviewers
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/review-panel && .venv/bin/pytest tests/test_docs.py -q --import-mode=importlib`
Expected: FAIL (shipped config missing).

- [ ] **Step 3: Write the shipped default config**

`plugins/review-panel/templates/config.yml`:
```yaml
# .review-panel/config.yml — copy into your repo root and edit.
# Reviewer keys are a built-in name (e.g. general) or clone:<alias> for a
# review-clone persona. Strictness: strict | pragmatic | aspirational.
defaults:
  strategy: committee
  scope: changed
  profile: pre-merge

profiles:
  pre-merge:
    strategy: committee
    scope: changed
    reviewers: { general: pragmatic }

  quick-pass:
    strategy: blind
    reviewers: { general: aspirational }

  high-risk:
    strategy: adversarial
    reviewers: { general: strict }

  design-heavy:
    strategy: informed
    context: []          # add spec/arch paths, e.g. [docs/spec.md]
    reviewers: { general: pragmatic }

output:
  default: report        # report | inline | interactive
  file: .review-panel/last-review.md
```

- [ ] **Step 4: Write the slash command**

`plugins/review-panel/commands/review-panel.md`:
```markdown
---
description: Run a composable code review — pick a profile (strategy × reviewers) or name reviewers ad-hoc. Args: [profile] [full|interactive|inline] | <reviewer…> | reviewers | strategies
---

Invoke the review-panel orchestrator (`skills/convene/SKILL.md`) with
`$ARGUMENTS`. Resolve arguments as follows:

- empty → the default profile from `.review-panel/config.yml`.
- a known profile name → that profile; a trailing `full` overrides scope to
  the whole repo; a trailing `interactive` or `inline` overrides output.
- one or more known reviewer names (built-in or `clone:<alias>`) → an ad-hoc
  committee over changed files.
- `reviewers` → list available reviewers (built-in + clone personas).
- `strategies` → list available strategies.

Follow the workflow in `skills/convene/SKILL.md` exactly.
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd plugins/review-panel && .venv/bin/pytest tests/test_docs.py -q --import-mode=importlib`
Expected: PASS (7 passed).

- [ ] **Step 6: Commit**

```bash
git add plugins/review-panel/templates/config.yml plugins/review-panel/commands/review-panel.md \
  plugins/review-panel/tests/test_docs.py
git commit -m "feat(review-panel): shipped default config + /review-panel command"
```

---

### Task 10: Orchestrator SKILL.md + end-to-end smoke test

**Files:**
- Create: `plugins/review-panel/skills/convene/SKILL.md`
- Replace: `plugins/review-panel/tests/test_smoke.py` (real pipeline smoke over the Python layer with a mocked reviewer payload)

**Interfaces:**
- Consumes: everything from Tasks 2–6 (`config`, `discovery`, `contract`, `strictness`, `personas`).
- Produces: the executable prose the `/review-panel` command follows.

The SKILL.md owns all live behaviour (git scope, subagent dispatch, gh posting) — not unit-testable here. The smoke test proves the deterministic pipeline the SKILL leans on (resolve → collate → strictness → decisions → render) works on a fixture, using a mocked reviewer result in place of a live subagent.

- [ ] **Step 1: Write the failing smoke test**

`plugins/review-panel/tests/test_smoke.py` (overwrite the Task 1 stub):
```python
"""End-to-end smoke over the deterministic pipeline the orchestrator uses:
resolve a profile -> parse a (mocked) reviewer result -> strictness ->
decisions -> collate -> render. No live subagent, no git, no gh."""
import textwrap
from pathlib import Path

from scripts.config import load_config, resolve_profile
from scripts.contract import parse_reviewer_result, collate, render_report
from scripts.strictness import apply_strictness, apply_decisions


def test_pipeline_produces_report(tmp_path):
    cfg_path = tmp_path / "config.yml"
    cfg_path.write_text(textwrap.dedent("""
        defaults: { strategy: committee, scope: changed, profile: pre-merge }
        profiles:
          pre-merge: { reviewers: { general: strict } }
        output: { default: report }
    """))
    resolved = resolve_profile(load_config(cfg_path), None)
    assert resolved.strategy == "committee"

    # A reviewer subagent would return this; here we mock it.
    mocked = {
        "reviewer": "general",
        "findings": [
            {"id": "GEN-001", "file": "app.py", "line": 12, "rule": "null deref",
             "actual": "user.name", "severity": "error", "category": "correctness",
             "suggestion": "guard user"},
        ],
        "clean_files": ["util.py"],
        "notes": [],
    }
    findings, _clean, _notes = parse_reviewer_result(mocked)

    strictness = {r.name: r.strictness for r in resolved.reviewers}
    findings = apply_strictness(findings, strictness)
    findings = apply_decisions(findings, {})
    report = render_report(collate(findings), {"strategy": resolved.strategy, "scope": resolved.scope})

    assert "GEN-001" in report
    assert "1 error" in report
    assert "committee" in report


def test_full_suite_importable():
    import scripts.config, scripts.discovery, scripts.contract  # noqa: F401
    import scripts.strictness, scripts.personas, scripts.doclint  # noqa: F401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/review-panel && .venv/bin/pytest tests/test_smoke.py -q --import-mode=importlib`
Expected: PASS for the pipeline test is possible already (Tasks 2–5 exist), but the SKILL.md does not yet exist. Confirm the pipeline test passes; the SKILL.md is authored in Step 3 and validated by the full run in Step 4.

- [ ] **Step 3: Write the orchestrator SKILL.md**

`plugins/review-panel/skills/convene/SKILL.md`:
````markdown
---
name: convene
description: Use when the user asks to review code, review a diff, review changes, or run a code review — "/review-panel", "review my changes", "code review this", "run a review panel". Composes reviewer lenses × a strategy over a diff.
---

# review-panel — convene the panel

Run a composable code review. A review = a **strategy** (how to orchestrate)
× a set of **reviewers** (what to examine), resolved from a **profile** in
`.review-panel/config.yml`. Neutral voice throughout.

The deterministic pieces live in `../../scripts/` (config resolution,
discovery, finding contract, strictness, persona reading). Run them with the
plugin venv: `plugins/review-panel/.venv/bin/python`. This SKILL owns the
parts that need git, a live model, or `gh`.

## Step 0 — Parse arguments

`$ARGUMENTS` may be: empty · a profile name · a profile + `full`/`interactive`/
`inline` · one or more reviewer keys · `reviewers` · `strategies`.

- `reviewers` → print `available_reviewers()` (built-in + `clone:<alias>`) and stop.
- `strategies` → print `discover_strategies()` and stop.

## Step 1 — Resolve the review

Load `.review-panel/config.yml`. If it is missing, offer to seed it from
`templates/config.yml`, then stop.

- Profile form → `resolve_profile(config, <name or None>)`.
- Ad-hoc reviewer form → `resolve_adhoc(config, [<keys>])`.

A trailing `full` sets scope to `full`; `interactive`/`inline` overrides the
output mode. You now have a `ResolvedReview`: strategy, scope, targets,
reviewers, context, output.

## Step 2 — Determine scope (the diff)

- `changed` → `git fetch -q origin <base> || true` then
  `git diff --name-only $(git merge-base HEAD <base>) HEAD`, where `<base>`
  is the repo's default branch (`main` unless told otherwise). Filter to the
  profile's `targets` globs if set.
- `full` → all files matching `targets` (or the repo default).

**Pre-flight size check:** if scope > ~100 files, warn and ask whether to
proceed, narrow to directories, or switch to changed-files.

## Step 3 — Load the strategy recipe

Read `../strategies/<strategy>.md`. Follow its **Context handling**,
**Stages**, and **Reconciliation** sections literally. Every subagent you
dispatch uses `model: sonnet` (never Fable).

## Step 4 — Seat the reviewers

For each `ReviewerRef`:
- `builtin` → read `../reviewers/<name>.md`; its "What to look for" table is
  the rule set, its "Voice" drives tone.
- `clone` → `read_persona(<alias>)`. If it returns null, warn
  "persona <alias> not found — skipping" and continue. Otherwise use the
  persona body's rules + voice, and carry over review-clone's gates:
  **symbol/API reality check** (skip a rule whose symbol is absent from the
  target repo — confirm with Grep), **cite-or-refuse** (every finding cites a
  real persona comment URL, else drop), and the persona's **"what they let
  go"** list.

Dispatch per the strategy's stages. Each reviewer subagent returns the
finding contract JSON (see `../../scripts/contract.py`): `reviewer`,
`findings[]` with `id,file,line,rule,actual,severity,category,suggestion`
(+ `citation` for clone reviewers), `clean_files`, `notes`. Clone findings
use id `CLONE-<alias>-NNN`; built-in findings use the reviewer's prefix.

## Step 5 — Reconcile, strictness, decisions

Apply the strategy's reconciliation (adversarial critic/judge,
dual-tiebreaker arbiter — these annotate each finding with a `verdict`; drop
`refuted`, downgrade `weakened`). Then apply `apply_strictness(...)` using
each reviewer's strictness and its "Allowed exceptions", and
`apply_decisions(...)` from `.review-panel/decisions.yml` if present.

## Step 6 — Output

- **report** (default) → `render_report(collate(findings), meta)`; print to
  chat and write to `output.file` (default `.review-panel/last-review.md`).
- **interactive** → walk findings one at a time: fix / explain / skip /
  accept-exception (accept writes an override into `.review-panel/decisions.yml`).
- **inline** → confirmation-gated. Resolve the open PR
  (`gh pr view --json number`). If none, fall back to report. Preview the
  count, wait for an explicit yes, then post one batched review via
  `gh api repos/<owner>/<repo>/pulls/<n>/reviews` — anchorable findings as
  inline comments, the rest bundled into the review summary. Never auto-post.

## When NOT to use
- Auditing architecture against doctrine → puritan `/puritan:inquisition`.
- Triaging existing PR comments → tribunal `/tribunal:reckoning`.
- Cloning a specific reviewer from GitHub history → review-clone.
````

- [ ] **Step 4: Run the full suite**

Run: `cd plugins/review-panel && .venv/bin/pytest tests -q --import-mode=importlib`
Expected: PASS (all tests across the suite green).

- [ ] **Step 5: Commit**

```bash
git add plugins/review-panel/skills/convene/SKILL.md plugins/review-panel/tests/test_smoke.py
git commit -m "feat(review-panel): orchestrator SKILL + end-to-end pipeline smoke"
```

---

### Task 11: Live end-to-end verification on a real diff

**Files:** none created — this is a manual verification gate that proves the
whole engine runs outside the unit tests.

- [ ] **Step 1: Make a tiny fixture change**

On a scratch branch in this repo, introduce an obvious bug (e.g. a Python
function that dereferences a possibly-None value) so there is a real diff to
review.

- [ ] **Step 2: Seed config and run committee**

```bash
mkdir -p .review-panel && cp plugins/review-panel/templates/config.yml .review-panel/config.yml
/review-panel pre-merge
```
Expected: the `general` reviewer runs under `committee`, a collated report
prints, and `.review-panel/last-review.md` is written naming the bug (GEN-002).

- [ ] **Step 3: Exercise the other strategies and output modes**

Run each and confirm it completes end-to-end:
```bash
/review-panel high-risk          # adversarial: critic/judge stage runs
/review-panel quick-pass         # blind: reviewer sees diff only
/review-panel pre-merge interactive   # walk findings
```
If a review-clone persona exists locally, add `clone:<alias>` to a profile and
confirm it is seated and produces cited findings; if none exists, confirm the
"persona not found — skipping" path.

- [ ] **Step 4: Record the result on the board**

```bash
.venv/bin/python plugins/overseer/scripts/cli.py --root . log-progress WF-093 \
  --note "Epic 1 engine verified end-to-end: 5 strategies × general reviewer, report/interactive/inline."
```

- [ ] **Step 5: Discard the fixture change**

Remove the scratch bug (do not commit it). Use the Edit tool to revert the
fixture, or delete the scratch branch — never `git checkout <file>` on
tracked working files without permission.

---

## Self-Review

**Spec coverage (§ by §):**
- §2 concepts (reviewer/strategy/profile/scope/strictness) → Tasks 2, 7, 8.
- §3 strategies (5) → Task 7.
- §4 `general` starter reviewer → Task 8.
- §5 config (defaults/profiles/context/output) → Tasks 2, 9.
- §6 invocation (profile/full/interactive/inline/ad-hoc/reviewers/strategies) → Tasks 9, 10.
- §7 finding contract → Task 4; §7a clone adapter (read + gates) → Tasks 6, 10.
- §8 output modes (report/interactive/inline) → Tasks 4, 10.
- §9 directory structure → all tasks; §10 portability (env resolution, neutral voice) → Tasks 3, 6, Global Constraints.
- §11 error handling (missing config/reviewer/persona, no PR) → Tasks 9, 10.
- Deferred by spec (§12): self-review-loop strategy, specialist reviewers, CI wiring, cross-model dual — correctly absent.

**Placeholder scan:** no TBD/TODO; every code and file step carries literal content.

**Type consistency:** `ReviewerRef(key,source,name,strictness)` and
`ResolvedReview(strategy,scope,targets,reviewers,context,output)` are used
identically in Tasks 2, 9, 10. `Finding(...)` fields match across Tasks 4, 5,
10. `review_clone_root()` defined in Task 3, reused in Task 6. `lint_doc`,
`required_sections`, `discover_*` signatures consistent across Tasks 3, 7, 8.

**Note on `pragmatic` allowed-exceptions:** the mechanism is implemented in
Task 5 and exercised by tests; wiring each reviewer's "Allowed exceptions"
section into the `allowed_exceptions` map is done in the orchestrator (Task
10, Step 5). For Epic 1 the only reviewer is `general`, whose exceptions are
info-level already, so behaviour is correct; richer parsing arrives with the
Epic 2 catalogue.
