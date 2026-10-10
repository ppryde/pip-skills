"""scripts/shellscan.py — the shell-aware scanner behind the guard (WF-265)."""
import pytest

from scripts.shellscan import scan


def words(command):
    return [list(c.words) for c in scan(command).commands]


class TestQuoteState:
    def test_single_quoted_substitution_is_inert(self):
        s = scan("python3 cli.py log-progress WF-1 --note 'ran `ls` and $(pwd)'")
        assert not s.live and s.error is None
        assert words("echo 'a $(x) `y`'") == [["echo", "a $(x) `y`"]]

    @pytest.mark.parametrize("command", [
        'echo "a $(x)"',
        'echo "a `x`"',
        "echo $(x)",
        "echo `x`",
        "x <(cat y)",
        "x >(cat)",
        "cat < <(x)",
        "echo a$(x)b",
    ])
    def test_live_substitution_is_flagged(self, command):
        assert scan(command).live

    def test_escaped_dollar_paren_is_inert(self):
        assert not scan(r"echo \$(x) \`y\`").live
        assert not scan('echo "\\$(x) \\`y\\`"').live

    @pytest.mark.parametrize("command", [
        "echo 'unbalanced",
        'echo "unbalanced',
        "echo \\",
        "python3 cli.py show WF-1 $'\\'' ; rm -rf x",  # ANSI-C quoting flips quote state
        'echo $"locale"',
        "echo (x)",
        "( echo x )",
        "echo {a,b}",
        "{ echo x; }",
        "echo ${x:-y}",
        'echo "${x:-"y"}"',
        'echo "${HOME:-$(x)}"',
        "echo >",
        "cat <<EOF\nbody",  # unterminated heredoc
        "cat <<EOF",
    ])
    def test_unmodelled_state_fails_closed(self, command):
        assert scan(command).error

    def test_plain_parameter_expansion_is_fine(self):
        s = scan('python3 "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" resume')
        assert s.error is None and not s.live
        assert words('python3 "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" resume')[0][1] == (
            "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py"
        )

    def test_comment_ends_at_newline_and_does_not_swallow_the_separator(self):
        assert words("python3 cli.py resume # note\nrm -rf x") == [
            ["python3", "cli.py", "resume"], ["rm", "-rf", "x"]]
        # a # inside a word is not a comment
        assert words("echo a#b") == [["echo", "a#b"]]

    def test_backslash_newline_is_a_continuation(self):
        assert words("echo a\\\nb") == [["echo", "ab"]]
        assert words("echo a \\\n  b") == [["echo", "a", "b"]]

    def test_backslash_newline_inside_single_quotes_is_literal(self):
        assert words("echo 'a\\\nb'") == [["echo", "a\\\nb"]]


class TestSeparators:
    @pytest.mark.parametrize("command", [
        "a ; b", "a && b", "a || b", "a | b", "a & b", "a |& b", "a\nb", "a;b",
    ])
    def test_every_separator_splits(self, command):
        assert words(command) == [["a"], ["b"]]

    def test_unquoted_newline_is_a_separator_not_whitespace(self):
        assert words("python3 cli.py resume\nrm -rf x") == [
            ["python3", "cli.py", "resume"], ["rm", "-rf", "x"]]

    def test_quoted_newline_is_not(self):
        assert words('python3 cli.py log-progress WF-1 --note "a\nb"') == [
            ["python3", "cli.py", "log-progress", "WF-1", "--note", "a\nb"]]

    def test_separator_following_each_command_is_recorded(self):
        cmds = scan("cd /x && a | b ; c\nd").commands
        assert [c.sep for c in cmds] == ["&&", "|", ";", "\n", ""]


class TestRedirects:
    def test_redirect_is_not_a_word(self):
        c = scan("cat > /tmp/x").commands[0]
        assert c.words == ("cat",)
        assert [(r.op, r.target, r.writes) for r in c.redirects] == [(">", "/tmp/x", True)]

    @pytest.mark.parametrize("command,op", [
        ("a >> /t", ">>"), ("a >| /t", ">|"), ("a &> /t", "&>"), ("a &>> /t", "&>>"),
        ("a 2> /t", ">"), ("a 1>/t", ">"), ("a >/t", ">"), ("a <> /t", "<>"),
    ])
    def test_output_operators(self, command, op):
        (r,) = scan(command).commands[0].redirects
        assert (r.op, r.target, r.writes) == (op, "/t", True)

    def test_input_redirect_does_not_write(self):
        (r,) = scan("a < /t").commands[0].redirects
        assert (r.op, r.writes) == ("<", False)

    def test_fd_duplication_is_not_a_file(self):
        rs = scan("a 2>&1 >&2 >&-").commands[0].redirects
        assert all(r.fd_dup for r in rs) and len(rs) == 3
        assert not any(r.writes for r in rs)

    def test_greater_ampersand_with_a_filename_is_a_file_redirect(self):
        (r,) = scan("a >& /t").commands[0].redirects
        assert r.writes and not r.fd_dup

    def test_fd_prefix_is_not_a_word(self):
        assert words("a 2>/dev/null") == [["a"]]
        assert words("a 2 >/dev/null") == [["a", "2"]]  # a spaced digit is an argument

    def test_quoted_digit_is_a_word_not_an_fd(self):
        assert words("a '2'>/t") == [["a", "2"]]

    def test_redirect_with_no_target_is_an_error(self):
        assert scan("a >").error
        assert scan("a > ; b").error
        assert scan("a > >").error

    def test_here_string_is_an_operand_not_a_heredoc(self):
        s = scan("cat <<< 'hello world'\necho next")
        assert s.error is None and not s.live
        assert words("cat <<< 'hello world'\necho next") == [["cat"], ["echo", "next"]]

    def test_here_string_operand_is_scanned_for_substitution(self):
        assert scan('cat <<< "$(x)"').live
        assert scan("cat <<<$(x)").live


class TestHeredocs:
    def test_quoted_body_is_inert_and_its_words_are_not_segmented(self):
        s = scan("cat > /tmp/x <<'EOF'\n$(rm -rf /) `x` ; rm -rf /repo\n/repo/secret.py\nEOF\necho done")
        assert s.error is None and not s.live
        assert [list(c.words) for c in s.commands] == [["cat"], ["echo", "done"]]

    @pytest.mark.parametrize("delim", ["'EOF'", '"EOF"', "\\EOF", "'EO'F", 'E"O"F', "EO\\F"])
    def test_any_quote_or_backslash_in_the_delimiter_makes_the_body_inert(self, delim):
        s = scan(f"cat <<{delim}\n$(x) `y`\nEOF")
        assert s.error is None and not s.live

    def test_unquoted_delimiter_body_is_scanned(self):
        assert scan("cat <<EOF\nhello $(x)\nEOF").live
        assert scan("cat <<EOF\nhello `x`\nEOF").live
        assert scan("cat <<EOF\nhello <(x)\nEOF").live
        assert not scan("cat <<EOF\nhello $HOME and ; rm -rf /\nEOF").live

    def test_unquoted_body_honours_backslash_escapes(self):
        assert not scan("cat <<EOF\n\\$(x) \\`y\\`\nEOF").live

    def test_unquoted_body_backslash_newline_continuation(self):
        # `\<newline>` joins the lines, so the terminator below is NOT a terminator line
        s = scan("cat <<EOF\nfoo \\\nEOF\nEOF\necho after")
        assert s.error is None
        assert [list(c.words) for c in s.commands] == [["cat"], ["echo", "after"]]
        # ... and a continuation can glue `$` to `(`
        assert scan("cat <<EOF\n$\\\n(x)\nEOF").error is None

    def test_quoted_body_backslash_newline_is_literal(self):
        s = scan("cat <<'EOF'\nfoo \\\nEOF\necho after")
        assert [list(c.words) for c in s.commands] == [["cat"], ["echo", "after"]]

    def test_rest_of_the_operator_line_is_still_scanned(self):
        (cat, _next) = scan("cat <<'EOF' > /repo/x\nbody\nEOF\necho hi").commands
        assert [r.target for r in cat.redirects] == ["/repo/x"]

    def test_body_starts_after_the_next_unquoted_newline(self):
        # the quoted newline belongs to the operator line, not the body
        s = scan("cat <<'EOF' --note 'a\nb'\nbody $(x)\nEOF\necho hi")
        assert s.error is None and not s.live
        assert [list(c.words) for c in s.commands] == [["cat", "--note", "a\nb"], ["echo", "hi"]]

    def test_several_heredocs_take_bodies_in_order(self):
        s = scan("cat <<'A' <<B\nfirst $(x)\nA\nsecond $(y)\nB\necho hi")
        assert s.live  # B is unquoted and its body is live
        s = scan("cat <<A <<'B'\nfirst\nA\nsecond $(y)\nB\necho hi")
        assert s.error is None and not s.live
        assert [list(c.words) for c in s.commands] == [["cat"], ["echo", "hi"]]

    def test_terminator_is_the_whole_line(self):
        s = scan("cat <<'EOF'\n EOF\nEOF \nEOF\necho hi")
        assert s.error is None
        assert [list(c.words) for c in s.commands] == [["cat"], ["echo", "hi"]]

    def test_dash_strips_leading_tabs_only(self):
        s = scan("cat <<-'EOF'\n\t\tbody\n\t\tEOF\necho hi")
        assert [list(c.words) for c in s.commands] == [["cat"], ["echo", "hi"]]
        # without the dash a tab-indented terminator does not terminate
        assert scan("cat <<'EOF'\nbody\n\tEOF").error

    def test_terminator_on_the_last_line_needs_no_trailing_newline(self):
        assert scan("cat <<'EOF'\nbody\nEOF").error is None

    def test_empty_body(self):
        assert scan("cat <<'EOF'\nEOF").error is None

    def test_heredoc_in_a_chain(self):
        s = scan("cat <<'EOF' | tee /tmp/x\nbody\nEOF")
        assert [list(c.words) for c in s.commands] == [["cat"], ["tee", "/tmp/x"]]


class TestGlobs:
    def test_unquoted_glob_chars_flagged_per_word(self):
        c = scan("cat /tmp/*/x 'a*' b? [c]").commands[0]
        assert list(c.globs) == [False, True, False, True, True]

    def test_escaped_glob_is_not_a_glob(self):
        assert not any(scan("cat /tmp/\\*").commands[0].globs)

    def test_glob_in_redirect_target(self):
        (r,) = scan("cat > /tmp/*").commands[0].redirects
        assert r.glob
