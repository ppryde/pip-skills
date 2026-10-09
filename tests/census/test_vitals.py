import json
import os
import subprocess
import sys
import unicodedata
from collections import Counter
from pathlib import Path

import pytest

from scripts import vitals
from scripts.vitals import Vitals, Window

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "census"
CENSUS_CLI = PLUGIN / "scripts" / "cli.py"
NOW = 1_791_243_480.0
HOUR = 3600


@pytest.fixture(autouse=True)
def _vitals_env(tmp_path, monkeypatch):
    """Every source vitals consults is pinned inside tmp_path; census is a fake that is not there."""
    monkeypatch.setenv("CENSUS_CLI", str(tmp_path / "no-census.py"))
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


def test_compact_is_lean_and_complete():
    out = vitals.render_compact(full_vitals())
    lines = out.splitlines()
    assert len(lines) <= 7
    assert "ctx 9%" in lines[0] and "88k/1M" in lines[0]
    assert "Opus 5.5 · high · $0.90" in out
    assert "feat/x · PR #102 open" in out
    assert "2 dirty · ↑1" in out and "new" not in out and "↓" not in out
    assert "5h 3%" in out and "7d 22%" in out
    assert "18 tools · 2 agents" in out


def test_detailed_shows_pace_and_breakdown():
    out = vitals.render_detailed(full_vitals())
    assert "912k headroom" in out
    assert "cache hit 89% · warm 59m" in out
    assert "3 prompts · 18 tool calls" in out
    assert "↳ Bash 7 · Read 4" in out and "  Edit 3 · Agent 2" in out
    assert "2 subagents spawned" in out
    # 22% after 2 of 7 days -> 77% at reset
    assert "pace → 77% at reset (within)" in out


def test_playful_verdict_follows_thresholds():
    v = full_vitals()
    assert "The soul is clean" in vitals.render_playful(v)
    v.ctx_pct = 85
    assert "Found wanting" in vitals.render_playful(v)
    assert "signs are hidden" in vitals.render_playful(Vitals(now=NOW))


def test_stale_reading_shows_age_without_hiding_the_verdict():
    v = Vitals(now=NOW)
    vitals.apply_census(v, entry(updated_at=NOW - 300, stale=True))
    v.ctx_pct = 85
    assert "reading is 5m old" in vitals.render_compact(v)
    playful = vitals.render_playful(v)
    assert "Found wanting" in playful and "reading is 5m old" in playful


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


def test_compact_shows_only_known_windows():
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
        (["drama"], "playful"),
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


@pytest.fixture
def fake_census(tmp_path, monkeypatch):
    """A census CLI that answers --session sess-1 and --worktree, logging calls."""
    log = tmp_path / "calls.log"
    data = tmp_path / "entry.json"
    data.write_text(json.dumps(entry(updated_at=9e12)))
    script = tmp_path / "fake_census.py"
    script.write_text(
        "import sys, pathlib\n"
        f"pathlib.Path({str(log)!r}).open('a').write(' '.join(sys.argv[1:]) + '\\n')\n"
        "if sys.argv[2] == '--session' and sys.argv[3] != 'sess-1':\n"
        "    print('{}'); sys.exit(0)\n"
        f"print(pathlib.Path({str(data)!r}).read_text())\n"
    )
    monkeypatch.setenv("CENSUS_CLI", str(script))
    return log


def test_gather_prefers_own_session(fake_census, tmp_path):
    v = vitals.gather("sess-1", str(tmp_path))
    assert v.model == "Opus 5.5"
    assert fake_census.read_text().splitlines() == ["read --session sess-1"]


def test_gather_falls_back_to_worktree(fake_census, tmp_path):
    v = vitals.gather("other", str(tmp_path))
    assert v.model == "Opus 5.5"
    assert fake_census.read_text().splitlines()[1].startswith("read --worktree ")


def test_no_census_still_prints(tmp_path, capsys):
    assert vitals.main(["--cwd", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "no census reading yet" in out and "ctx ?%" in out


def test_cli_runs_as_script(fake_census, tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            vitals.__file__,
            "playful",
            "--session",
            "sess-1",
            "--cwd",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "THE SANCTUM'S VITAL SIGNS" in result.stdout


# ----------------------------------------------- resolving census (the real one)


@pytest.fixture
def real_census_env(tmp_path, monkeypatch):
    """The environment census itself reads, pinned inside tmp_path; no CENSUS_CLI override,
    no PATH, and no sibling cli.py (vitals pretends to live elsewhere)."""
    monkeypatch.delenv("CENSUS_CLI", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    monkeypatch.setattr(vitals, "__file__", str(tmp_path / "elsewhere" / "vitals.py"))
    return dict(os.environ)


def test_its_own_plugin_cli_is_used_first(tmp_path, monkeypatch):
    monkeypatch.delenv("CENSUS_CLI", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    assert vitals.census_cli() == CENSUS_CLI


def test_census_cli_env_is_authoritative_over_the_sibling(tmp_path, monkeypatch):
    other = tmp_path / "other.py"
    other.write_text("")
    monkeypatch.setenv("CENSUS_CLI", str(other))
    assert vitals.census_cli() == other
    monkeypatch.setenv("CENSUS_CLI", str(tmp_path / "gone.py"))
    assert vitals.census_cli() is None  # refused, not skipped past to the sibling


def test_cli_path_pointer_in_a_census_store_dir_is_followed(tmp_path, monkeypatch, real_census_env):
    store = tmp_path / "census"
    store.mkdir()
    (store / "cli.path").write_text(str(CENSUS_CLI))
    monkeypatch.setenv("CENSUS_STORE", str(store))
    assert vitals.census_cli() == CENSUS_CLI


def test_a_dotjson_store_is_a_directory_like_any_other(tmp_path, monkeypatch, real_census_env):
    (tmp_path / "pointer-parent").mkdir()
    (tmp_path / "pointer-parent" / "cli.path").write_text(str(CENSUS_CLI))
    monkeypatch.setenv("CENSUS_STORE", str(tmp_path / "pointer-parent" / "status.json"))
    assert vitals.census_cli() is None


def test_gather_reads_a_session_recorded_by_the_real_census(tmp_path, monkeypatch):
    store = tmp_path / "census"
    monkeypatch.setenv("CENSUS_STORE", str(store))
    monkeypatch.delenv("CENSUS_CLI", raising=False)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    payload = entry()["payload"] | {"cwd": str(tmp_path), "session_id": "sess-1"}
    ingest = subprocess.run(
        [sys.executable, str(CENSUS_CLI), "ingest"], input=json.dumps(payload),
        capture_output=True, text=True, env=dict(os.environ), check=False,
    )
    assert ingest.returncode == 0, ingest.stderr
    v = vitals.gather("sess-1", str(tmp_path))
    assert v.has_reading and v.model == "Opus 5.5"
    assert v.dirty == 0 and v.branch is None  # not a repo: the block's null-safe values


def test_a_census_override_is_one_path_never_a_command_line(monkeypatch):
    monkeypatch.setenv("CENSUS_CLI", f"{sys.executable} -c 'print(1)'")
    assert vitals.census_cli() is None


@pytest.mark.parametrize("bad", ["relative/cli.py", "cli.py"])
def test_a_relative_census_path_is_refused(bad, monkeypatch):
    monkeypatch.setenv("CENSUS_CLI", bad)
    assert vitals.census_cli() is None


def test_a_directory_or_a_plain_data_file_is_not_a_census_cli(tmp_path, monkeypatch):
    data = tmp_path / "notes.txt"
    data.write_text("hi")
    for target in (tmp_path, data):
        monkeypatch.setenv("CENSUS_CLI", str(target))
        assert vitals.census_cli() is None


def test_a_python_script_and_an_executable_are_both_accepted(tmp_path, monkeypatch):
    script = tmp_path / "cli.py"
    script.write_text("")
    program = tmp_path / "census"
    program.write_text("#!/bin/sh\n")
    program.chmod(0o755)
    monkeypatch.setenv("CENSUS_CLI", str(script))
    assert vitals.census_cli() == script
    monkeypatch.setenv("CENSUS_CLI", str(program))
    assert vitals.census_cli() == program


def test_a_pointer_to_a_missing_or_relative_file_is_ignored(tmp_path, monkeypatch, real_census_env):
    store = tmp_path / "census"
    store.mkdir()
    monkeypatch.setenv("CENSUS_STORE", str(store))
    for recorded in ("gone/cli.py", str(tmp_path / "gone" / "cli.py")):
        (store / "cli.path").write_text(recorded)
        assert vitals.census_cli() is None


def test_each_call_site_builds_its_own_argv(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(vitals.subprocess, "run", lambda cmd, **kw: seen.append(cmd) or (_ for _ in ()).throw(OSError()))
    script = tmp_path / "cli.py"
    script.write_text("")
    program = tmp_path / "census"
    program.write_text("#!/bin/sh\n")
    program.chmod(0o755)
    monkeypatch.setenv("CENSUS_CLI", str(script))
    vitals.census_entry("s 1", "/repo")
    monkeypatch.setenv("CENSUS_CLI", str(program))
    vitals.census_entry("s 1", "/repo")
    assert seen[0] == [sys.executable, str(script), "read", "--session", "s 1"]
    assert seen[2] == [str(program), "read", "--session", "s 1"]


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
