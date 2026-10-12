"""VG-9: the three vigils (plugins/vigil, skills/context-vigil, plugins/context-vigil-mod)
are deliberately not unified, so the values they must agree on are pinned here.

Every value is read from its source file (Python modules by parsing the AST, the mod's
TypeScript by regex), never duplicated, so editing one copy without the others fails.
Where the copies legitimately differ, the difference is asserted explicitly.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VIGIL = ROOT / "plugins" / "vigil" / "scripts"
SKILL = ROOT / "skills" / "context-vigil" / "scripts" / "context_vigil"
MOD = ROOT / "plugins" / "context-vigil-mod" / "plugin" / "core"


def py_const(path: Path, name: str) -> object:
    """A module-level constant of a Python file, evaluated without importing it."""
    for node in ast.parse(path.read_text()).body:
        targets = node.targets if isinstance(node, ast.Assign) else [getattr(node, "target", None)]
        value = getattr(node, "value", None)
        if value is not None and any(isinstance(t, ast.Name) and t.id == name for t in targets):
            return eval(compile(ast.Expression(value), str(path), "eval"), {"__builtins__": {}})
    raise AssertionError(f"{name} not found in {path}")


def py_default(path: Path, key: str) -> object:
    """A key of a module-level ``DEFAULTS`` dict literal."""
    defaults = py_const(path, "DEFAULTS")
    assert isinstance(defaults, dict)
    return defaults[key]


def ts_default(name: str) -> int:
    """A numeric field of the mod's ``DEFAULTS`` object literal in core/settings.ts."""
    text = (MOD / "settings.ts").read_text()
    block = re.search(r"export const DEFAULTS[^=]*=\s*\{(.*?)\n\}", text, re.S)
    assert block, "DEFAULTS not found in settings.ts"
    match = re.search(rf"\b{name}:\s*(\d+)", block.group(1))
    assert match, f"{name} not found in the mod's DEFAULTS"
    return int(match.group(1))


def test_nudge_threshold_default_is_shared():
    values = {
        "vigil": py_default(VIGIL / "config.py", "context.threshold"),
        "skill": py_default(SKILL / "config.py", "context.threshold"),
        "mod": ts_default("nudgeAt"),
    }
    assert len(set(values.values())) == 1, values


def test_repeat_step_default_is_shared_by_skill_and_mod():
    # plugins/vigil nudges once per cycle (the gate), so it has no repeat step.
    assert py_default(SKILL / "config.py", "nudge.repeat_step") == ts_default("step")


def test_last_light_threshold_default_is_shared_by_skill_and_mod():
    # plugins/vigil has no last light.
    assert py_default(SKILL / "config.py", "last_light.threshold") == ts_default("lastLightAt")


def test_gate_ttl_is_shared_by_vigil_and_skill():
    assert py_const(VIGIL / "state.py", "GATE_TTL_SECONDS") == py_const(SKILL / "state.py", "GATE_TTL_SECONDS")


def test_census_stale_horizon_is_shared_by_vigil_and_skill():
    # The mod reads no census store, so it has no horizon of its own.
    assert py_const(VIGIL / "census.py", "STALE_HORIZON_SECONDS") == py_const(SKILL / "census.py", "STALE_HORIZON_SECONDS")


def test_archive_keep_is_shared_by_vigil_and_skill():
    assert py_const(VIGIL / "state.py", "ARCHIVE_KEEP") == py_const(SKILL / "state.py", "ARCHIVE_KEEP")


def test_cooldown_differs_by_design():
    # INTENDED, asserted so a change on either side is a decision: plugins/vigil hard-codes
    # 5 minutes ("outlives census's lag window", see scripts/state.py), while context-vigil
    # defaults to 60 s and makes it configurable (`handover.cooldown_seconds`). The mod keeps
    # no cooldown. NOTE for review: the skill's 60 s is shorter than the 90 s stale horizon.
    assert py_const(VIGIL / "state.py", "COOLDOWN_TTL_SECONDS") == 300
    assert py_const(SKILL / "state.py", "COOLDOWN_SECONDS") == 60
    assert py_default(SKILL / "config.py", "handover.cooldown_seconds") == 60


def test_resume_prompts_name_their_own_tag_and_the_handover():
    # INTENDED to differ in wording: each is branded with its own name and each surface
    # words the nudge for its own channel (pane keystrokes vs an in-process prompt).
    # What they share: a tag, the word "handover", and an instruction to resume.
    vigil = str(py_const(VIGIL / "cli.py", "_KICK_PROMPT"))
    skill = str(py_const(SKILL / "hooks.py", "KICK_PROMPT"))
    mod = (MOD / "handover.ts").read_text()
    mod_prompt = re.search(r"export function resumeText[^{]*\{\s*return `([^`]*)`", mod)
    assert mod_prompt, "resumeText not found in handover.ts"
    for tag, text in (("vigil:", vigil), ("context-vigil:", skill), ("[context-vigil-mod]", mod_prompt.group(1))):
        assert text.startswith(tag), (tag, text)
        assert "handover" in text and "esume" in text, text


def test_pane_safety_patterns_are_shared_by_vigil_and_skill():
    # Both find the (possibly named) prompt box and refuse a dialog footer or a running
    # turn the same way; the wording must not drift.
    for name in ("RULE_PATTERN", "FOOTER_PATTERN", "BUSY_PATTERN"):
        assert py_const(VIGIL / "pane.py", name) == py_const(SKILL / "pane.py", name), name


def _shape(path: Path, name: str) -> str:
    """A function's AST with docstrings and type annotations removed: the plugin
    writes ``int | None`` where the skill writes ``Optional[int]``."""
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            node.returns = None
            for arg in node.args.args + node.args.kwonlyargs:
                arg.annotation = None
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                node.body = body[1:]
            for sub in ast.walk(node):
                if isinstance(sub, ast.AnnAssign):
                    sub.annotation = ast.Constant(None)
            return ast.dump(node, include_attributes=False)
    raise AssertionError(f"{name} not found in {path}")


def test_pane_logic_is_shared_by_vigil_and_skill():
    # The screen-reading functions are copies; pin their bodies so a fix to one reaches both.
    for name in ("plain", "typed_text", "_input_index", "input_row", "below_box", "hold_reason"):
        assert _shape(VIGIL / "pane.py", name) == _shape(SKILL / "pane.py", name), name
    assert py_const(VIGIL / "pane.py", "BUSY_REASON") == py_const(SKILL / "pane.py", "BUSY_REASON")
