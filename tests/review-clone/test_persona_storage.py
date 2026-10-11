"""RA-8 roots from CLAUDE_CONFIG_DIR + read-only legacy fallback, RA-9 round-trips, CR-10 CLI."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import scripts.persona_io as pio

PLUGIN = Path(__file__).resolve().parents[2] / "plugins/review-clone"
SCRIPT = PLUGIN / "scripts/persona_io.py"


@pytest.fixture
def layout(tmp_path, monkeypatch):
    """The default layout: CLAUDE_CONFIG_DIR -> tmp, legacy ~/.claude -> tmp/home."""
    cfg, home = tmp_path / "cfg", tmp_path / "home"
    cfg.mkdir()
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    monkeypatch.delenv("REVIEW_CLONE_ROOT", raising=False)
    root = cfg / "review-clone" / "personas"
    monkeypatch.setattr(pio, "_DEFAULT_ROOT", root)
    monkeypatch.setattr(pio, "PERSONA_ROOT", root)
    return cfg, home, root


def legacy_persona(home, alias="old", body="## Rules\n"):
    d = home / ".claude" / "review-clone" / alias
    d.mkdir(parents=True)
    pio.write_persona(d / "PERSONA.md", {"alias": alias, "drift_log": [], "drift_log_archived_count": 0}, body)
    return d


def test_default_root_derives_from_claude_config_dir(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "REVIEW_CLONE_ROOT"}
    env["CLAUDE_CONFIG_DIR"] = str(tmp_path / "acct")
    env["HOME"] = str(tmp_path / "h")
    out = subprocess.run([sys.executable, "-c",
                          "import sys; sys.path.insert(0, 'scripts'); import persona_io as p; "
                          "print(p.PERSONA_ROOT); print(p.commands_dir())"],
                         cwd=PLUGIN, env=env, capture_output=True, text=True, check=True).stdout.split()
    assert out == [str(tmp_path / "acct/review-clone/personas"), str(tmp_path / "acct/commands")]


def test_default_root_without_config_dir_is_dot_claude(tmp_path):
    env = {k: v for k, v in os.environ.items() if k not in ("REVIEW_CLONE_ROOT", "CLAUDE_CONFIG_DIR")}
    env["HOME"] = str(tmp_path / "h")
    out = subprocess.run([sys.executable, "-c",
                          "import sys; sys.path.insert(0, 'scripts'); import persona_io as p; print(p.PERSONA_ROOT)"],
                         cwd=PLUGIN, env=env, capture_output=True, text=True, check=True).stdout.strip()
    assert out == str(tmp_path / "h/.claude/review-clone/personas")


def test_two_accounts_do_not_see_each_others_personas(tmp_path):
    def personas(cfg):
        env = {k: v for k, v in os.environ.items() if k != "REVIEW_CLONE_ROOT"}
        env.update(CLAUDE_CONFIG_DIR=str(cfg), HOME=str(tmp_path / "h"))
        return json.loads(subprocess.run([sys.executable, str(SCRIPT), "list"], env=env,
                                         capture_output=True, text=True, check=True).stdout)["personas"]
    a, b = tmp_path / "a", tmp_path / "b"
    env_a = {**os.environ, "CLAUDE_CONFIG_DIR": str(a), "HOME": str(tmp_path / "h")}
    env_a.pop("REVIEW_CLONE_ROOT", None)
    fm, body = tmp_path / "fm.json", tmp_path / "b.md"
    fm.write_text(json.dumps({"alias": "jen", "drift_log": [], "drift_log_archived_count": 0}))
    body.write_text("## Rules")
    subprocess.run([sys.executable, str(SCRIPT), "write", "--alias", "jen", "--frontmatter", str(fm),
                    "--body", str(body)], env=env_a, check=True, capture_output=True)
    assert personas(a) == ["jen"] and personas(b) == []


def test_legacy_persona_is_found_but_never_written(layout):
    cfg, home, root = layout
    d = legacy_persona(home)
    before = (d / "PERSONA.md").read_bytes()
    assert pio.list_personas() == ["old"] and pio.persona_exists("old")
    found = pio.locate_persona("old")
    assert found == (d / "PERSONA.md", "legacy")
    assert pio.persona_path("old") == d / "PERSONA.md"            # read location
    assert pio.persona_write_path("old") == root / "old" / "PERSONA.md"
    # a drift entry migrates the persona into the new root and leaves the legacy file alone
    entry = tmp = cfg / "e.json"
    entry.write_text(json.dumps({"date": "d", "summary": "s"}))
    assert pio.main(["drift", "--alias", "old", "--entry", str(tmp)]) == 0
    assert (d / "PERSONA.md").read_bytes() == before
    assert pio.read_frontmatter(root / "old" / "PERSONA.md")["drift_log"] == [{"date": "d", "summary": "s"}]
    assert pio.locate_persona("old")[1] == "current"


def test_current_root_wins_over_legacy_and_listing_dedupes(layout):
    cfg, home, root = layout
    legacy_persona(home, "same", "legacy")
    pio.write_persona(root / "same" / "PERSONA.md", {"alias": "same"}, "current")
    legacy_persona(home, "only-old")
    assert pio.list_personas() == ["only-old", "same"]
    assert "current" in pio._split_body(pio.persona_path("same"))


def test_overridden_root_has_no_legacy_fallback(layout, tmp_path, monkeypatch):
    cfg, home, root = layout
    legacy_persona(home)
    monkeypatch.setattr(pio, "PERSONA_ROOT", tmp_path / "elsewhere")
    assert pio.legacy_roots() == [] and pio.list_personas() == []


def test_paths_command_reports_account_dirs(layout, capsys):
    cfg, home, root = layout
    assert pio.main(["paths", "--alias", "jen"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["persona_dir"] == str(root / "jen")
    assert out["command_file"] == str(cfg / "commands" / "review-as-jen.md")
    assert out["raw_dir"].startswith(str(root))
    assert out["persona"] is None
    assert pio.main(["paths", "--alias", "../x"]) == 2


# ---- CR-10 CLI by absolute path
def run_cli(tmp_path, *args):
    env = {**os.environ, "REVIEW_CLONE_ROOT": str(tmp_path / "root"), "HOME": str(tmp_path / "h")}
    p = subprocess.run([sys.executable, "-I", str(SCRIPT), *map(str, args)], cwd=tmp_path, env=env,
                       capture_output=True, text=True)
    return p.returncode, json.loads(p.stdout)


def test_cli_write_read_update_roundtrip_from_an_unrelated_cwd(tmp_path):
    fm = tmp_path / "fm.json"
    body = tmp_path / "body.md"
    fm.write_text(json.dumps({"alias": "jen", "handles": ["j"], "last_scanned_at": "2026-05-01T00:00:00Z",
                              "disclaimer": 'say "hi"\nline two: x # not a comment',
                              "drift_log": [], "drift_log_archived_count": 0}))
    body.write_text("## Voice & tone\nx\n")
    assert run_cli(tmp_path, "write", "--alias", "jen", "--frontmatter", fm, "--body", body)[0] == 0
    code, out = run_cli(tmp_path, "read", "--alias", "jen")
    assert code == 0 and out["source"] == "current"
    assert out["frontmatter"]["disclaimer"] == 'say "hi"\nline two: x # not a comment'
    assert out["body"].startswith("## Voice")
    part = tmp_path / "part.json"
    part.write_text(json.dumps({"last_scanned_at": "2026-06-01T00:00:00Z", "output_default": "all-chat"}))
    assert run_cli(tmp_path, "update", "--alias", "jen", "--set", part)[0] == 0
    assert run_cli(tmp_path, "read", "--alias", "jen")[1]["frontmatter"]["output_default"] == "all-chat"
    assert run_cli(tmp_path, "list")[1]["personas"] == ["jen"]
    assert run_cli(tmp_path, "read", "--alias", "nobody")[1]["status"] == "not-found"


def test_cli_rejects_bad_alias_and_bad_json(tmp_path):
    fm = tmp_path / "fm.json"
    fm.write_text("[1]")
    body = tmp_path / "b.md"
    body.write_text("x")
    assert run_cli(tmp_path, "write", "--alias", "../evil", "--frontmatter", fm, "--body", body)[0] == 2
    assert run_cli(tmp_path, "write", "--alias", "ok", "--frontmatter", fm, "--body", body)[0] == 2
    assert run_cli(tmp_path, "write", "--alias", "Upper", "--frontmatter", tmp_path / "nope", "--body", body)[0] == 2


# ---- RA-9
@pytest.mark.parametrize("val", [
    'has "quotes"', "back\\slash", "multi\nline", "tab\there", "colon: here", "hash # here",
    "- dash", "[bracket", "{brace", " lead", "trail ", "unicode é ✓", "https://x.y/z", "a, b",
])
def test_scalars_round_trip(tmp_path, val):
    path = tmp_path / "PERSONA.md"
    pio.write_persona(path, {"alias": "x", "note": val, "items": [val], "drift_log": [{"date": "d", "summary": val}],
                             "drift_log_archived_count": 0}, "b")
    fm = pio.read_frontmatter(path)
    assert fm["note"] == val and fm["items"] == [val] and fm["drift_log"][0]["summary"] == val


def test_newline_value_stays_one_line(tmp_path):
    path = tmp_path / "PERSONA.md"
    pio.write_persona(path, {"a": "x\ny: z"}, "b")
    head = path.read_text().split("---")[1]
    assert head.strip().count("\n") == 0


def test_over_indented_frontmatter_is_an_error_not_silently_dropped(tmp_path):
    path = tmp_path / "PERSONA.md"
    path.write_text("---\nalias: x\nwindow:\n  months: 6\n      since: z\n---\n\nbody\n")
    with pytest.raises(ValueError, match="indentation"):
        pio.read_frontmatter(path)


def test_crlf_and_bom_files_parse(tmp_path):
    path = tmp_path / "PERSONA.md"
    path.write_bytes("\ufeff---\r\nalias: x\r\nhandles:\r\n  - a\r\n---\r\n\r\nbody\r\n".encode())
    assert pio.read_frontmatter(path) == {"alias": "x", "handles": ["a"]}


def test_legacy_unescaped_quotes_still_read(tmp_path):
    path = tmp_path / "PERSONA.md"
    path.write_text('---\nnote: "C:\\path: x"\nother: "plain: v"\n---\n\nb\n')
    fm = pio.read_frontmatter(path)
    assert fm["note"] == "C:\\path: x" and fm["other"] == "plain: v"


def test_persona_is_written_before_the_archive(tmp_path, monkeypatch):
    path = tmp_path / "PERSONA.md"
    pio.write_persona(path, {"alias": "t", "drift_log": [{"date": str(i), "summary": "s"} for i in range(20)],
                             "drift_log_archived_count": 0}, "b")
    real = pio.write_private

    def crash_on_archive(p, text):
        if p.name == "drift.log":
            raise OSError("disk full")
        return real(p, text)
    monkeypatch.setattr(pio, "write_private", crash_on_archive)
    with pytest.raises(OSError):
        pio.append_drift_entry(path, {"date": "new", "summary": "s"})
    fm = pio.read_frontmatter(path)
    assert fm["drift_log"][-1]["date"] == "new" and fm["drift_log_archived_count"] == 1
    monkeypatch.setattr(pio, "write_private", real)
    pio.append_drift_entry(path, {"date": "newer", "summary": "s"})
    assert (tmp_path / "drift.log").read_text().count("\n") == 1  # never duplicated


def test_persona_files_are_private(tmp_path):
    path = tmp_path / "p" / "PERSONA.md"
    pio.write_persona(path, {"alias": "x"}, "b")
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700


def test_write_refuses_a_symlink(tmp_path):
    victim = tmp_path / "victim"
    victim.write_text("keep")
    link = tmp_path / "PERSONA.md.tmp"
    link.symlink_to(victim)
    with pytest.raises(ValueError):
        pio.write_persona(tmp_path / "PERSONA.md", {"a": 1}, "b")
    assert victim.read_text() == "keep"
