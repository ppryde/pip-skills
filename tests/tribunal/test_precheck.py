"""Step 0 pre-check: the verdict table, the state file, and the hook's narrow approvals.

`gh` is never run: the script's `gh` function is monkeypatched. State is pinned to
tmp_path through RECKONING_STATE_DIR by the autouse fixture, so nothing lands in the
real ~/.local/state.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import pytest
from tribunal_helpers import PLUGIN, SHA, SKILL, allow_gh, allowed

SCRIPTS = PLUGIN / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import precheck

PRECHECK = SCRIPTS / "precheck.py"
OTHER_SHA = "f" * 40
SNAP = "0123456789ab"
SLUG = "octo__repo__12"
T1, T2, T3 = "2026-10-01T10:00:00Z", "2026-10-02T10:00:00Z", "2026-10-03T10:00:00Z"


@pytest.fixture(autouse=True)
def _state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state = tmp_path / "state"
    monkeypatch.setenv("RECKONING_STATE_DIR", str(state))
    return state


def pr_payload(
    *,
    threads: tuple[tuple[bool, str], ...] = (),
    review: str | None = None,
    comment: str | None = None,
    head: str = SHA,
    more: bool = False,
    checks: tuple[dict[str, Any], ...] = (),
    more_checks: bool = False,
) -> dict[str, Any]:
    rollup = {
        "contexts": {"pageInfo": {"hasNextPage": more_checks}, "nodes": list(checks)}
    }
    return {
        "headRefOid": head,
        "headRefName": "feature/x",
        "reviewThreads": {
            "pageInfo": {"hasNextPage": more},
            "nodes": [
                {
                    "id": f"PRRT_{i:08d}",
                    "isResolved": r,
                    "comments": {"nodes": [{"createdAt": t, "updatedAt": t}]},
                }
                for i, (r, t) in enumerate(threads)
            ],
        },
        "reviews": {
            "nodes": [{"submittedAt": review, "updatedAt": review}] if review else []
        },
        "comments": {
            "nodes": [{"createdAt": comment, "updatedAt": comment}] if comment else []
        },
        "commits": {"nodes": [{"commit": {"statusCheckRollup": rollup}}]},
    }


def fake_gh(
    monkeypatch: pytest.MonkeyPatch, pr: dict[str, Any] | None
) -> list[list[str]]:
    calls: list[list[str]] = []

    def gh(args: list[str]) -> str | None:
        calls.append(args)
        if pr is None:
            return None
        return json.dumps({"data": {"repository": {"pullRequest": pr}}})

    monkeypatch.setattr(precheck, "gh", gh)
    return calls


def args(cmd: str, *extra: str) -> Any:
    return precheck.parse([cmd, "--repo", "octo/repo", "--pr", "12", *extra])


def check(*extra: str) -> dict[str, Any]:
    return precheck.cmd_check(args("check", *extra))


def save(snapshot: str, *extra: str) -> dict[str, Any]:
    return precheck.cmd_save(args("save", "--snapshot", snapshot, *extra))


def stored(state: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((state / f"{SLUG}.json").read_text())
    return data


# ---- summarise -------------------------------------------------------------------


def test_summarise_counts_and_newest_mark() -> None:
    s = precheck.summarise(
        pr_payload(
            threads=((False, T1), (True, T3), (False, T1)), review=T2, comment=T1
        )
    )
    assert s["unresolved"] == 2 and s["newest_activity"] == T3 and s["head_sha"] == SHA
    assert s["branch"] == "feature/x"
    assert (
        not s["truncated"] and s["pending_checks"] == [] and not s["checks_truncated"]
    )


def test_summarise_ignores_malformed_stamps_sha_and_branch() -> None:
    pr = pr_payload(threads=((False, "yesterday"),), review=T1, head="nope")
    pr["headRefName"] = "bad branch;"
    s = precheck.summarise(pr)
    assert s["newest_activity"] == T1 and s["head_sha"] is None and s["branch"] is None


def test_summarise_pending_checks() -> None:
    checks = (
        {"__typename": "CheckRun", "name": "coderabbit", "status": "IN_PROGRESS"},
        {"__typename": "CheckRun", "name": "ci", "status": "COMPLETED"},
        {"__typename": "StatusContext", "context": "copilot", "state": "PENDING"},
        {"__typename": "StatusContext", "context": "lint", "state": "SUCCESS"},
        {"__typename": "CheckRun", "name": "bad\nname", "status": "QUEUED"},
    )
    assert precheck.summarise(pr_payload(checks=checks))["pending_checks"] == [
        "coderabbit",
        "copilot",
    ]
    assert precheck.summarise(pr_payload(more_checks=True))["checks_truncated"]


def test_unresolved_key_tracks_which_threads_not_just_how_many() -> None:
    a = precheck.summarise(pr_payload(threads=((False, T1), (True, T1))))
    b = precheck.summarise(pr_payload(threads=((True, T1), (False, T1))))
    assert a["unresolved"] == b["unresolved"] == 1
    assert a["unresolved_key"] != b["unresolved_key"]


# ---- decide ----------------------------------------------------------------------

KEY0 = precheck.summarise(pr_payload())["unresolved_key"]
KEY2 = precheck.summarise(pr_payload(threads=((False, T1), (False, T1))))[
    "unresolved_key"
]


def now(**kw: Any) -> dict[str, Any]:
    base = {
        "head_sha": SHA,
        "unresolved": 0,
        "unresolved_key": KEY0,
        "truncated": False,
        "newest_activity": T1,
        "pending_checks": [],
        "checks_truncated": False,
    }
    return {**base, **kw}


PREV = {
    "head_sha": SHA,
    "unresolved": 0,
    "unresolved_key": KEY0,
    "newest_activity": T1,
    "summary": None,
}
OPEN2 = {"unresolved": 2, "unresolved_key": KEY2}


@pytest.mark.parametrize(
    ("current", "prev", "full", "verdict"),
    [
        (now(), PREV, True, "full"),
        (now(), None, False, "full"),
        (now(head_sha=None), PREV, False, "full"),
        (now(truncated=True), PREV, False, "full"),
        (now(newest_activity=T2), PREV, False, "full"),
        (now(), PREV, False, "quiet"),
        (now(newest_activity=None), PREV, False, "quiet"),
        (now(head_sha=OTHER_SHA), PREV, False, "quiet"),
        (now(head_sha=OTHER_SHA, pending_checks=["bot"]), PREV, False, "pending"),
        (now(head_sha=OTHER_SHA, checks_truncated=True), PREV, False, "full"),
        (now(pending_checks=["bot"]), PREV, False, "quiet"),
        (now(**OPEN2), {**PREV, **OPEN2, "summary": "C1 ..."}, False, "cached"),
        (now(**OPEN2), {**PREV, **OPEN2}, False, "full"),
        (
            now(unresolved=2, unresolved_key="other"),
            {**PREV, **OPEN2, "summary": "C1 ..."},
            False,
            "full",
        ),
        (
            now(**OPEN2, head_sha=OTHER_SHA),
            {**PREV, **OPEN2, "summary": "x"},
            False,
            "full",
        ),
        # review-body findings with no threads stay reachable
        (now(), {**PREV, "summary": "C1 PR-level ..."}, False, "cached"),
        (
            now(head_sha=OTHER_SHA),
            {**PREV, "summary": "C1 PR-level ..."},
            False,
            "full",
        ),
    ],
)
def test_decide(
    current: dict[str, Any], prev: dict[str, Any] | None, full: bool, verdict: str
) -> None:
    assert precheck.decide(current, prev, full)[0] == verdict


# ---- check / save round trips ----------------------------------------------------


def test_first_run_is_full_then_save_makes_next_quiet(
    monkeypatch: pytest.MonkeyPatch, _state: Path
) -> None:
    fake_gh(monkeypatch, pr_payload(threads=((True, T1),), review=T1))
    first = check()
    assert first["verdict"] == "full" and first["reason"] == "no previous run recorded"
    assert first["branch"] == "feature/x"
    snap = first["snapshot"]
    assert first["summary_path"] == str(_state / f"{SLUG}.{snap}.summary.md")
    assert save(snap)["saved"]
    state = stored(_state)
    assert (
        state["head_sha"] == SHA
        and state["newest_activity"] == T1
        and state["summary"] is None
    )
    assert not list(_state.glob("*.pending.json"))
    assert check()["verdict"] == "quiet"


def test_cached_summary_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_gh(monkeypatch, pr_payload(threads=((False, T1),)))
    out = check()
    Path(out["summary_path"]).write_text("PR #12 ...\nC1 a.py:3 — @bot — x — y\n")
    assert save(out["snapshot"], "--with-summary")["summary_stored"]
    again = check()
    assert again["verdict"] == "cached" and again["summary"].startswith("PR #12")
    assert again["branch"] == "feature/x" and "snapshot" not in again
    assert not Path(out["summary_path"]).exists()


def test_comment_landing_mid_run_still_counts_as_new(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_gh(monkeypatch, pr_payload(threads=((False, T1),)))
    snap = check()["snapshot"]
    fake_gh(monkeypatch, pr_payload(threads=((False, T1), (False, T2))))
    save(snap)
    assert check()["verdict"] == "full"


def test_own_fix_push_still_reaches_pending(
    monkeypatch: pytest.MonkeyPatch, _state: Path
) -> None:
    """save keeps the check-time head: the fix push is seen as new next time."""
    fake_gh(monkeypatch, pr_payload(threads=((False, T1),)))
    snap = check()["snapshot"]
    fake_gh(monkeypatch, pr_payload(threads=((True, T1),), head=OTHER_SHA))
    save(snap)
    assert stored(_state)["head_sha"] == SHA and stored(_state)["unresolved"] == 0
    running = (
        {"__typename": "CheckRun", "name": "coderabbit", "status": "IN_PROGRESS"},
    )
    fake_gh(
        monkeypatch, pr_payload(threads=((True, T1),), head=OTHER_SHA, checks=running)
    )
    out = check()
    assert out["verdict"] == "pending" and out["pending_checks"] == ["coderabbit"]


def test_two_sessions_keep_separate_snapshots(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_gh(monkeypatch, pr_payload(threads=((False, T1),)))
    a = check()["snapshot"]
    fake_gh(monkeypatch, pr_payload(threads=((False, T1), (False, T2))))
    b = check()["snapshot"]
    assert a != b
    assert save(a)["saved"]
    assert check()["verdict"] == "full"  # A never saw T2's comment
    assert save(b)["saved"]


def test_full_flag_never_short_circuits(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_gh(monkeypatch, pr_payload())
    save(check()["snapshot"])
    assert check("--full")["verdict"] == "full"


def test_quiet_records_the_moved_head(
    monkeypatch: pytest.MonkeyPatch, _state: Path
) -> None:
    fake_gh(monkeypatch, pr_payload())
    save(check()["snapshot"])
    fake_gh(monkeypatch, pr_payload(head=OTHER_SHA))
    assert check()["verdict"] == "quiet"
    assert stored(_state)["head_sha"] == OTHER_SHA


def test_query_failure_means_full(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_gh(monkeypatch, None)
    assert check()["verdict"] == "full"
    assert not save(SNAP)["saved"]
    assert save("../../etc")["reason"] == "bad snapshot id"


def test_query_passes_validated_values_as_separate_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = fake_gh(monkeypatch, pr_payload())
    check()
    assert calls[0][:2] == ["api", "graphql"]
    assert (
        "owner=octo" in calls[0] and "repo=repo" in calls[0] and "number=12" in calls[0]
    )


@pytest.mark.parametrize(
    ("repo", "pr"),
    [
        ("octo/..", "12"),
        ("octo", "12"),
        ("a/b;rm", "12"),
        ("octo/repo", "1x"),
        ("oc_to/repo", "1"),
    ],
)
def test_detect_rejects_bad_values(repo: str, pr: str) -> None:
    assert precheck.detect(repo, pr) is None


def test_state_names_cannot_collide() -> None:
    assert precheck.slug("foo-bar", "baz", "1") != precheck.slug("foo", "bar-baz", "1")


def test_state_dir_default_is_outside_the_plugin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("RECKONING_STATE_DIR")
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert precheck.state_dir() == tmp_path / ".local" / "state" / "reckoning"
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "x"))
    assert precheck.state_dir() == tmp_path / "x" / "reckoning"


@pytest.mark.parametrize(
    "env", [{}, {"XDG_STATE_HOME": "/xdg"}, {"RECKONING_STATE_DIR": "/r"}]
)
def test_hook_state_dir_mirrors_script(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str]
) -> None:
    monkeypatch.delenv("RECKONING_STATE_DIR")
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert allow_gh.reckoning_state_dir() == str(precheck.state_dir())


# ---- hook approvals --------------------------------------------------------------


@pytest.mark.parametrize(
    "tail",
    ["check", "check --full", "check --repo octo/repo --pr 12", "check --repo=octo/repo --pr=12 --full",
     f"save --snapshot {SNAP}", f"save --snapshot {SNAP} --with-summary",
     f"save --repo octo/repo --pr 12 --snapshot={SNAP} --with-summary"],
)  # fmt: skip
def test_hook_allows_precheck_at_its_own_path(tail: str) -> None:
    assert allowed(f"python3 '{PRECHECK}' {tail}")
    via_skill_dir = f"{SKILL.parent}/../../scripts/precheck.py"
    assert allowed(f"python3 '{via_skill_dir}' {tail}")


@pytest.mark.parametrize(
    "cmd",
    [
        "python3 /tmp/precheck.py check",
        f"python3 '{PRECHECK}'",
        f"python3 '{PRECHECK}' delete",
        f"python3 '{PRECHECK}' check --with-summary",
        f"python3 '{PRECHECK}' save --full",
        f"python3 '{PRECHECK}' save --snapshot ../x",
        f"python3 '{PRECHECK}' check extra",
        f"python3 '{PRECHECK}' check --repo 'octo/repo;x'",
        f"python3 '{PRECHECK}' check --pr -1",
        f"python3 -c 'print(1)' '{PRECHECK}' check",
        f"python '{PRECHECK}' check",
        f"python3 '{PRECHECK}' check; rm -rf x",
    ],
)
def test_hook_declines_other_python(cmd: str) -> None:
    assert not allowed(cmd)


def test_hook_declines_a_relative_script_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolved against the hook's cwd it matches; the shell may sit somewhere else."""
    monkeypatch.chdir(SCRIPTS)
    assert os.path.realpath("precheck.py") == os.path.realpath(PRECHECK)
    assert not allowed("python3 precheck.py check")
    assert not allowed("python3 ../scripts/precheck.py check")


def write(path: str) -> bool:
    return allow_gh.evaluate(
        {"tool_name": "Write", "tool_input": {"file_path": path, "content": "x"}}
    )


SUMMARY = f"{SLUG}.{SNAP}.summary.md"


def test_hook_allows_summary_write_into_state_dir(_state: Path) -> None:
    _state.mkdir()
    assert write(str(_state / SUMMARY))


def test_hook_declines_other_writes(_state: Path, tmp_path: Path) -> None:
    _state.mkdir()
    assert not write(str(_state / f"{SLUG}.json"))
    assert not write(str(_state / "notes.md"))
    assert not write(str(_state / f"{SLUG}.summary.md"))
    assert not write(str(_state / "sub" / SUMMARY))
    assert not write(str(tmp_path / SUMMARY))
    assert not write(SUMMARY)
    assert not write(str(_state / ".." / SUMMARY))
    assert not write(str(_state) + "/./" + SUMMARY)
    assert not write(str(_state) + "//" + SUMMARY)
    target = tmp_path / "elsewhere.md"
    linked = f"{SLUG}.{'f' * 12}.summary.md"
    (_state / linked).symlink_to(target)
    assert not write(str(_state / linked))


def test_hook_declines_link_dotdot_escape(_state: Path, tmp_path: Path) -> None:
    """realpath follows `link` then applies `..`; a lexical resolver drops `link/..`."""
    _state.mkdir()
    evil = tmp_path / "evil"
    evil.mkdir()
    (evil / "link").symlink_to(_state / "nonexistent")
    assert not write(f"{evil}/link/../{SUMMARY}")


def test_hook_declines_a_state_dir_under_dot_claude(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rules = tmp_path / ".claude" / "rules"
    rules.mkdir(parents=True)
    monkeypatch.setenv("RECKONING_STATE_DIR", str(rules))
    assert not write(str(rules / SUMMARY))
    monkeypatch.setenv("RECKONING_STATE_DIR", "relative/state")
    assert not write(str(Path.cwd() / "relative" / "state" / SUMMARY))


def test_hook_declines_writes_through_a_symlinked_state_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    monkeypatch.setenv("RECKONING_STATE_DIR", str(real))
    assert not write(str(link / SUMMARY))  # lexical parent must be the state dir itself
    assert write(str(real / SUMMARY))


# ---- skill text ------------------------------------------------------------------


def test_skill_precheck_commands_are_approved() -> None:
    refs = SKILL.parent / "references"
    found = []
    for path in [SKILL, *sorted(refs.glob("*.md"))]:
        for block in re.findall(
            r"```bash\n(.*?)```", path.read_text(encoding="utf-8"), re.DOTALL
        ):
            for line in block.strip().splitlines():
                if line.startswith("python3 "):
                    found.append(
                        line.replace(
                            "<skill base directory>", str(SKILL.parent)
                        ).replace("{snapshot}", SNAP)
                    )
    assert len(found) >= 2
    assert all(allowed(c) for c in found), found


def test_skill_keeps_the_delegation_rule() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "Never load the full comment payload into the main session" in text
    assert "Nesting guard" in text
    delegate = (SKILL.parent / "references" / "delegate.md").read_text(encoding="utf-8")
    assert 'model: "sonnet"' in delegate and "1,500 tokens" in delegate
    assert "branch <head branch>" in delegate
