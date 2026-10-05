import json
import subprocess
import sys
import unicodedata
from collections import Counter

import pytest

from scripts import vitals
from scripts.vitals import Vitals, Window

NOW = 1_791_243_480.0
HOUR = 3600


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
    v.dirty, v.untracked, v.ahead, v.behind = 2, 1, 1, 0
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


def test_stale_flag_from_age_even_if_census_says_fresh():
    v = Vitals(now=NOW)
    vitals.apply_census(v, entry(updated_at=NOW - 600))
    assert v.stale


def test_ctx_pct_derived_when_missing():
    e = entry()
    del e["payload"]["context_window"]["used_percentage"]
    v = Vitals(now=NOW)
    vitals.apply_census(v, e)
    assert v.ctx_pct == pytest.approx(8.8002)


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
    assert v.prompts == 1 and v.agents == 1


def test_missing_transcript_is_quiet(tmp_path):
    v = Vitals(now=NOW)
    vitals.apply_transcript(v, str(tmp_path / "gone.jsonl"))
    assert v.tools == Counter() and v.prompts is None


# ---------------------------------------------------------------------- git


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_git_branch_dirty_and_untracked(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "feat/v")
    git(
        repo,
        "-c",
        "user.email=a@b",
        "-c",
        "user.name=a",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "x",
    )
    (repo / "a.txt").write_text("a")
    git(repo, "add", "a.txt")
    (repo / "b.txt").write_text("b")
    v = Vitals(now=NOW)
    vitals.apply_git(v, str(repo), with_pr=False)
    assert (v.branch, v.dirty, v.untracked) == ("feat/v", 1, 1)
    assert v.ahead is None  # no upstream


def test_git_outside_repo_leaves_fields_empty(tmp_path):
    v = Vitals(now=NOW)
    vitals.apply_git(v, str(tmp_path), with_pr=False)
    assert v.branch is None and v.dirty is None


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
    assert "2 dirty · 1 untracked · ↑1 ↓0" in out
    assert "5h 3%" in out and "7d 22%" in out
    assert "18 tools · 2 agents" in out


def test_detailed_shows_pace_and_breakdown():
    out = vitals.render_detailed(full_vitals())
    assert "912k headroom" in out
    assert "cache hit 89% · warm 59m" in out
    assert "3 prompts · 18 tool calls" in out
    assert "Bash 7 · Read 4 · Edit 3" in out
    assert "2 subagents spawned" in out
    # 22% after 2 of 7 days -> 77% at reset
    assert "pace → 77% at reset (within)" in out


def test_playful_verdict_follows_thresholds():
    v = full_vitals()
    assert "The soul is clean" in vitals.render_playful(v)
    v.ctx_pct = 85
    assert "Found wanting" in vitals.render_playful(v)
    v.ctx_pct, v.stale = 10, True
    assert "vigil is broken" in vitals.render_playful(v)


def test_stale_reading_is_flagged():
    v = full_vitals()
    v.stale = True
    assert "stale reading" in vitals.render_compact(v)


# ---------------------------------------------------------------- formatting


@pytest.mark.parametrize(
    "n,expected", [(None, "?"), (213, "213"), (1500, "1.5k"), (88_002, "88k"), (1_000_000, "1M")]
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
    v = vitals.gather("sess-1", str(tmp_path), with_pr=False)
    assert v.model == "Opus 5.5"
    assert fake_census.read_text().splitlines() == ["read --session sess-1"]


def test_gather_falls_back_to_worktree(fake_census, tmp_path):
    v = vitals.gather("other", str(tmp_path), with_pr=False)
    assert v.model == "Opus 5.5"
    assert fake_census.read_text().splitlines()[1].startswith("read --worktree ")


def test_no_census_still_prints(tmp_path, capsys):
    assert vitals.main(["--no-pr", "--cwd", str(tmp_path)]) == 0
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
            "--no-pr",
            "--cwd",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "THE SANCTUM'S VITAL SIGNS" in result.stdout
