import io
import json
import os
import subprocess
import sys
import time
import unicodedata
from collections import Counter
from pathlib import Path

import pytest

from scripts import cli, vitals
from scripts import store as st
from scripts.vitals import Vitals, Window

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "census"
CENSUS_CLI = PLUGIN / "scripts" / "cli.py"
NOW = 1_791_243_480.0
HOUR = 3600


@pytest.fixture(autouse=True)
def _vitals_env(tmp_path, monkeypatch):
    """Every source vitals consults is pinned inside tmp_path; census is a fake that is not there."""
    monkeypatch.setenv("CENSUS_STORE", str(tmp_path / "census"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)


def entry(**overrides):
    payload = {
        "session_id": "sess-1",
        "session_name": "vitals build",
        "model": {"id": "claude-opus-5-5", "display_name": "Opus 5.5"},
        "effort": {"level": "high"},
        "cost": {
            "total_cost_usd": 0.9,
            "total_duration_ms": 180_000,
            "total_api_duration_ms": 120_000,
            "total_lines_added": 619,
            "total_lines_removed": 3,
        },
        "context_window": {
            "total_input_tokens": 88_000,
            "total_output_tokens": 213,
            "context_window_size": 1_000_000,
            "current_usage": {
                "input_tokens": 2,
                "cache_creation_input_tokens": 3_000,
                "cache_read_input_tokens": 85_000,
            },
            "used_percentage": 9,
        },
        "prompt_cache": {"hit_ratio": 0.89, "expires_at": NOW + 59 * 60},
        "rate_limits": {"five_hour": {"used_percentage": 1, "resets_at": NOW + 4 * HOUR}},
    }
    base = {
        "worktree_cwd": "/repo",
        "updated_at": NOW - 5,
        "branch": "feat/x",
        "payload": payload,
        "stale": False,
        "idle": False,
        "limits": {
            "seven_day": {"used_percentage": 22, "resets_at": NOW + 5 * 86400},
            "five_hour": {"used_percentage": 3, "resets_at": NOW + 4 * HOUR},
        },
    }
    base.update(overrides)
    return base


def full_vitals():
    v = Vitals(now=NOW)
    vitals.apply_census(v, entry())
    v.dirty, v.ahead = 2, 1
    v.pr_number, v.pr_state = 102, "open"
    v.tools = Counter({"Bash": 7, "Write": 1, "Agent": 2, "Read": 4, "Edit": 3, "Grep": 1})
    v.prompts = 3
    return v


def width(line):
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in line)


# ------------------------------------------------------------------- census


def test_apply_census_reads_every_field():
    v = Vitals(now=NOW)
    vitals.apply_census(v, entry())
    assert (v.model, v.effort, v.session_name) == ("Opus 5.5", "high", "vitals build")
    assert v.ctx_pct == 9 and v.ctx_tokens == 88_002 and v.ctx_size == 1_000_000
    assert (v.tokens_in, v.tokens_out, v.cost_usd) == (88_000, 213, 0.9)
    assert (v.duration_ms, v.api_ms, v.lines_added, v.lines_removed) == (180_000, 120_000, 619, 3)
    assert v.cache_hit == 0.89 and v.branch == "feat/x" and not v.stale


def test_merged_limits_win_over_payload_copy_and_order_5h_first():
    v = Vitals(now=NOW)
    vitals.apply_census(v, entry())
    assert [(w.key, w.used) for w in v.windows] == [("five_hour", 3), ("seven_day", 22)]


def test_payload_limits_used_when_entry_has_none():
    v = Vitals(now=NOW)
    vitals.apply_census(v, entry(limits={}))
    assert [(w.key, w.used) for w in v.windows] == [("five_hour", 1)]


def test_expired_and_malformed_windows_dropped():
    v = Vitals(now=NOW)
    vitals.apply_census(
        v,
        entry(
            limits={
                "five_hour": {"used_percentage": 50, "resets_at": NOW - 1},
                "seven_day": {"used_percentage": "x", "resets_at": NOW + 10},
                "spend_limit": {"amount": 3},
            }
        ),
    )
    assert v.windows == []


def test_census_verdict_wins_over_age():
    """A census-mod session does not write on a timer: old updated_at, process alive."""
    live = Vitals(now=NOW)
    vitals.apply_census(live, entry(updated_at=NOW - 6000, stale=False))
    assert not live.stale and live.age == 6000
    dead = Vitals(now=NOW)
    vitals.apply_census(dead, entry(updated_at=NOW - 1, stale=True))
    assert dead.stale


def test_age_rule_when_census_gave_no_verdict():
    for verdict in ({}, {"stale": "yes"}, {"stale": None}):
        e = entry(updated_at=NOW - 600)
        e.pop("stale", None)
        e.update(verdict)
        v = Vitals(now=NOW)
        vitals.apply_census(v, e)
        assert v.stale, verdict
    fresh = entry(updated_at=NOW - 5)
    fresh.pop("stale")
    v = Vitals(now=NOW)
    vitals.apply_census(v, fresh)
    assert not v.stale


def test_ctx_pct_derived_when_missing():
    e = entry()
    del e["payload"]["context_window"]["used_percentage"]
    v = Vitals(now=NOW)
    vitals.apply_census(v, e)
    assert v.ctx_pct == pytest.approx(8.8002)


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_non_finite_numbers_are_unknown(bad):
    e = entry()
    e["payload"]["context_window"]["used_percentage"] = bad
    e["payload"]["prompt_cache"]["hit_ratio"] = bad
    e["limits"]["five_hour"]["used_percentage"] = bad
    v = Vitals(now=NOW)
    vitals.apply_census(v, e)
    assert v.cache_hit is None and [w.key for w in v.windows] == ["seven_day"]
    for render in vitals.RENDERERS.values():
        render(v)


def test_millisecond_or_far_resets_dropped():
    v = Vitals(now=NOW)
    vitals.apply_census(
        v, entry(limits={"five_hour": {"used_percentage": 5, "resets_at": NOW * 1000}})
    )
    assert v.windows == []


@pytest.mark.parametrize("path", [["a", "b"], "bad\x00path", 42])
def test_odd_transcript_path_is_quiet(path):
    v = Vitals(now=NOW)
    vitals.apply_transcript(v, path)
    assert v.prompts is None


def test_junk_entry_never_raises():
    v = Vitals(now=NOW)
    vitals.apply_census(v, {"payload": "nope", "limits": [1], "updated_at": "x"})
    assert v.model is None and v.windows == []


# --------------------------------------------------------------------- pace


def test_pace_projects_at_reset():
    # 2.5h of a 5h window gone, 40% used -> 80% at reset
    assert Window("five_hour", 40, NOW + 2.5 * HOUR).pace(NOW) == pytest.approx(80)


def test_pace_none_when_too_early_or_unknown_window():
    assert Window("five_hour", 1, NOW + 4.9 * HOUR).pace(NOW) is None
    assert Window("spend_limit", 10, NOW + HOUR).pace(NOW) is None


# --------------------------------------------------------------- transcript


def test_transcript_counts_main_thread_tools_and_real_prompts(tmp_path):
    lines = [
        {"type": "user", "message": {"content": "build vitals"}},
        {"type": "user", "isMeta": True, "message": {"content": "meta"}},
        {"type": "user", "message": {"content": "<command-name>/clear</command-name>"}},
        {"type": "user", "message": {"content": [{"type": "tool_result"}]}},
        {
            "type": "user",
            "message": {"content": [{"type": "image"}, {"type": "text", "text": "see this"}]},
        },
        {
            "type": "user",
            "message": {"content": [{"type": "text", "text": "[Request interrupted"}]},
        },
        {"type": "user", "isCompactSummary": True, "message": {"content": "This session is..."}},
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "hi"},
                    {"type": "tool_use", "name": "Bash"},
                    {"type": "tool_use", "name": "Agent"},
                ]
            },
        },
        {
            "type": "assistant",
            "isSidechain": True,
            "message": {"content": [{"type": "tool_use", "name": "Read"}]},
        },
    ]
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\nnot json\n")
    v = Vitals(now=NOW)
    vitals.apply_transcript(v, str(path))
    assert v.tools == Counter({"Bash": 1, "Agent": 1})
    assert v.prompts == 2 and v.agents == 1


def test_missing_transcript_is_quiet(tmp_path):
    v = Vitals(now=NOW)
    vitals.apply_transcript(v, str(tmp_path / "gone.jsonl"))
    assert v.tools == Counter() and v.prompts is None


# ---------------------------------------------------------------------- git


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def make_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "feat/v")
    git(repo, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q", "--allow-empty", "-m", "x")
    return repo


BLOCK = {"branch": "feat/blk", "uncommitted": 4, "ahead": 2, "has_upstream": True, "detached": False}


def test_git_comes_from_the_census_block_and_runs_no_git(monkeypatch):
    seen = []
    monkeypatch.setattr(vitals.subprocess, "run", lambda cmd, **kw: seen.append(cmd) or (_ for _ in ()).throw(OSError()))
    v = Vitals(now=NOW)
    vitals.apply_git(v, entry(git=BLOCK), "/repo")
    assert (v.branch, v.dirty, v.ahead) == ("feat/blk", 4, 2)
    assert seen == []


def test_ahead_is_unknown_without_an_upstream():
    v = Vitals(now=NOW)
    vitals.apply_git(v, entry(git={**BLOCK, "has_upstream": False, "ahead": 0}), "/repo")
    assert v.ahead is None
    assert "↑" not in (vitals.sync_line(v) or "")


def test_a_detached_block_shows_its_short_sha():
    v = Vitals(now=NOW)
    vitals.apply_git(v, entry(git={**BLOCK, "branch": "abc1234", "detached": True}), "/repo")
    assert v.branch == "abc1234"


@pytest.mark.parametrize("bad", [
    {"branch": 3}, {"uncommitted": "x"}, {"uncommitted": None}, {"ahead": None}, {"has_upstream": "yes"}, "junk", [],
])
def test_a_malformed_block_is_the_same_as_none(bad, monkeypatch):
    seen = []
    monkeypatch.setattr(vitals.subprocess, "run", lambda cmd, **kw: seen.append(cmd) or (_ for _ in ()).throw(OSError()))
    block = bad if not isinstance(bad, dict) else {**BLOCK, **bad}
    vitals.apply_git(Vitals(now=NOW), entry(git=block), "/repo")
    assert len(seen) == 1  # fell back to asking git


def test_no_block_falls_back_to_one_uno_status_in_the_worktree(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "a.txt").write_text("a")
    git(repo, "add", "a.txt")
    (repo / "new").mkdir()
    (repo / "new" / "b.txt").write_text("b")
    v = Vitals(now=NOW)
    vitals.apply_git(v, entry(worktree_cwd=str(repo)), "/elsewhere")
    assert (v.branch, v.dirty) == ("feat/v", 1)  # untracked files are not counted
    assert v.ahead is None


def test_the_fallback_argv_is_the_uno_status_with_no_optional_locks(monkeypatch):
    seen = []
    monkeypatch.setattr(vitals.subprocess, "run", lambda cmd, **kw: seen.append((cmd, kw.get("cwd"))) or (_ for _ in ()).throw(OSError()))
    vitals.apply_git(Vitals(now=NOW), None, "/repo")
    assert seen == [(["git", "--no-optional-locks", "status", "--porcelain=2", "--branch", "-uno"], "/repo")]


def test_git_outside_repo_leaves_fields_empty(tmp_path):
    v = Vitals(now=NOW)
    vitals.apply_git(v, None, str(tmp_path))
    assert v.branch is None and v.dirty is None


# ----------------------------------------------------------------------- PR


def test_the_pr_comes_from_the_payload():
    e = entry()
    e["payload"]["pr"] = {"number": 77, "url": "https://x/77", "review_state": "Approved"}
    v = Vitals(now=NOW)
    vitals.apply_census(v, e)
    assert (v.pr_number, v.pr_state) == (77, "approved")


@pytest.mark.parametrize("pr", [{}, {"number": "x"}, {"number": None}, "junk", None])
def test_no_usable_pr_leaves_it_out(pr):
    e = entry()
    e["payload"]["pr"] = pr
    v = Vitals(now=NOW)
    vitals.apply_census(v, e)
    assert v.pr_number is None and v.pr_state is None


def test_vitals_never_calls_gh(tmp_path, monkeypatch):
    """A gh on PATH that fails the test if it is ever run."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    marker = tmp_path / "gh-was-run"
    gh = bin_dir / "gh"
    gh.write_text(f"#!/bin/sh\ntouch {marker}\nexit 1\n")
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    repo = make_repo(tmp_path)
    e = entry(worktree_cwd=str(repo))
    e["payload"]["pr"] = {"number": 5, "review_state": "open"}
    v = Vitals(now=NOW)
    vitals.apply_census(v, e)
    vitals.apply_git(v, e, str(repo))                       # the fallback path
    vitals.apply_git(Vitals(now=NOW), entry(git=BLOCK), str(repo))   # the block path
    assert not marker.exists()
    assert v.pr_number == 5
    src = Path(vitals.__file__).read_text()
    assert '"gh"' not in src and "'gh'" not in src


def test_untracked_is_not_in_any_style():
    for style in vitals.STYLES:
        out = vitals.RENDERERS[style](full_vitals())
        assert "untracked" not in out and "unbaptised" not in out and " new" not in out


# ------------------------------------------------------------------- render


@pytest.mark.parametrize("style", vitals.STYLES)
def test_every_style_fits_a_phone(style):
    out = vitals.RENDERERS[style](full_vitals())
    assert max(width(line) for line in out.splitlines()) <= 44


@pytest.mark.parametrize("style", vitals.STYLES)
def test_every_style_survives_empty_vitals(style):
    out = vitals.RENDERERS[style](Vitals(now=NOW))
    assert out  # no source at all still renders something, never raises


def lean(**over):
    """The full fixture with a PR whose state census records (`approved`), and whatever `over` changes."""
    v = full_vitals()
    v.pr_state = "approved"
    for key, value in over.items():
        setattr(v, key, value)
    return v


def test_lean_is_three_lines_with_full_data():
    assert vitals.render_compact(lean()) == "\n".join([
        "⚡ 9% ▰▱▱▱▱▱ 88k/1M · Opus 5.5 · $0.90",
        "🌿 feat/x · 🔀 #102 ✓ approved · ✏️ 2 ⬆️ 1",
        "⏳ 5h 3% ⟳4h · 7d 22% ⟳5d",
    ])


def test_lean_without_a_pr_has_no_pr_part():
    out = vitals.render_compact(lean(pr_number=None, pr_state=None))
    assert out.splitlines()[1] == "🌿 feat/x · ✏️ 2 ⬆️ 1"


def test_lean_pr_states_are_marked():
    marks = {"approved": "✓ approved", "pending": "… pending", "changes_requested": "✗ changes"}
    for state, mark in marks.items():
        assert f"🔀 #102 {mark}" in vitals.render_compact(lean(pr_state=state))
    assert vitals.render_compact(lean(pr_state="open")).splitlines()[1] == "🌿 feat/x · 🔀 #102 · ✏️ 2 ⬆️ 1"


def test_lean_shows_ahead_only_above_zero():
    assert vitals.render_compact(lean(ahead=0)).splitlines()[1].endswith("✏️ 2")
    assert vitals.render_compact(lean(ahead=None)).splitlines()[1].endswith("✏️ 2")


def test_lean_without_limits_has_no_limits_line():
    assert vitals.render_compact(lean(windows=[])).splitlines() == [
        "⚡ 9% ▰▱▱▱▱▱ 88k/1M · Opus 5.5 · $0.90",
        "🌿 feat/x · 🔀 #102 ✓ approved · ✏️ 2 ⬆️ 1",
    ]


def test_lean_shows_only_the_windows_present():
    out = vitals.render_compact(lean(windows=[Window("seven_day", 22, NOW + 5 * 86400)]))
    assert out.splitlines()[2] == "⏳ 7d 22% ⟳5d"


def test_lean_adds_a_fourth_line_only_when_the_reading_may_not_be_live():
    v = Vitals(now=NOW)
    vitals.apply_census(v, entry(updated_at=NOW - 300, stale=True))
    lines = vitals.render_compact(v).splitlines()
    assert lines[-1] == "⚠️ reading is 5m old" and len(lines) == 4
    assert len(vitals.render_compact(lean()).splitlines()) == 3


def test_lean_drops_effort_duration_tools_and_agents():
    out = vitals.render_compact(lean())
    assert "high" not in out and "tools" not in out and "agent" not in out and "⏱" not in out


def test_lean_with_nothing_known_is_one_line():
    assert vitals.render_compact(Vitals(now=NOW)) == "⚡ ?% ▱▱▱▱▱▱"


def test_lean_a_very_long_branch_and_model_are_clipped_not_wrapped():
    out = vitals.render_compact(lean(
        branch="feat/census-v2-account-keyed-limits-and-more",
        model="Claude Opus 5.5 with an extremely long display name", cost_usd=1234.56, ctx_tokens=888_000,
    ))
    assert out.splitlines() == [
        "⚡ 9% ▰▱▱▱▱▱ · Claude Opus 5.5 with an extr…",  # the cost, then the token counts, went first
        "🌿 feat/census-v2-acc… · 🔀 #102 ✓ approved · ✏️ 2 ⬆️ 1".replace(" ✓ approved", ""),
        "⏳ 5h 3% ⟳4h · 7d 22% ⟳5d",
    ]
    assert max(width(line) for line in out.splitlines()) <= 44


def test_lean_drops_the_cost_first_then_the_token_counts_before_clipping_the_model():
    first = lambda **kw: vitals.render_compact(lean(ctx_tokens=88_000, **kw)).splitlines()[0]  # noqa: E731
    assert first(model="Opus 5.5") == "⚡ 9% ▰▱▱▱▱▱ 88k/1M · Opus 5.5 · $0.90"
    assert first(model="Claude Opus 5.5 ext") == "⚡ 9% ▰▱▱▱▱▱ 88k/1M · Claude Opus 5.5 ext"  # the cost went
    assert first(model="Claude Opus 5.5 extended ed") == "⚡ 9% ▰▱▱▱▱▱ · Claude Opus 5.5 extended ed"  # then the tokens
    assert first(model="Claude Opus 5.5 extended edition x").endswith("extended edi…")  # only then is the model clipped


def test_lean_the_state_word_goes_before_the_branch_is_cut():
    out = vitals.render_compact(lean(pr_state="changes_requested", dirty=12345, ahead=123))
    assert out.splitlines()[1] == "🌿 feat/x · 🔀 #102 · ✏️ 12345 ⬆️ 123"


def test_detailed_shows_pace_and_breakdown():
    out = vitals.render_detailed(full_vitals())
    assert "912k headroom" in out
    assert "cache hit 89% · warm 59m" in out
    assert "3 prompts · 18 tool calls" in out
    assert "↳ Bash 7 · Read 4" in out and "  Edit 3 · Agent 2" in out
    assert "2 subagents spawned" in out
    # 22% after 2 of 7 days -> 77% at reset
    assert "pace → 77% at reset (within)" in out


def test_sibling_sessions_reading_is_flagged_as_borrowed():
    v = Vitals(now=NOW, session_id="me")
    vitals.apply_census(v, entry())  # payload session_id is sess-1
    assert v.borrowed
    assert "another session's reading" in vitals.render_compact(v)
    own = Vitals(now=NOW, session_id="sess-1")
    vitals.apply_census(own, entry())
    assert not own.borrowed


def long_vitals():
    v = full_vitals()
    v.branch = "feat/census-v2-account-keyed-limits-and-more"
    v.pr_number, v.pr_state = 12345, "draft"
    v.session_name = "a very long session name that goes on and on and on"
    v.model = "Claude Opus 5.5 with an extremely long display name"
    v.tools = Counter(
        {
            "mcp__plugin_context-mode_context-mode__ctx_batch_execute": 120,
            "mcp__claude_ai_Slack__slack_search_public_and_private": 100,
            "Bash": 50,
            "NotebookEditWithAVeryLongName": 10,
        }
    )
    v.windows.append(Window("seven_day_opus_extra", 100, NOW + 86400))
    v.dirty, v.ahead = 12345, 123
    return v


@pytest.mark.parametrize("style", vitals.STYLES)
def test_every_style_fits_a_phone_with_long_real_world_data(style):
    out = vitals.RENDERERS[style](long_vitals())
    widest = max(out.splitlines(), key=width)
    assert width(widest) <= 44, widest


def test_repo_line_keeps_pr_when_branch_clipped():
    line = vitals.repo_line(long_vitals())
    assert line.endswith("· PR #12345 draft") and "…" in line


def test_mcp_tool_names_shortened():
    assert vitals.tool_label("mcp__plugin_context-mode_context-mode__ctx_search") == "ctx_search"
    assert vitals.tool_label("mcp__x__an_extremely_long_tool_name") == "an_extremely_…"


def test_lean_shows_only_known_windows():
    v = full_vitals()
    v.windows = [Window("seven_day_opus", 50, NOW + HOUR)]
    assert "⏳" not in vitals.render_compact(v)


def test_unknown_window_label_abbreviated():
    assert Window("seven_day_opus_extra_long", 1, NOW).label == "seven day o…"


# ---------------------------------------------------------------- formatting


@pytest.mark.parametrize(
    "n,expected",
    [
        (None, "?"),
        (213, "213"),
        (1500, "1.5k"),
        (88_002, "88k"),
        (999_600, "1M"),
        (1_000_000, "1M"),
    ],
)
def test_fmt_tokens(n, expected):
    assert vitals.fmt_tokens(n) == expected


@pytest.mark.parametrize(
    "secs,expected",
    [(5, "5s"), (180, "3m"), (4 * HOUR + 49 * 60, "4h49m"), (5 * 86400 + 19 * HOUR, "5d19h")],
)
def test_fmt_duration(secs, expected):
    assert vitals.fmt_duration(secs) == expected


def test_bar_clamps():
    assert (
        vitals.bar(150, 4) == "▰▰▰▰" and vitals.bar(-5, 4) == "▱▱▱▱" and vitals.bar(None, 2) == "▱▱"
    )


@pytest.mark.parametrize(
    "words,style",
    [
        ([], "compact"),
        (["detailed"], "detailed"),
        (["drama"], "compact"),  # playful is gone: not a style any more
        (["brief"], "compact"),
        (["full"], "detailed"),
        (["Trend"], "detailed"),
        (["nonsense"], "compact"),
        (["please detailed"], "detailed"),
    ],
)
def test_resolve_style(words, style):
    assert vitals.resolve_style(words) == style


@pytest.mark.parametrize("raw", [None, "", "${CLAUDE_SESSION_ID}", "$CLAUDE_SESSION_ID"])
def test_unexpanded_session_is_unknown(raw):
    assert vitals._clean_session(raw) is None


# --------------------------------------------------------------- end to end


def ingest(session="sess-1", cwd=None, **over):
    """Record a session into the (tmp) census store, as the status line or the mod would."""
    payload = entry()["payload"] | {"session_id": session, **({"cwd": str(cwd)} if cwd else {})} | over
    st.ingest(json.dumps(payload), now=time.time())


def test_gather_prefers_own_session(tmp_path):
    ingest("sess-1", tmp_path, model={"display_name": "Mine"})
    ingest("sess-2", tmp_path, model={"display_name": "Sibling"})
    v = vitals.gather("sess-1", str(tmp_path))
    assert v.model == "Mine" and not v.borrowed


def test_gather_falls_back_to_the_worktrees_freshest_session(tmp_path):
    ingest("sess-2", tmp_path, model={"display_name": "Sibling"})
    v = vitals.gather("other", str(tmp_path))
    assert v.model == "Sibling" and v.borrowed


def test_with_no_session_id_the_worktrees_freshest_is_used(tmp_path):
    ingest("sess-2", tmp_path)
    assert vitals.gather(None, str(tmp_path)).has_reading


def test_nothing_recorded_is_no_reading(tmp_path):
    assert vitals.gather("sess-1", str(tmp_path)).has_reading is False


def test_the_entry_is_exactly_what_census_read_prints(tmp_path, capsys):
    """Vitals reads census in-process; the shape must be byte-identical to `census read`."""
    ingest("sess-1", tmp_path)
    assert cli.main(["read", "--session", "sess-1"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert vitals.census_entry("sess-1", str(tmp_path)) == printed
    assert cli.main(["read", "--worktree", os.path.realpath(tmp_path)]) == 0
    assert vitals.census_entry("nobody", str(tmp_path)) == json.loads(capsys.readouterr().out)


def test_vitals_runs_no_census_subprocess_at_all(tmp_path, monkeypatch):
    """The only subprocess left is the fixed-argv git fallback; census itself is never shelled out to."""
    ingest("sess-1", tmp_path)
    seen = []
    monkeypatch.setattr(vitals.subprocess, "run", lambda cmd, **kw: seen.append(cmd) or (_ for _ in ()).throw(OSError()))
    vitals.gather("sess-1", str(tmp_path))
    assert all(cmd[0] == "git" for cmd in seen)
    src = Path(vitals.__file__).read_text()
    for gone in ("CENSUS_CLI", "cli.path", "_runnable", "_one_arg", "shlex", "census_cli"):
        assert gone not in src


def test_census_store_is_honoured(tmp_path, monkeypatch):
    elsewhere = tmp_path / "elsewhere"
    monkeypatch.setenv("CENSUS_STORE", str(elsewhere))
    ingest("sess-1", tmp_path)
    assert (elsewhere / "sessions" / "sess-1.json").exists()
    assert vitals.gather("sess-1", str(tmp_path)).has_reading


def test_no_census_still_prints(tmp_path, capsys):
    assert vitals.main(["--cwd", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "no census reading yet" in out and "⚡ ?%" in out


def test_cli_runs_as_script(tmp_path):
    ingest("sess-1", tmp_path)
    env = {**os.environ, "CENSUS_STORE": str(tmp_path / "census"), "CLAUDE_CONFIG_DIR": str(tmp_path / "cfg")}
    result = subprocess.run(
        [sys.executable, vitals.__file__, "detailed", "--session", "sess-1", "--cwd", str(tmp_path)],
        capture_output=True, text=True, check=True, env=env,
    )
    assert "SESSION VITALS" in result.stdout


def test_git_is_asked_not_to_take_optional_locks(monkeypatch):
    seen = []
    monkeypatch.setattr(vitals.subprocess, "run", lambda cmd, **kw: seen.append(cmd) or (_ for _ in ()).throw(OSError()))
    vitals.apply_git(Vitals(now=NOW), None, "/repo")
    assert seen[0][:3] == ["git", "--no-optional-locks", "status"]


def test_clip_counts_wide_characters_as_two_columns():
    assert width(vitals.clip("日本語日本語", 7)) <= 7
    assert vitals.clip("日本語日本語", 7).endswith("…")
    assert vitals.clip("日本語", 6) == "日本語"
    assert vitals.clip("abcdefgh", 5) == "abcd…"


# ------------------------------------------------------------------ review round: output, prompts, argv


def test_output_is_utf8_bytes_even_on_a_legacy_windows_stdout(tmp_path, monkeypatch):
    """Every renderer prints emoji and box glyphs; a cp1252 console raises on them unless the bytes are written."""
    raw = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(raw, encoding="cp1252", errors="strict", write_through=True))

    assert vitals.main(["--cwd", str(tmp_path)]) == 0

    out = raw.getvalue().decode("utf-8")
    assert "no census reading yet" in out and "⚡" in out
    assert any(ord(ch) > 0x2000 for ch in out)  # glyphs a cp1252 console cannot encode were written


def test_a_failure_message_is_utf8_bytes_too(tmp_path, monkeypatch):
    raw = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(raw, encoding="cp1252", errors="strict", write_through=True))
    monkeypatch.setitem(vitals.RENDERERS, "compact", lambda v: (_ for _ in ()).throw(RuntimeError("boom ✻")))

    assert vitals.main(["--cwd", str(tmp_path)]) == 0
    assert "boom ✻" in raw.getvalue().decode("utf-8")


@pytest.mark.parametrize("content", ["[Request interrupted by user]", "[Request interrupted by user for tool use]"])
def test_an_interruption_marker_is_not_a_prompt_in_either_form(content):
    assert vitals._is_prompt({}, content) is False
    assert vitals._is_prompt({}, [{"type": "text", "text": content}]) is False
    assert vitals._is_prompt({}, "a real prompt") is True


# ------------------------------------------------------------------------ the default style


@pytest.fixture
def census_home(tmp_path, monkeypatch):
    """The census dir (and so vitals.json) pinned inside tmp_path."""
    monkeypatch.delenv("CENSUS_STORE", raising=False)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    return tmp_path / "cfg" / "census"


MARKER = "(vitals: no default style chosen yet)"


def run(capsys, *argv):
    code = vitals.main([*argv])
    return code, capsys.readouterr().out


class TestDefaultStyle:
    def test_nothing_saved_is_lean_with_one_final_marker_line(self, census_home, tmp_path, capsys):
        code, out = run(capsys, "--cwd", str(tmp_path))
        assert code == 0
        assert out.rstrip("\n").splitlines()[-1] == MARKER
        assert out.count(MARKER) == 1
        assert "⚡ ?%" in out  # the lean readout

    def test_set_default_saves_and_the_next_run_uses_it_with_no_marker(self, census_home, tmp_path, capsys):
        code, out = run(capsys, "--set-default", "detailed", "--cwd", str(tmp_path))
        assert code == 0 and "detailed" in out
        assert json.loads((census_home / "vitals.json").read_text()) == {"default_style": "detailed"}
        code, out = run(capsys, "--cwd", str(tmp_path))
        assert "SESSION VITALS" in out and MARKER not in out

    @pytest.mark.parametrize("given,saved", [
        ("lean", "compact"), ("brief", "compact"), ("compact", "compact"), ("full", "detailed"), ("trend", "detailed"),
        ("detailed", "detailed"), ("DETAILED", "detailed"), (" Lean ", "compact"),
    ])
    def test_set_default_takes_names_and_aliases(self, census_home, tmp_path, capsys, given, saved):
        assert run(capsys, "--set-default", given, "--cwd", str(tmp_path))[0] == 0
        assert json.loads((census_home / "vitals.json").read_text())["default_style"] == saved

    @pytest.mark.parametrize("bad", ["playful", "drama", "witchfinder", "", "rm -rf /", "lean; ls", "$(id)", "fancy", "lean detailed"])
    def test_anything_else_is_an_error_and_nothing_is_written(self, census_home, tmp_path, capsys, bad):
        assert run(capsys, "--set-default", bad, "--cwd", str(tmp_path))[0] == 2
        assert not (census_home / "vitals.json").exists()

    def test_an_explicit_style_wins_and_shows_no_marker(self, census_home, tmp_path, capsys):
        run(capsys, "--set-default", "detailed", "--cwd", str(tmp_path))
        _, out = run(capsys, "lean", "--cwd", str(tmp_path))
        assert "SESSION VITALS" not in out and MARKER not in out
        _, out = run(capsys, "--style", "compact", "--cwd", str(tmp_path))
        assert "⚡ ?%" in out and MARKER not in out

    def test_an_explicit_style_before_any_default_does_not_nag(self, census_home, tmp_path, capsys):
        _, out = run(capsys, "detailed", "--cwd", str(tmp_path))
        assert MARKER not in out

    @pytest.mark.parametrize("content", ["{ nope", "[]", "42", '{"default_style": "fancy"}', '{"default_style": 7}', "{}", ""])
    def test_a_corrupt_or_odd_file_is_unset_and_never_raises(self, census_home, tmp_path, capsys, content):
        census_home.mkdir(parents=True)
        (census_home / "vitals.json").write_text(content)
        assert vitals.read_default() is None
        _, out = run(capsys, "--cwd", str(tmp_path))
        assert MARKER in out

    def test_a_default_of_playful_from_the_old_branch_reads_as_unset(self, census_home, tmp_path, capsys):
        census_home.mkdir(parents=True)
        (census_home / "vitals.json").write_text('{"default_style": "playful"}')
        assert vitals.read_default() is None
        assert MARKER in run(capsys, "--cwd", str(tmp_path))[1]

    def test_playful_is_not_a_style_any_more(self, tmp_path, capsys):
        assert "playful" not in vitals.STYLES and "playful" not in vitals.ALIASES.values()
        with pytest.raises(SystemExit):
            vitals.main(["--style", "playful", "--cwd", str(tmp_path)])
        _, out = run(capsys, "playful", "--cwd", str(tmp_path))  # a word that names no style: the default (lean)
        assert "⚡" in out and "SESSION VITALS" not in out

    def test_setting_it_again_replaces_it_atomically(self, census_home, tmp_path, capsys):
        run(capsys, "--set-default", "lean", "--cwd", str(tmp_path))
        run(capsys, "--set-default", "detailed", "--cwd", str(tmp_path))
        assert vitals.read_default() == "detailed"
        assert sorted(p.name for p in census_home.iterdir()) == ["vitals.json"]  # no temp file left

    def test_it_lives_in_the_census_dir_so_it_is_per_account(self, tmp_path, monkeypatch, capsys):
        monkeypatch.delenv("CENSUS_STORE", raising=False)
        for name in ("a", "b"):
            monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / name))
            run(capsys, "--set-default", "detailed" if name == "a" else "lean", "--cwd", str(tmp_path))
        assert json.loads((tmp_path / "a" / "census" / "vitals.json").read_text())["default_style"] == "detailed"
        assert json.loads((tmp_path / "b" / "census" / "vitals.json").read_text())["default_style"] == "compact"

    def test_a_dotjson_census_store_keeps_it_beside_the_file(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("CENSUS_STORE", str(tmp_path / "legacy" / "status.json"))
        run(capsys, "--set-default", "detailed", "--cwd", str(tmp_path))
        assert (tmp_path / "legacy" / "vitals.json").is_file()

    def test_an_unwritable_census_dir_says_so_and_does_not_traceback(self, census_home, tmp_path, monkeypatch, capsys):
        (tmp_path / "cfg").mkdir()
        (tmp_path / "cfg" / "census").write_text("a file where the directory should be")
        code, out = run(capsys, "--set-default", "lean", "--cwd", str(tmp_path))
        assert code == 1 and "could not save" in out
