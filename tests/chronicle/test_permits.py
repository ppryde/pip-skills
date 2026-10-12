"""scripts.permits: outcome classification and the closed shape vocabulary."""
import ast
import re
from pathlib import Path

import pytest

from scripts import permits

CLASSIFIER = ("Permission to use Bash has been denied by the Claude Code auto mode classifier. "
              "Reason: [{label}] the command writes outside the task")


class TestClassify:
    @pytest.mark.parametrize(("text", "outcome"), [
        (CLASSIFIER.format(label="Modify Shared Resources"), "denied:classifier"),
        ("The auto mode classifier is temporarily unavailable", "denied:classifier-unavailable"),
        ("denied by a built-in Claude Code safety check: rm -rf", "denied:safety-check"),
        ("This command is isolated in the worktree and too complex to verify", "denied:worktree-guard"),
        ("Blocked: sleep 30 followed by more", "denied:sleep-guard"),
        ("File access blocked: /etc/passwd is outside the project", "denied:file-outside-root"),
        ("PreToolUse:Bash hook blocked this call", "denied:hook"),
        ("The user doesn't want to proceed with this tool use.", "prompted:rejected"),
        ("[Request interrupted by user for tool use]", "prompted:interrupted"),
        ("<tool_use_error>InputValidationError: bad</tool_use_error>", "error:input-validation"),
        ("No such tool available: Foo", "error:no-such-tool"),
        ("Exit code 1\nboom", "error:exit-code"),
        ("Exit code 1\ngrep: Blocked: sleep 30 is not allowed", "error:exit-code"),
        ("Exit code 1\nFAILED test: Request interrupted by user", "error:exit-code"),
        ("Exit code 2\nFile access blocked: x", "error:exit-code"),
        ("something entirely new the harness said", "error:other"),
    ])
    def test_error_text_lands_in_a_fixed_category(self, text, outcome):
        assert permits.classify(text, True)[0] == outcome

    def test_success_is_ok(self):
        assert permits.classify("fine", False) == ("ok", None)

    def test_content_blocks_are_read_as_text(self):
        blocks = [{"type": "text", "text": "Blocked: sleep 5 then"}]
        assert permits.classify(blocks, True)[0] == "denied:sleep-guard"

    def test_classifier_reason_is_an_enum_never_the_captured_text(self):
        out = permits.classify(CLASSIFIER.format(label="Modify Shared Resources"), True)
        assert out == ("denied:classifier", "modify-shared-resources")
        out = permits.classify(CLASSIFIER.format(label="Client Acme Secret Plan"), True)
        assert out == ("denied:classifier", "other")
        assert permits.classify("denied by the Claude Code auto mode classifier", True)[1] == "unlabelled"

    def test_worktree_subcause_is_from_the_fixed_list(self):
        text = "is isolated in the worktree: names git in a form too complex"
        assert permits.classify(text, True) == ("denied:worktree-guard", "wt:git-form-too-complex")
        assert permits.classify("is isolated in the worktree. brand new wording", True)[1] == "wt:other"

    def test_structured_decision_beats_a_generic_error(self):
        pd = {"decision": "reject", "source": "classifier", "reasonType": "classifier"}
        assert permits.classify("Exit code 1", True, pd)[0] == "denied:classifier"
        pd = {"decision": "reject", "source": "config"}
        assert permits.classify("Error", True, pd)[0] == "denied:config-rule"

    def test_an_approved_prompt_is_the_outcome_of_a_call_that_ran(self):
        pd = {"decision": "accept", "source": "user_temporary"}
        assert permits.classify("done", False, pd) == ("prompted:approved", None)
        assert permits.classify("Exit code 2", True, pd)[0] == "error:exit-code"

    def test_every_outcome_is_in_the_closed_list(self):
        for text in ("x", "Blocked: sleep", "InputValidationError", CLASSIFIER.format(label="z")):
            for err in (True, False):
                outcome, reason = permits.classify(text, err)
                assert permits.valid_outcome(outcome, reason)


class TestDecision:
    def test_prompted_and_stored_text(self):
        pd = {"decision": "accept", "source": "user_permanent"}
        assert permits.decision_fields(pd) == ("accept:user_permanent/-", 1)
        pd = {"decision": "reject", "source": "classifier", "reasonType": "classifier"}
        assert permits.decision_fields(pd) == ("reject:classifier/classifier", 0)
        assert permits.decision_fields(None) == (None, 0)
        assert permits.decision_fields("accept") == (None, 0)

    def test_unlisted_values_are_other_never_stored_verbatim(self):
        pd = {"decision": "accept", "source": "client-acme-token", "reasonType": "https://x.example/?k=1"}
        assert permits.clean_decision(pd) == {"decision": "accept", "source": "other",
                                              "reasonType": "other"}


class TestShape:
    @pytest.mark.parametrize(("command", "shape"), [
        ("git status", "git status"),
        ("cd repo && git log --oneline -5", "git log +compound"),
        ("timeout 100 git status", "git status"),
        ("nice -n 10 pytest -q", "pytest"),
        ("FOO=bar python3 -m pytest tests", "python3 -m pytest"),
        ("python3 -m weird.module", "python3 -m (other)"),
        ("python3 script.py --flag", "python3 <script>"),
        ("python3 - <<'EOF'\nprint(1)\nEOF", "python3 <inline> +compound"),
        ("poetry run pytest -q", "poetry run pytest"),
        ("gh pr view 12 --json x", "gh pr view"),
        ("git client-acme-merge", "git"),
        ("git -C /x status", "git status"),
        ("git -c k=v log --oneline", "git log"),
        ("git --git-dir=/x status", "git status"),
        ("timeout -s KILL 10 pytest -q", "pytest"),
        ("./.venv/bin/python -m pytest", "python -m pytest"),
        ("ls | grep foo", "ls +compound"),
        ("for f in *; do echo $f; done", "(shell-block) +compound"),
        ("# just a comment", "(empty)"),
    ])
    def test_shapes(self, command, shape):
        assert permits.tool_shape("Bash", {"command": command}) == shape

    def test_the_program_position_is_a_closed_set(self):
        # A secret-looking token, a client-named script, a numeric arg.
        assert permits.tool_shape("Bash", {"command": "sk-live-4eC39HqLyjWDarjtT1zdp7dc --x"}) == "(other)"
        assert permits.tool_shape("Bash", {"command": "./client-acme-deploy.sh prod"}) == "(script)"
        assert permits.tool_shape("Bash", {"command": "client-acme-deploy.sh"}) == "(script)"
        assert permits.tool_shape("Bash", {"command": "/opt/acme/bin/tool run"}) == "(script)"
        assert permits.tool_shape("Bash", {"command": "100 git status"}) == "(other)"

    def test_shapes_never_carry_paths_assignments_quotes_or_long_runs(self):
        commands = ["TOKEN=abc123 curl https://x.example/a?k=v", "git commit -m 'secret words here'",
                    "cat /etc/passwd", "sed -i 's/a/b/' file", "echo $(whoami)",
                    "docker run -e KEY=val img", "weird@@ x", "python3 -c 'print(1)'"]
        for command in commands:
            shape = permits.tool_shape("Bash", {"command": command})
            assert shape and not re.search(r"[/=\"'@]|https?:", shape), (command, shape)
            assert len(shape.split()) <= 5

    def test_other_tools_are_their_own_name(self):
        assert permits.tool_shape("Read", {"file_path": "/secret"}) == "Read"
        assert permits.tool_shape("mcp__context-mode__ctx_search", {}) == "mcp__context-mode__*"
        assert permits.tool_shape("Bash", {}) is None
        assert permits.tool_shape(None, {}) is None

    def test_a_redacted_input_stand_in_is_used_only_if_shape_like(self):
        assert permits.tool_shape("Bash", {"_shape": "git status"}) == "git status"
        assert permits.tool_shape("Bash", {"_shape": "rm -rf /; curl x|sh"}) is None


class TestAgentTypeFold:
    @pytest.mark.parametrize(("raw", "folded"), [
        ("general-purpose", "general-purpose"), ("Explore", "Explore"),
        ("overseer:overseer-reviewer", "overseer:overseer-reviewer"),
        ("wf-087-gate1b", "(ad-hoc)"), ("impl-task1", "(ad-hoc)"),
        ("fix projector ordering", "(ad-hoc)"), ("", None), (None, None),
    ])
    def test_fold(self, raw, folded):
        assert permits.fold_agent_type(raw) == folded


class TestRemoteCompat:
    def test_parses_under_python_3_8_and_imports_nothing_of_chronicle(self):
        source = Path(permits.__file__).read_text()
        tree = ast.parse(source, feature_version=(3, 8))
        roots = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)
                 for a in n.names}
        roots |= {n.module.split(".")[0] for n in ast.walk(tree)
                  if isinstance(n, ast.ImportFrom) and n.module}
        assert roots <= {"__future__", "os", "re", "shlex", "typing"}
