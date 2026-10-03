"""Pure helpers of the dev-only live smoke harness (no tmux, no claude)."""
from __future__ import annotations

import re
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path

import pytest

from .conftest import SKILL


def _load():  # type: ignore[no-untyped-def]
    path = str(SKILL / "dev" / "live-smoke")
    spec = spec_from_loader("live_smoke", SourceFileLoader("live_smoke", path))
    assert spec is not None
    mod = module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


ls = _load()


def test_settings_mirror_install_hooks() -> None:
    from_install = (SKILL / "scripts").as_posix()
    import sys
    sys.path.insert(0, from_install)
    try:
        from context_vigil import install
    finally:
        sys.path.remove(from_install)
    s = ls.build_settings(2, Path("/d"))
    assert ls.HOOKS == install.HOOKS
    for event, matcher, name in install.HOOKS:
        entry = s["hooks"][event][0]
        assert entry.get("matcher") == matcher
        assert entry["hooks"][0]["command"] == f'"{ls.LAUNCHER}" hook {name}'
    assert s["env"]["CONTEXT_VIGIL_COOLDOWN_SECONDS"] == "0"
    assert s["statusLine"]["command"].endswith('capture.sh"')


def test_slug_and_claude_args() -> None:
    assert ls.project_slug("/a/b.c_d") == "-a-b-c-d"
    narrow = ls.claude_args(Path("/s.json"), "haiku", False)
    assert "--allowedTools" in narrow and "--dangerously-skip-permissions" not in narrow
    assert "--dangerously-skip-permissions" in ls.claude_args(Path("/s.json"), "haiku", True)


def test_redact_masks_secret_shapes() -> None:
    text = ("key sk-FAKE-canary-123456 and AKIAFAKECANARY123456 then "
            "MY_API_KEY=abc OTHER_TOKEN_X=def SECRET=ghi plain=ok")
    out = ls.redact(text)
    for bad in ("sk-FAKE-canary-123456", "AKIAFAKECANARY123456", "=abc", "=def", "=ghi"):
        assert bad not in out
    assert "plain=ok" in out and "[redacted]" in out


def test_peek_redacts_pane_text(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    import argparse
    pane = "hello\nexport X_TOKEN=sk-FAKE-canary-99\n"
    monkeypatch.setattr(ls, "pane_text", lambda lines=60: pane)
    ls.cmd_peek(argparse.Namespace(n=10))
    out = capsys.readouterr().out
    assert "sk-FAKE-canary" not in out and "hello" in out


def test_wait_timeout_tail_is_redacted(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    pane = "AWS_SECRET_ACCESS_KEY=sk-FAKE-canary-77\n"
    monkeypatch.setattr(ls, "pane_text", lambda lines=60: pane)
    ok, why = ls.wait_until(lambda: False, 0, "x", 0)
    assert not ok and "sk-FAKE-canary" not in why


def test_state_helpers_hide_secrets() -> None:
    rec = {"headless": False, "api_token": "x", "env": "y", "nested": {"a": 1},
           "transcript_size": 3}
    assert ls.safe_fields(rec) == {"headless": False, "transcript_size": 3}
    doc = {"w": [{"context_window": {"used_percentage": 4, "x": {"y": 1}}}]}
    assert ls.find_window_dicts(doc) == [{"used_percentage": 4}]


# --- round 3 (adversarial): private, unpredictable paths; wider redaction ----------

def _mode(path: Path) -> int:
    import stat
    return stat.S_IMODE(path.stat().st_mode)


REDACTION_SAMPLES = [
    (f"ghp_{'A' * 36}", "AAAAAAAA"), (f"github_pat_{'B' * 30}", "BBBBBBBB"),
    ("xoxb-1234567890-abcdefghij", "abcdefghij"), (f"AIza{'C' * 35}", "CCCCCCCC"),
    ("-----BEGIN RSA PRIVATE KEY-----", "PRIVATE KEY"), ("my_token=abcdef123", "abcdef123"),
    ("password: hunter2222", "hunter2222"), ("Authorization: Bearer abc.def.ghi", "abc.def"),
    ('"api_key": "zzzzzzzzzz"', "zzzzzzzzzz"),
    ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.x", "eyJhbG"),
    ("https://user:hunter3hunter3@example.invalid/x", "hunter3"),
    # formats the skill's own scanner used to mask (kept here after it was removed)
    ("https://hooks.slack.com/services/T00000000/B00000000/" + "X" * 24, "XXXXXXXX"),
    ("npm_" + "E" * 36, "EEEEEEEE"), ("hf_" + "G" * 34, "GGGGGGGG"),
    ("SG." + "H" * 22 + "." + "I" * 43, "HHHHHHHH"), ("dop_v1_" + "a" * 64, "aaaaaaaa"),
    ("AGE-SECRET-KEY-1" + "J" * 58, "JJJJJJJJ"),
    ("SIGNING_KEY=" + "4f9a8b7c6d5e4f3a" * 2, "4f9a8b7c6d5e"),
    ("PRIVATE_KEY=abcdEFGH1234ijklMNOP", "abcdEFGH1234"),
    ("--token abcdef0123456789abcd", "abcdef0123456789"),
    ("--api-key abcdef0123456789abcd", "abcdef0123456789"),
    ("pwd=Hunter2Hunter2", "Hunter2Hunter2"), ("PASS=Tr0ub4dor&3x", "Tr0ub4dor"),
    ("passphrase: Tr0ub4dor&3x", "Tr0ub4dor"),
    ("Authorization: Basic dXNlcjpwYXNzd29yZDEyMzQ1Njc4", "dXNlcjpwYXNzd29yZDEyMzQ1Njc4"),
    ("Authorization: Token abcdef0123456789abcd", "abcdef0123456789"),
    ("sk-ant-FAKE-canary-123456789", "canary"), ("AKIA" + "Q" * 16, "QQQQQQQQ"),
    ("rk_live_" + "Z" * 20, "ZZZZZZZZ"), ("glpat-" + "y" * 22, "yyyyyyyy"),
    ("ya29." + "w" * 24, "wwwwwwww"),
]


@pytest.mark.parametrize("text, fragment", REDACTION_SAMPLES)
def test_redaction_covers_common_key_shapes(text: str, fragment: str) -> None:
    out = ls.redact(f"before {text} after")
    assert fragment not in out and "[redacted]" in out
    assert out.startswith("before") and out.endswith("after")


def test_state_redacts_by_value_as_well_as_key_name() -> None:
    rec = {"model_id": "sk-ant-FAKE-canary-123456789", "headless": True, "api_token": "x",
           "transcript_size": 5, "unknown_field": "kept out"}
    out = ls.safe_fields(rec)
    assert "sk-ant-FAKE" not in str(out) and out["headless"] is True
    assert "api_token" not in out and "unknown_field" not in out
    assert out["model_id"] == "[redacted]"
    doc = {"context_window": {"label": "ghp_" + "Z" * 36, "used_percentage": 3}}
    assert ls.find_window_dicts(doc) == [{"label": "[redacted]", "used_percentage": 3}]


def test_sandbox_and_state_are_private_and_unpredictable(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(ls.tempfile, "gettempdir", lambda: str(tmp_path))
    first, second = ls.make_sandbox(None, 2), ls.make_sandbox(None, 2)
    assert first["sandbox"] != second["sandbox"]
    private = ls.private_dir()
    assert _mode(private) == 0o700 and private.stat().st_uid == __import__("os").getuid()
    for info in (first, second):
        root = Path(info["sandbox"])
        assert root.parent == private.resolve() and _mode(root) == 0o700
        assert not root.name.endswith(__import__("time").strftime("%Y%m%d"))
    assert ls.state_file().parent == private


def test_state_file_must_be_private_and_ours(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    import pytest
    monkeypatch.setattr(ls.tempfile, "gettempdir", lambda: str(tmp_path))
    ls.save_state({"sandbox": "/nowhere"})
    assert _mode(ls.state_file()) == 0o600
    assert ls.load_state()["sandbox"] == "/nowhere"
    ls.state_file().chmod(0o644)
    with pytest.raises(SystemExit):
        ls.load_state()
    private = ls.private_dir()
    ls.state_file().chmod(0o600)
    private.chmod(0o777)
    with pytest.raises(SystemExit):
        ls.load_state()
    private.chmod(0o700)


def test_headless_prompt_keeps_notes_out_of_the_repo() -> None:
    prompt = ls.headless_prompt()
    assert "notes-path" in prompt and "./notes.md" not in prompt


@pytest.mark.parametrize(("screen", "choice"), [
    ("Quick safety check\n ❯ 1. No, exit\n   2. Yes, I trust this folder\n", "1. No, exit"),
    ("Quick safety check\n   1. No, exit\n ❯ 2. Yes, I trust this folder\n",
     "2. Yes, I trust this folder"),
    ("no menu here\n", None),
])
def test_trust_cursor_line_reads_the_selected_option(screen: str, choice: object) -> None:
    assert ls.trust_cursor_line(screen) == choice
    assert (re.search(ls.TRUST_RE, screen) is not None) == (choice is not None)


@pytest.mark.parametrize(("screen", "ready"), [
    ("─" * 40 + "\n❯ Try \"fix lint errors\"\n" + "─" * 40 + "\n", True),
    ("  ? for shortcuts\n", True),
    ("Quick safety check\n ❯ 1. No, exit\n   2. Yes, I trust this folder\n", False),
])
def test_ready_re_sees_the_input_box_not_the_trust_menu(screen: str, ready: bool) -> None:
    assert (re.search(ls.READY_RE, screen) is not None) is ready
    assert (re.match(ls.TRUST_OPTION_RE, ls.trust_cursor_line(screen) or "") is not None) \
        is (not ready)
