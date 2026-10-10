"""Hostile payloads and CLI identity for the shell-aware guard (WF-265 PR A,
verdict changes 1-8). Every probe quoted in the verdict is here."""
import json
import os
from pathlib import Path

import pytest
from factories import make_card

from scripts import guard
from scripts.guard import bash_check, decide

REPO = Path(__file__).resolve().parents[2]
OWN = REPO / "plugins" / "overseer" / "scripts" / "cli.py"
CWD = str(REPO)
CLI = f"python3 {OWN}"
ROOTS = [Path("/state"), Path("/plugins"), Path("/cfg")]
CARD = make_card("WF-012")


def verdict(command, **kw):
    kw.setdefault("cwd", CWD)
    return bash_check(command, **kw)


def denied(command, needle=None, **kw):
    allowed, why = verdict(command, **kw)
    assert not allowed, command
    if needle is not None:
        assert why and needle in why, (command, why)


def allowed(command, **kw):
    ok, why = verdict(command, **kw)
    assert ok, (command, why)


class TestFailClosed:
    """Change 1: unknown or unbalanced shell state denies."""

    @pytest.mark.parametrize("command", [
        f"{CLI} show WF-1 $'\\'' ; rm -rf x",  # the verdict's ANSI-C probe
        f"{CLI} show WF-1 $\"x\"",
        f"{CLI} show WF-1 'unbalanced",
        f'{CLI} show WF-1 "unbalanced',
        f"{CLI} show WF-1 && (rm -rf x)",
        f"{CLI} show WF-1 ; {{ rm -rf x; }}",
        f"{CLI} show WF-1 {{a,b}}",
        f"{CLI} show WF-1 ${{x:-y}}",
        "cat <<'EOF' > /tmp/x\nunterminated",
        "cat <<EOF > /tmp/x",
    ])
    def test_cannot_parse(self, command):
        denied(command, "cannot parse command")

    def test_old_fail_open_case_is_closed(self):
        denied("echo 'unbalanced", "cannot parse command", roots=ROOTS)

    def test_deny_flows_through_decide_with_the_distinct_reason(self):
        payload = {"tool_name": "Bash", "cwd": CWD, "tool_input": {"command": "echo 'x"}}
        reason = decide(payload, [CARD], ROOTS).deny_reason
        assert "WF-012 in flight" in reason and "GUARD: cannot parse command" in reason


class TestSubstitution:
    """Change 2 (process substitution) and OR-7 (single-quoted text is inert)."""

    @pytest.mark.parametrize("command", [
        f"{CLI} set-section WF-1 --section Plan --file <(cat /repo/secret)",  # the verdict's probe
        f"{CLI} set-section WF-1 --section Plan --file >(cat)",
        f"{CLI} show WF-1 $(cat /repo/secret)",
        f"{CLI} show WF-1 `cat /repo/secret`",
        f'{CLI} log-progress WF-1 --note "a $(cat /repo/secret)"',
        "echo $(cat /repo/secret) > /tmp/x.md",
        f"{CLI} bootstrap --title t --brief \"$(cat /repo/secret)\"",
        "cat <<EOF > /tmp/x\n$(cat /repo/secret)\nEOF",
    ])
    def test_live_substitution_denied_with_remedy(self, command):
        denied(command, "live command substitution")
        _ok, why = verdict(command)
        assert "--text-file" in why and "--brief-file" in why

    @pytest.mark.parametrize("command", [
        f"{CLI} log-progress WF-1 --note 'uses `ls` and $(pwd) in the brief' --tokens 0",
        f"{CLI} bootstrap --title t --brief 'run `make` then $(make test)'",
        f"{CLI} set-section WF-1 --section Plan --text 'see <(x) and >(y)'",
        f"{CLI} bootstrap --title t --brief - <<'EOF'\nthe plan: `a` $(b) <(c)\n/repo/src/app.py\nEOF",
        f"{CLI} log-progress WF-1 --note \\$\\(x\\) --tokens 0",
    ])
    def test_inert_text_is_allowed(self, command):
        allowed(command)


class TestRedirects:
    """Change 3: redirects on a CLI segment are checked."""

    @pytest.mark.parametrize("command", [
        f"{CLI} show WF-1 > /repo/notes.md",  # the verdict's probe
        f"{CLI} show WF-1 >> /repo/notes.md",
        f"{CLI} show WF-1 &> /repo/notes.md",
        f"{CLI} show WF-1 2> /repo/err.txt",
        f"{CLI} show WF-1 >| /repo/notes.md",
        f"{CLI} show WF-1 <> /repo/notes.md",
        f"{CLI} show WF-1 >& /repo/notes.md",
        f"{CLI} show WF-1 < /repo/src/app.py",  # reads repo source
        "git status > /repo/notes.md",
        "cd /repo > /repo/x",
        "> /repo/truncate-me",
    ])
    def test_non_scratch_target_denied(self, command):
        denied(command, "redirect")

    @pytest.mark.parametrize("command", [
        f"{CLI} show WF-1 > /tmp/out.txt",
        f"{CLI} show WF-1 > /dev/null",
        f"{CLI} show WF-1 2>&1",
        f"{CLI} show WF-1 >&2",
        f"{CLI} show WF-1 > /dev/null 2>&1",
        f"{CLI} show WF-1 &>/dev/null",
        "git status 2>/dev/null",
        f"{CLI} show WF-1 <<< 'a string'",
        f"{CLI} show WF-1 < /tmp/in.txt",
    ])
    def test_scratch_dev_null_and_fd_dups_allowed(self, command):
        allowed(command)

    def test_here_string_operand_checked_for_substitution(self):
        denied(f'{CLI} set-section WF-1 --section Plan --text - <<< "$(cat /repo/secret)"',
               "live command substitution")

    def test_here_string_is_not_confused_with_a_heredoc(self):
        # a `<<<` must not swallow the following lines as a heredoc body
        denied(f"{CLI} show WF-1 <<< x\nrm -rf /repo/src")

    def test_glob_in_redirect_target(self):
        denied("echo hi > /tmp/*", "no globs")


class TestHeredocRules:
    """Change 4."""

    def test_unquoted_newline_separates_commands(self):
        denied(f"{CLI} resume\nrm -rf x")  # the design's newline hole
        denied(f"{CLI} resume\n\nrm -rf x")
        allowed(f"{CLI} resume\n{CLI} board")

    def test_backslash_newline_is_a_continuation_not_a_separator(self):
        allowed(f"{CLI} \\\n  resume")
        denied(f"{CLI} resume \\\n; rm -rf x")

    @pytest.mark.parametrize("delim", ["'EOF'", '"EOF"', "\\EOF", "'EO'F"])
    def test_quoted_delimiters_make_the_body_inert_data(self, delim):
        allowed(f"cat > /tmp/x.md <<{delim}\n$(rm -rf /) `x`\n; rm -rf /repo\n/repo/src/app.py\nEOF")

    def test_unquoted_delimiter_body_is_scanned(self):
        denied("cat > /tmp/x.md <<EOF\n$(cat /repo/secret)\nEOF", "live command substitution")
        denied("cat > /tmp/x.md <<EOF\n`cat /repo/secret`\nEOF", "live command substitution")
        allowed("cat > /tmp/x.md <<EOF\nplain $HOME text ; rm -rf /\nEOF")

    def test_rest_of_the_operator_line_is_still_scanned(self):
        denied("cat <<'EOF' > /repo/x\nbody\nEOF")
        allowed("cat <<'EOF' > /tmp/x\nbody\nEOF")

    def test_command_after_the_terminator_is_scanned(self):
        denied("cat > /tmp/x <<'EOF'\nbody\nEOF\nrm -rf /repo/src")

    def test_terminator_must_be_the_whole_line(self):
        # `EOF ` and ` EOF` do not terminate, so the body swallows the rm and
        # the heredoc is unterminated -> cannot parse
        denied("cat > /tmp/x <<'EOF'\nbody\n EOF\nrm -rf /repo/src", "cannot parse")

    def test_several_heredocs_one_line(self):
        allowed("cat > /tmp/x <<'A' <<'B'\none\nA\ntwo $(x)\nB")

    def test_dash_heredoc(self):
        allowed("cat > /tmp/x <<-'EOF'\n\tbody $(x)\n\tEOF")

    def test_comment_does_not_swallow_the_separator(self):
        denied(f"{CLI} resume # harmless\nrm -rf x")

    def test_continuation_in_unquoted_body_joins_lines(self):
        # `$\<newline>(` is a live substitution once the continuation is applied
        denied("cat > /tmp/x <<EOF\n$\\\n(cat /repo/secret)\nEOF", "live command substitution")

    def test_continuation_in_quoted_body_is_literal(self):
        allowed("cat > /tmp/x <<'EOF'\n$\\\n(cat /repo/secret)\nEOF")


class TestGlobs:
    """Change 5."""

    @pytest.mark.parametrize("command", [
        "cat /tmp/*/x",
        "grep -rn foo /plugins/*/scripts",
        "grep foo * /plugins/overseer/scripts/cli.py",
        "cat /plugins/overs?er/scripts/cli.py",
        "cat /plugins/overseer/scripts/[c]li.py",
        "echo hi > /tmp/x*",
        "cat /tmp/a /tmp/*",
    ])
    def test_glob_denied(self, command):
        denied(command, "no globs", roots=ROOTS)

    def test_quoted_and_escaped_globs_are_literal(self):
        allowed("grep -n 'def .*cmd' /plugins/overseer/scripts/cli.py", roots=ROOTS)
        allowed("echo hi > /tmp/lit\\*eral")

    def test_glob_check_does_not_apply_to_cli_segments(self):
        allowed(f"{CLI} log-progress WF-1 --note x* --tokens 0")


class TestMultiEdit:
    """Change 6."""

    def test_multiedit_denied_for_the_orchestrator(self):
        payload = {"tool_name": "MultiEdit", "cwd": CWD,
                   "tool_input": {"file_path": "/tmp/x.md", "edits": []}}
        assert "WF-012 in flight" in decide(payload, [CARD], ROOTS).deny_reason

    def test_agents_may_multiedit(self):
        payload = {"tool_name": "MultiEdit", "cwd": CWD, "agent_id": "a1",
                   "agent_type": "overseer:overseer-implementer", "tool_input": {}}
        assert decide(payload, [CARD], ROOTS).deny_reason is None


class TestExistingOrchestrationCommandsStillAllowed:
    """The commands the orchestrate SKILL teaches must keep passing."""

    @pytest.mark.parametrize("command", [
        f'python3 "{OWN.parent}/../scripts/cli.py" --root . resume',
        f"{CLI} --root . bootstrap --title 'T' --complexity S --brief 'do the thing' --labels a,b",
        f"{CLI} --root . dispatch-prep WF-1 --stage impl-review --role reviewer --round 1 --slot A --advance",
        f"{CLI} --root . set-stage WF-1 awaiting-merge",
        f"{CLI} --root . set-section WF-1 --section Verification --text-file /tmp/v.md",
        f"{CLI} --root . append-body WF-1 Decisions --text-file /tmp/d.md",
        f"{CLI} --root . set-section WF-1 --section Plan --text - <<'EOF'\nplan `x` $(y)\nEOF",
        f'{CLI} --root . log-progress WF-1 --note "reviewed; fixed && merged" --tokens 12k',
        f"{CLI} --root . block WF-1 --reason 'user: waiting on a decision'",
        f"{CLI} --root . handover",
        f"{CLI} --root . vigil begin",
        "git add -A && git commit -m 'feat: x' && git push -u origin feat/WF-1-x",
        "git -C /tmp/wt status",
        "gh pr create --title t --body b",
        "gh pr view 12",
        f"cd {REPO} && {CLI} --root . show WF-1",
        "cat > /tmp/brief.md <<'EOF'\n# Brief\n`code` and $(not run)\nEOF",
        "echo hello > /tmp/x.txt",
        "printf 'x' >> /tmp/x.txt",
        "pwd",
    ])
    def test_allowed(self, command):
        allowed(command, roots=ROOTS)


class TestCdTracking:
    """A `cd` changes what a relative CLI path means."""

    def test_cd_elsewhere_makes_the_relative_cli_not_found(self, tmp_path):
        denied(f"cd {tmp_path} && python3 plugins/overseer/scripts/cli.py resume", "cli not found")

    def test_cd_to_a_variable_makes_the_cwd_unknown(self):
        denied('cd "$X" && python3 plugins/overseer/scripts/cli.py resume', "no working directory")

    def test_cd_followed_by_a_pipe_makes_the_cwd_unknown(self):
        denied(f"cd {REPO} | python3 plugins/overseer/scripts/cli.py resume", "no working directory")

    def test_cd_into_the_repo_then_relative_cli(self):
        allowed(f"cd {REPO} && python3 plugins/overseer/scripts/cli.py resume", cwd="/elsewhere")


class TestCliIdentity:
    """Changes 7 and 8: identity is the REAL path; no lexical normalisation."""

    @pytest.fixture
    def cache(self, tmp_path, monkeypatch):
        """A marketplace-cache layout: versioned overseer dirs (one orphaned),
        a sibling vigil, a different plugin, all under <config>/plugins."""
        cfg = tmp_path / "cfg"
        base = cfg / "plugins" / "cache" / "pip-skills"

        def plugin(name, version, manifest=True, plugin_name=None):
            root = base / name / version
            (root / "scripts").mkdir(parents=True)
            (root / "scripts" / "cli.py").write_text("print('hi')\n")
            if manifest:
                (root / ".claude-plugin").mkdir()
                (root / ".claude-plugin" / "plugin.json").write_text(
                    json.dumps({"name": plugin_name or name, "version": version}))
            return root

        own = plugin("overseer", "0.25.1")
        old = plugin("overseer", "0.24.0")
        orphan = plugin("overseer", "0.23.0")
        (orphan / ".orphaned_at").write_text("1")
        vigil = plugin("vigil", "0.2.0")
        census = plugin("census", "1.0.0")
        nomanifest = plugin("overseer", "0.1.0", manifest=False)
        (base / "overseer" / "0.0.9").mkdir(parents=True)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
        monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
        monkeypatch.setattr(guard, "_own_cli", lambda: Path(os.path.realpath(own / "scripts" / "cli.py")))
        guard._manifest_name.cache_clear()
        yield {"own": own, "old": old, "orphan": orphan, "vigil": vigil, "census": census,
               "nomanifest": nomanifest, "tmp": tmp_path, "base": base}
        guard._manifest_name.cache_clear()

    def py(self, root):
        return f"python3 {root}/scripts/cli.py --root . resume"

    def test_the_skills_mandated_form_resolves_to_own(self, cache):
        own = cache["own"]
        allowed(f'python3 "{own}/skills/orchestrate/../../scripts/cli.py" --root . resume')

    def test_plugin_root_variable_form(self, cache, monkeypatch):
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(cache["own"]))
        allowed('python3 "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" --root . resume')
        allowed("python3 $CLAUDE_PLUGIN_ROOT/scripts/cli.py --root . resume")

    def test_other_installed_versions_incl_orphaned_are_accepted(self, cache):
        allowed(self.py(cache["old"]))
        allowed(self.py(cache["orphan"]))

    def test_sibling_vigil_in_the_cache_is_accepted(self, cache):
        allowed(self.py(cache["vigil"]))

    def test_other_plugins_cli_denied(self, cache):
        denied(self.py(cache["census"]), "not a ledger CLI")

    def test_missing_or_wrong_manifest_denies(self, cache):
        denied(self.py(cache["nomanifest"]), "not a ledger CLI")
        (cache["old"] / ".claude-plugin" / "plugin.json").write_text("{not json")
        guard._manifest_name.cache_clear()
        denied(self.py(cache["old"]), "not a ledger CLI")

    def test_missing_file_names_the_resolved_path(self, cache):
        gone = cache["base"] / "overseer" / "0.0.9"
        denied(self.py(gone), f"cli not found at {gone.resolve()}/scripts/cli.py")

    def test_symlinked_intermediate_dir_pointing_outside_is_denied(self, cache):
        evil = cache["tmp"] / "evil"
        (evil / "scripts").mkdir(parents=True)
        (evil / "scripts" / "cli.py").write_text("print('pwned')\n")
        (evil / ".claude-plugin").mkdir()
        (evil / ".claude-plugin" / "plugin.json").write_text('{"name": "overseer"}')
        (cache["base"] / "overseer" / "link").symlink_to(evil)
        denied(self.py(cache["base"] / "overseer" / "link"), "not a ledger CLI")

    def test_dotdot_through_a_symlink_resolves_on_the_real_path(self, cache):
        # lexically `<link>/../scripts/cli.py` would normalise into the plugin
        # tree; really `link/..` is the symlink's TARGET parent
        outside = cache["tmp"] / "outside"
        (outside / "deep").mkdir(parents=True)
        (outside / "scripts").mkdir()
        (outside / "scripts" / "cli.py").write_text("print('pwned')\n")
        link = cache["own"] / "skills"
        link.mkdir()
        (link / "orchestrate").symlink_to(outside / "deep")
        denied(f"python3 {link}/orchestrate/../scripts/cli.py --root . resume", "not a ledger CLI")

    def test_symlink_to_the_real_cli_is_allowed(self, cache):
        alias = cache["tmp"] / "alias.py"
        alias.symlink_to(cache["own"] / "scripts" / "cli.py")
        allowed(f"python3 {alias} --root . resume")

    def test_dangling_symlink_denied(self, cache):
        dangling = cache["tmp"] / "dangling.py"
        dangling.symlink_to(cache["tmp"] / "nowhere.py")
        denied(f"python3 {dangling} resume", "cli not found")

    def test_relative_path_with_no_cwd_denies(self, cache):
        denied("python3 scripts/cli.py resume", "no working directory", cwd=None)

    def test_relative_path_against_the_payload_cwd(self, cache):
        allowed("python3 scripts/cli.py resume", cwd=str(cache["own"]))

    @pytest.mark.parametrize("command", [
        "python3 -c 'print(1)'",
        "python3 -m pytest",
        "python3 -I -c 'import os'",
        "python3 -u",
    ])
    def test_dash_c_dash_m_and_bare_python_are_not_cli_calls(self, cache, command):
        denied(command, "not a ledger CLI")

    def test_bare_interpreter_is_denied(self, cache):
        denied("python3")

    def test_interpreter_flags_are_skipped(self, cache):
        allowed(f"python3 -I -u -B {cache['own']}/scripts/cli.py resume")

    def test_unresolvable_variable_denies(self, cache):
        denied("python3 $SOMEWHERE/scripts/cli.py resume", "cannot resolve")

    def test_a_file_that_is_not_scripts_cli_py_is_denied(self, cache):
        other = cache["own"] / "scripts" / "other.py"
        other.write_text("print(1)\n")
        denied(f"python3 {other}", "not a ledger CLI")

    def test_repo_layout_covers_the_sibling_vigil_and_nothing_else(self, tmp_path, monkeypatch):
        plugins = tmp_path / "repo" / "plugins"
        for name in ("overseer", "vigil", "census"):
            (plugins / name / "scripts").mkdir(parents=True)
            (plugins / name / "scripts" / "cli.py").write_text("print(1)\n")
            (plugins / name / ".claude-plugin").mkdir()
            (plugins / name / ".claude-plugin" / "plugin.json").write_text(f'{{"name": "{name}"}}')
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
        monkeypatch.setattr(guard, "_own_cli", lambda: (plugins / "overseer" / "scripts" / "cli.py").resolve())
        guard._manifest_name.cache_clear()
        allowed(f"python3 {plugins}/vigil/scripts/cli.py --root . context")
        allowed("python3 plugins/overseer/scripts/cli.py resume", cwd=str(tmp_path / "repo"))
        denied(f"python3 {plugins}/census/scripts/cli.py read", "not a ledger CLI")

    def test_deny_message_prints_the_resolved_path_and_the_allowed_roots(self, cache):
        _ok, why = verdict(self.py(cache["census"]))
        assert str(cache["census"].resolve()) in why
        assert str((cache["tmp"] / "cfg" / "plugins").resolve()) in why

    def test_find_sibling_cli_prefers_the_newest_manifest_version(self, cache):
        newer = cache["base"] / "vigil" / "0.3.0"
        (newer / "scripts").mkdir(parents=True)
        (newer / "scripts" / "cli.py").write_text("print(1)\n")
        (newer / ".claude-plugin").mkdir()
        (newer / ".claude-plugin" / "plugin.json").write_text('{"name": "vigil", "version": "0.3.0"}')
        guard._manifest_name.cache_clear()
        assert guard.find_sibling_cli("vigil") == (newer / "scripts" / "cli.py").resolve()

    def test_find_sibling_cli_none_when_absent(self, cache):
        assert guard.find_sibling_cli("nonesuch") is None
