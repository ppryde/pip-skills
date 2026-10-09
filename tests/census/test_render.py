import json
import re

import pytest

from scripts import render as rd

NOW = 1_800_000_000.0
PLAIN = {"CENSUS_STATUSLINE_COLOR": "never"}
ANSI = re.compile(r"\x1b\[[0-9;]*m")
GIT = {"branch": "feat/x", "detached": False, "uncommitted": 3, "ahead": 1, "has_upstream": True}
NO_GIT = {"branch": None, "detached": False, "uncommitted": 0, "ahead": 0, "has_upstream": False}


def payload(**over):
    base = {
        "session_id": "s1",
        "model": {"display_name": "Opus 5.5"},
        "workspace": {"current_dir": "/Users/pip/repos/pip-skills"},
        "context_window": {"used_percentage": 42.4},
        "cost": {"total_cost_usd": 3.1, "total_duration_ms": 3_600_000 * 2},
    }
    base.update(over)
    return base


def draw(p=None, env=None, limits=None, git=GIT, now=NOW):
    return rd.draw(p if p is not None else payload(), env={**PLAIN, **(env or {})}, now=now, limits=limits, git=git)


def lines(**kw):
    return draw(**kw).split("\n")


class TestBars:
    def test_pac_bar_eats_left_to_right(self):
        assert rd.pac_bar(42.4, 10, color=False) == "••••ᗧ•••••"

    def test_pac_bar_edges(self):
        assert rd.pac_bar(0, 10, color=False) == "ᗧ" + "•" * 9
        assert rd.pac_bar(100, 10, color=False) == "•" * 9 + "ᗧ"
        assert rd.pac_bar(250, 10, color=False) == "•" * 9 + "ᗧ"

    def test_cost_bar_eats_dollar_signs(self):
        assert rd.pac_bar(30, 10, ahead="$", color=False) == "•••ᗧ$$$$$$"

    def test_trail_is_coloured_by_slot(self):
        bar = rd.pac_bar(100, 10, color=True)
        assert "\x1b[32m•" in bar  # first slot green
        assert "\x1b[38;5;208m•" in bar  # slot 8 orange (80%)
        assert "\x1b[31m•" in bar  # slot 9 red (90%)
        assert "\x1b[93mᗧ" in bar  # bright yellow Pac-Man

    def test_track_ahead_is_bright_white(self):
        assert "\x1b[97m•" in rd.pac_bar(0, 10, color=True)


class TestLevelColours:
    @pytest.mark.parametrize("pct,code", [(0, "32"), (74, "32"), (75, "38;5;208"), (89, "38;5;208"), (90, "31")])
    def test_ramp(self, pct, code):
        assert rd.level_colour(pct) == f"\x1b[{code}m"

    @pytest.mark.parametrize("pct,code", [(100, "32"), (90, "32"), (89, "38;5;208"), (75, "38;5;208"), (74, "31")])
    def test_inverted_ramp(self, pct, code):
        assert rd.level_colour_inv(pct) == f"\x1b[{code}m"


class TestFmtReset:
    @pytest.mark.parametrize(
        "delta,text",
        [(-50, "0m"), (45 * 60, "45m"), (2 * 3600 + 10 * 60, "2h10m"), (3 * 86400 + 4 * 3600, "3d4h")],
    )
    def test_compact(self, delta, text):
        assert rd.fmt_reset(NOW + delta, NOW) == text


class TestContext:
    def test_percentage_and_bar(self):
        assert lines()[0].startswith("🧠 ••••ᗧ••••• 42%")

    def test_derived_from_current_usage(self):
        p = payload(context_window={
            "context_window_size": 200_000,
            "current_usage": {"input_tokens": 20_000, "cache_read_input_tokens": 60_000, "cache_creation_input_tokens": 20_000},
        })
        assert "50%" in lines(p=p)[0]

    def test_absent_is_a_placeholder_not_hidden(self):
        p = payload(context_window={})
        assert lines(p=p)[0].startswith("🧠 ᗧ••••••••• --%")

    def test_rounds_like_printf(self):
        p = payload(context_window={"used_percentage": 83.5})
        assert "84%" in lines(p=p)[0]  # half to even, as printf "%.0f"
        p = payload(context_window={"used_percentage": 82.5})
        assert "82%" in lines(p=p)[0]


class TestCache:
    def cache(self, **over):
        base = {"hit_ratio": 0.93, "requests": 12, "warm": True, "expires_at": NOW + 2 * 3600 + 600, "misses": 0}
        return payload(prompt_cache={**base, **over})

    def test_warm_with_countdown(self):
        assert "│ 🎯 93% ⟳ 2h10m" in lines(p=self.cache())[0]

    def test_cold_has_no_countdown(self):
        seg = lines(p=self.cache(warm=False))[0]
        assert "🧊 93%" in seg and "⟳ 2h10m" not in seg

    def test_misses_shown_only_when_nonzero(self):
        assert "✗2" in lines(p=self.cache(misses=2))[0]
        assert "✗" not in lines(p=self.cache())[0]

    def test_hidden_without_requests(self):
        assert "🎯" not in lines(p=self.cache(requests=0))[0]
        assert "🧊" not in lines(p=self.cache(requests=0, warm=False))[0]

    def test_hidden_when_absent(self):
        assert "🎯" not in lines()[0] and "🧊" not in lines()[0]

    def test_inverted_colour(self):
        out = draw(p=self.cache(hit_ratio=0.5), env={"CENSUS_STATUSLINE_COLOR": "always"})
        assert "\x1b[31m50%" in out


class TestLimits:
    LIM = {
        "five_hour": {"used_percentage": 23.0, "resets_at": NOW + 2 * 3600 + 600},
        "seven_day": {"used_percentage": 4.0, "resets_at": NOW + 3 * 86400 + 4 * 3600},
    }

    def test_each_window_is_its_own_segment(self):
        l1 = lines(limits=self.LIM)[0]
        assert "│ ⏳ ••ᗧ••••••• 23% ⟳ 2h10m │ 📅 ᗧ••••••••• 4% ⟳ 3d4h │" in l1

    def test_absent_means_hidden(self):
        assert "⏳" not in lines(limits=None)[0] and "📅" not in lines(limits={})[0]

    def test_one_window_only(self):
        l1 = lines(limits={"seven_day": self.LIM["seven_day"]})[0]
        assert "📅" in l1 and "⏳" not in l1

    def test_expired_window_is_hidden(self):
        lim = {"five_hour": {"used_percentage": 99.0, "resets_at": NOW - 5}}
        assert "⏳" not in lines(limits=lim)[0]

    def test_malformed_window_is_ignored(self):
        assert "⏳" not in lines(limits={"five_hour": "lots"})[0]


class TestCost:
    def test_bar_amount_and_burn(self):
        l1 = lines()[0]
        assert "💸 ••ᗧ$$$$$$$ $3.10" in l1  # 3.10 / 20 = 16%: 1.6+0.5 -> 2 eaten
        assert "🐌 $1.55/hr" in l1

    def test_budget_env(self):
        assert "💸 ••••••••ᗧ$" in lines(env={"CLAUDE_COST_BUDGET": "4"})[0]

    def test_bad_budget_falls_back_to_default(self):
        assert "💸" in lines(env={"CLAUDE_COST_BUDGET": "lots"})[0]

    def test_over_budget_pins_the_bar_and_goes_red_by_uncapped_pct(self):
        p = payload(cost={"total_cost_usd": 50.0, "total_duration_ms": 3_600_000})
        out = draw(p=p, env={"CENSUS_STATUSLINE_COLOR": "always"})
        assert "\x1b[31m$50.00" in out
        assert rd.pac_bar(100, 10, ahead="$", color=False) in ANSI.sub("", out)

    def test_zero_budget_is_zero_percent(self):
        assert "💸 ᗧ" in lines(env={"CLAUDE_COST_BUDGET": "0"})[0]

    @pytest.mark.parametrize(
        "cost,hours,emoji,text",
        [
            (7.4, 1, "🐌", "$7.40/hr"),
            (8.0, 1, "🔥", "$8.00/hr"),
            (19.6, 1, "🚀", "$19.60/hr"),  # rounds to 20: the tier test is on the rounded figure
            (99.6, 1, "🚀", "$100/hr"),
            (150.0, 1, "🚀", "$150/hr"),
        ],
    )
    def test_burn_tiers(self, cost, hours, emoji, text):
        p = payload(cost={"total_cost_usd": cost, "total_duration_ms": hours * 3_600_000})
        assert f"{emoji} {text}" in lines(p=p)[0]

    def test_no_duration_means_no_burn(self):
        p = payload(cost={"total_cost_usd": 1.0})
        l1 = lines(p=p)[0]
        assert "💸" in l1 and "/hr" not in l1

    def test_no_cost_means_no_cost_segments(self):
        l1 = lines(p=payload(cost={}))[0]
        assert "💸" not in l1 and "/hr" not in l1


class TestLine2:
    def test_model_branch_dir_changes_in_order(self):
        l2 = lines(p=payload(workspace={"current_dir": "/a/b"}))[1]
        assert l2 == "🦾 Opus 5.5 │ 🌿 feat/x │ 📁 /a/b │ ✏️ 3  ⬆️ 1"

    def test_dir_is_last_three_components_with_ellipsis(self):
        assert "📁 …/pip/repos/pip-skills" in lines()[1]

    def test_short_dir_is_whole(self):
        assert "📁 /a/b" in lines(p=payload(workspace={"current_dir": "/a/b"}))[1]

    def test_dir_falls_back_to_cwd_key(self):
        p = payload(workspace={}, cwd="/x/y")
        assert "📁 /x/y" in lines(p=p)[1]

    def test_edits_always_shown_even_zero(self):
        assert "✏️ 0" in lines(git={**GIT, "uncommitted": 0})[1]

    def test_ahead_hidden_when_zero_or_no_upstream(self):
        assert "⬆️" not in lines(git={**GIT, "ahead": 0})[1]
        assert "⬆️" not in lines(git={**GIT, "has_upstream": False})[1]

    def test_no_repo_hides_branch_and_changes(self):
        l2 = lines(git=NO_GIT)[1]
        assert "🌿" not in l2 and "✏️" not in l2 and "📁" in l2

    def test_model_defaults_to_claude(self):
        assert "Claude" in lines(p=payload(model={}))[1]


class TestMascot:
    def test_work_by_default(self):
        assert lines()[1].startswith("🦾 ")

    def test_personal_by_config_dir(self):
        assert lines(env={"CLAUDE_CONFIG_DIR": "/h/.claude-personal"})[1].startswith("🎮 ")

    def test_other_config_dir_is_work(self):
        assert lines(env={"CLAUDE_CONFIG_DIR": "/h/.claude"})[1].startswith("🦾 ")

    @pytest.mark.parametrize("profile,mascot", [("personal", "🎮"), ("home", "🎮"), ("p", "🎮"), ("acme", "🦾")])
    def test_profile_wins_over_config_dir(self, profile, mascot):
        env = {"CLAUDE_PROFILE": profile, "CLAUDE_CONFIG_DIR": "/h/.claude-personal" if mascot == "🦾" else "/h/.claude"}
        assert lines(env=env)[1].startswith(mascot + " ")

    def test_override(self):
        assert lines(env={"CENSUS_STATUSLINE_MASCOT": "🐙"})[1].startswith("🐙 ")


class TestSegments:
    def test_default_layout_is_two_lines(self):
        assert len(lines()) == 2

    def test_order_and_slash(self):
        out = draw(env={"CENSUS_STATUSLINE_SEGMENTS": "dir,model/context"}).split("\n")
        assert out[0].startswith("📁") and "Opus 5.5" in out[0]
        assert out[1].startswith("🧠")

    def test_unknown_names_ignored(self):
        out = draw(env={"CENSUS_STATUSLINE_SEGMENTS": "bogus, model ,nope"})
        assert out == "🦾 Opus 5.5"

    def test_empty_line_dropped(self):
        out = draw(env={"CENSUS_STATUSLINE_SEGMENTS": "cache/model"})
        assert out == "🦾 Opus 5.5"

    def test_blank_setting_means_default(self):
        assert len(lines(env={"CENSUS_STATUSLINE_SEGMENTS": "  "})) == 2

    def test_git_segment_is_the_branch_alone(self):
        assert draw(env={"CENSUS_STATUSLINE_SEGMENTS": "git"}) == "🌿 feat/x"

    def test_changes_segment(self):
        assert draw(env={"CENSUS_STATUSLINE_SEGMENTS": "changes"}) == "✏️ 3  ⬆️ 1"


class TestColour:
    def test_never_strips_everything(self):
        assert "\x1b" not in draw(env={"CENSUS_STATUSLINE_COLOR": "never"})

    def test_auto_is_on_for_a_pipe(self):
        assert "\x1b[" in draw(env={"CENSUS_STATUSLINE_COLOR": "auto"})

    def test_unset_is_auto(self):
        assert "\x1b[" in rd.draw(payload(), env={}, now=NOW, limits=None, git=GIT)

    def test_no_color_honoured_under_auto(self):
        assert "\x1b" not in draw(env={"CENSUS_STATUSLINE_COLOR": "auto", "NO_COLOR": "1"})

    def test_always_overrides_no_color(self):
        assert "\x1b[" in draw(env={"CENSUS_STATUSLINE_COLOR": "always", "NO_COLOR": "1"})

    def test_separator_is_grey(self):
        assert "\x1b[90m │ \x1b[0m" in draw(env={"CENSUS_STATUSLINE_COLOR": "always"})

    def test_plain_equals_stripped_colour(self):
        coloured = draw(env={"CENSUS_STATUSLINE_COLOR": "always"})
        assert ANSI.sub("", coloured) == draw()


class TestSample:
    def test_whole_line(self):
        p = payload(prompt_cache={"hit_ratio": 0.93, "requests": 4, "warm": True, "expires_at": NOW + 3000, "misses": 0})
        lim = {"five_hour": {"used_percentage": 23.0, "resets_at": NOW + 2 * 3600 + 600}}
        l1, l2 = lines(p=p, limits=lim)
        assert l1 == "🧠 ••••ᗧ••••• 42% │ 🎯 93% ⟳ 50m │ ⏳ ••ᗧ••••••• 23% ⟳ 2h10m │ 💸 ••ᗧ$$$$$$$ $3.10 │ 🐌 $1.55/hr"
        assert l2 == "🦾 Opus 5.5 │ 🌿 feat/x │ 📁 …/pip/repos/pip-skills │ ✏️ 3  ⬆️ 1"


class TestFallback:
    def test_draw_error_prints_one_line_never_a_traceback(self):
        out = rd.safe_draw({"model": {"display_name": "Opus 5.5"}}, env=PLAIN, now=NOW, limits=lambda: 1 / 0, git=NO_GIT)
        assert out == "🤖 Opus 5.5"

    def test_fallback_with_no_model(self):
        assert rd.fallback(None) == "🤖 Claude"


def test_preview_payload_is_json_serialisable_and_drawable():
    json.dumps(rd.PREVIEW_PAYLOAD)
    out = rd.draw(rd.PREVIEW_PAYLOAD, env=PLAIN, now=NOW, limits=None, git=GIT)
    assert "🧠" in out and "💸" in out


class TestReviewRound2:
    def test_windows_path_is_shortened_like_a_posix_one(self):
        p = payload(workspace={"current_dir": "C:\\Users\\pip\\repos\\pip-skills"})
        assert "📁 …/pip/repos/pip-skills" in lines(p=p)[1]

    def test_short_windows_path_is_whole(self):
        p = payload(workspace={"current_dir": "C:\\repos"})
        assert "📁 C:\\repos" in lines(p=p)[1]

    def test_worktree_path_wins_for_the_dir(self):
        p = payload(worktree={"path": "/a/b/wt"}, workspace={"current_dir": "/a/b/main"})
        assert "📁 …/a/b/wt" in lines(p=p)[1] and "main" not in lines(p=p)[1]


class TestSideChannelTemp:
    def test_a_planted_symlink_is_never_followed(self, tmp_path):
        victim = tmp_path / "victim.txt"
        victim.write_text("precious")
        side = tmp_path / "side"
        side.mkdir()
        (side / ".s1.tmp").symlink_to(victim)  # the old predictable temp name
        rd.write_side_channel('{"session_id": "s1"}', {"session_id": "s1"}, str(side))
        assert victim.read_text() == "precious"
        assert (side / "s1.json").read_text() == '{"session_id": "s1"}'
        assert [p for p in side.glob("*.tmp") if not p.is_symlink()] == []  # our own temp is gone
