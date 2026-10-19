"""Step 0 pre-check: the verdict table, the state file, and the hook's narrow approvals.

`gh` is never run: the script's `gh` function is monkeypatched. State is pinned to
tmp_path through RECKONING_STATE_DIR by the autouse fixture, so nothing lands in the
real ~/.local/state.
"""

from __future__ import annotations

import json
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


@pytest.fixture(autouse=True)
def _state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state = tmp_path / "state"
    monkeypatch.setenv("RECKONING_STATE_DIR", str(state))
    return state


def pr_payload(
    *,
    threads: list[tuple[bool, str]] = (),  # type: ignore[assignment]
    review: str | None = None,
    comment: str | None = None,
    head: str = SHA,
    more: bool = False,
    checks: list[dict[str, Any]] = (),  # type: ignore[assignment]
) -> dict[str, Any]:
    return {
        "headRefOid": head,
        "reviewThreads": {
            "pageInfo": {"hasNextPage": more},
            "nodes": [
                {
                    "isResolved": r,
                    "comments": {"nodes": [{"createdAt": t, "updatedAt": t}]},
                }
                for r, t in threads
            ],
        },
        "reviews": {
            "nodes": [{"submittedAt": review, "updatedAt": review}] if review else []
        },
        "comments": {
            "nodes": [{"createdAt": comment, "updatedAt": comment}] if comment else []
        },
        "commits": {
            "nodes": [
                {"commit": {"statusCheckRollup": {"contexts": {"nodes": list(checks)}}}}
            ]
        },
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


def check(*extra: str) -> dict[str, Any]:
    return precheck.cmd_check(precheck_args("check", *extra))


def save(*extra: str) -> dict[str, Any]:
    return precheck.cmd_save(precheck_args("save", *extra))


def precheck_args(cmd: str, *extra: str) -> Any:
    return precheck.parse([cmd, "--repo", "octo/repo", "--pr", "12", *extra])


T1, T2, T3 = "2026-10-01T10:00:00Z", "2026-10-02T10:00:00Z", "2026-10-03T10:00:00Z"


# ---- summarise -------------------------------------------------------------------


def test_summarise_counts_and_newest_mark() -> None:
    s = precheck.summarise(
        pr_payload(
            threads=[(False, T1), (True, T3), (False, T1)], review=T2, comment=T1
        )
    )
    assert s["unresolved"] == 2 and s["newest_activity"] == T3 and s["head_sha"] == SHA
    assert not s["truncated"] and s["pending_checks"] == []


def test_summarise_ignores_malformed_stamps_and_sha() -> None:
    s = precheck.summarise(
        pr_payload(threads=[(False, "yesterday")], review=T1, head="nope")
    )
    assert s["newest_activity"] == T1 and s["head_sha"] is None


def test_summarise_pending_checks() -> None:
    checks = [
        {"__typename": "CheckRun", "name": "coderabbit", "status": "IN_PROGRESS"},
        {"__typename": "CheckRun", "name": "ci", "status": "COMPLETED"},
        {"__typename": "StatusContext", "context": "copilot", "state": "PENDING"},
        {"__typename": "StatusContext", "context": "lint", "state": "SUCCESS"},
        {"__typename": "CheckRun", "name": "bad\nname", "status": "QUEUED"},
    ]
    assert precheck.summarise(pr_payload(checks=checks))["pending_checks"] == [
        "coderabbit",
        "copilot",
    ]


# ---- decide ----------------------------------------------------------------------


def now(**kw: Any) -> dict[str, Any]:
    base = {
        "head_sha": SHA,
        "unresolved": 0,
        "truncated": False,
        "newest_activity": T1,
        "pending_checks": [],
    }
    return {**base, **kw}


PREV = {"head_sha": SHA, "unresolved": 0, "newest_activity": T1, "summary": None}


@pytest.mark.parametrize(
    ("current", "prev", "full", "verdict"),
    [
        (now(), PREV, True, "full"),
        (now(), None, False, "full"),
        (now(head_sha=None), PREV, False, "full"),
        (now(truncated=True), PREV, False, "full"),
        (now(newest_activity=T2), PREV, False, "full"),
        (now(), PREV, False, "quiet"),
        (now(head_sha=OTHER_SHA), PREV, False, "quiet"),
        (now(head_sha=OTHER_SHA, pending_checks=["bot"]), PREV, False, "pending"),
        (now(pending_checks=["bot"]), PREV, False, "quiet"),
        (
            now(unresolved=2),
            {**PREV, "unresolved": 2, "summary": "C1 ..."},
            False,
            "cached",
        ),
        (now(unresolved=2), {**PREV, "unresolved": 2}, False, "full"),
        (
            now(unresolved=1),
            {**PREV, "unresolved": 2, "summary": "C1 ..."},
            False,
            "full",
        ),
        (
            now(unresolved=2, head_sha=OTHER_SHA),
            {**PREV, "unresolved": 2, "summary": "x"},
            False,
            "full",
        ),
        (now(newest_activity=None), PREV, False, "quiet"),
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
    fake_gh(monkeypatch, pr_payload(threads=[(True, T1)], review=T1))
    first = check()
    assert first["verdict"] == "full" and first["reason"] == "no previous run recorded"
    assert first["summary_path"] == str(_state / "octo-repo-12.summary.md")
    assert save()["saved"]
    stored = json.loads((_state / "octo-repo-12.json").read_text())
    assert (
        stored["head_sha"] == SHA
        and stored["newest_activity"] == T1
        and stored["summary"] is None
    )
    assert not (_state / "octo-repo-12.pending.json").exists()
    assert check()["verdict"] == "quiet"


def test_cached_summary_round_trip(
    monkeypatch: pytest.MonkeyPatch, _state: Path
) -> None:
    fake_gh(monkeypatch, pr_payload(threads=[(False, T1)]))
    out = check()
    Path(out["summary_path"]).write_text("PR #12 ...\nC1 a.py:3 — @bot — x — y\n")
    assert save("--with-summary")["summary_stored"]
    again = check()
    assert again["verdict"] == "cached" and again["summary"].startswith("PR #12")
    assert not Path(out["summary_path"]).exists()


def test_comment_landing_mid_run_still_counts_as_new(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_gh(monkeypatch, pr_payload(threads=[(False, T1)]))
    check()
    fake_gh(monkeypatch, pr_payload(threads=[(False, T1), (False, T2)]))
    save()
    assert check()["verdict"] == "full"


def test_save_recounts_after_resolution(
    monkeypatch: pytest.MonkeyPatch, _state: Path
) -> None:
    fake_gh(monkeypatch, pr_payload(threads=[(False, T1)]))
    check()
    fake_gh(monkeypatch, pr_payload(threads=[(True, T1)]))
    save()
    assert json.loads((_state / "octo-repo-12.json").read_text())["unresolved"] == 0
    assert check()["verdict"] == "quiet"


def test_full_flag_never_short_circuits(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_gh(monkeypatch, pr_payload())
    check()
    save()
    assert check("--full")["verdict"] == "full"


def test_quiet_records_the_moved_head(
    monkeypatch: pytest.MonkeyPatch, _state: Path
) -> None:
    fake_gh(monkeypatch, pr_payload())
    check()
    save()
    fake_gh(monkeypatch, pr_payload(head=OTHER_SHA))
    assert check()["verdict"] == "quiet"
    assert (
        json.loads((_state / "octo-repo-12.json").read_text())["head_sha"] == OTHER_SHA
    )


def test_query_failure_means_full(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_gh(monkeypatch, None)
    assert check()["verdict"] == "full"
    assert save() == {
        "saved": False,
        "reason": "no pre-check snapshot; run check first",
    }


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
    [("octo/..", "12"), ("octo", "12"), ("a/b;rm", "12"), ("octo/repo", "1x")],
)
def test_detect_rejects_bad_values(repo: str, pr: str) -> None:
    assert precheck.detect(repo, pr) is None


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
     "save", "save --with-summary", "save --repo octo/repo --pr 12 --with-summary"],
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


def write(path: str) -> bool:
    return allow_gh.evaluate(
        {"tool_name": "Write", "tool_input": {"file_path": path, "content": "x"}}
    )


def test_hook_allows_summary_write_into_state_dir(_state: Path) -> None:
    _state.mkdir()
    assert write(str(_state / "octo-repo-12.summary.md"))


def test_hook_declines_other_writes(_state: Path, tmp_path: Path) -> None:
    _state.mkdir()
    assert not write(str(_state / "octo-repo-12.json"))
    assert not write(str(_state / "notes.md"))
    assert not write(str(_state / "sub" / "octo-repo-12.summary.md"))
    assert not write(str(tmp_path / "octo-repo-12.summary.md"))
    assert not write("octo-repo-12.summary.md")
    assert not write(str(_state / ".." / "octo-repo-12.summary.md"))
    target = tmp_path / "elsewhere.md"
    (_state / "octo-repo-13.summary.md").symlink_to(target)
    assert not write(str(_state / "octo-repo-13.summary.md"))


def test_hook_declines_writes_through_a_symlinked_state_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    monkeypatch.setenv("RECKONING_STATE_DIR", str(real))
    assert write(str(link / "octo-repo-12.summary.md"))  # same directory once resolved
    assert not write(str(tmp_path / "octo-repo-12.summary.md"))


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
                        line.replace("<skill base directory>", str(SKILL.parent))
                    )
    assert len(found) >= 2
    assert all(allowed(c) for c in found), found


def test_skill_keeps_the_delegation_rule() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "Never load the full comment payload into the main session" in text
    assert "Nesting guard" in text
    delegate = (SKILL.parent / "references" / "delegate.md").read_text(encoding="utf-8")
    assert 'model: "sonnet"' in delegate and "1,500 tokens" in delegate
