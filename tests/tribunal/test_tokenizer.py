"""Tokenizer: accepts only a tiny safe subset, and agrees with real bash and zsh."""
from __future__ import annotations

import pytest
from tribunal_helpers import ALLOW_CORPUS, allow_gh, assert_oracle_agrees

tokenize = allow_gh.tokenize

ACCEPTED = [
    ("gh pr view 1", ["gh", "pr", "view", "1"]),
    ("gh   pr\tview 1", ["gh", "pr", "view", "1"]),
    ("gh pr view ''", ["gh", "pr", "view", ""]),
    ('gh pr view ""', ["gh", "pr", "view", ""]),
    ("gh pr view '' x ''", ["gh", "pr", "view", "", "x", ""]),
    ("a'b'\"c\"d", ["abcd"]),
    ("gh 'pr view'", ["gh", "pr view"]),
    ("gh -q '.a | .b'", ["gh", "-q", ".a | .b"]),
    ("gh x='line1\nline2'", ["gh", "x=line1\nline2"]),
    ("gh 'it'\"'\"'s'", ["gh", "it's"]),
    ("gh 'a;b&c|d>e<f(g)h{i}j$k`l\\m#n~o*p?q[r]s!t'", ["gh", "a;b&c|d>e<f(g)h{i}j$k`l\\m#n~o*p?q[r]s!t"]),
    ('gh "a;b&c|d>e<f(g)h{i}j#n~o*p?q[r]s"', ["gh", "a;b&c|d>e<f(g)h{i}j#n~o*p?q[r]s"]),
    ("gh a=b=c :,%@+._/-", ["gh", "a=b=c", ":,%@+._/-"]),
    ("gh '=ls'", ["gh", "=ls"]),
    ("  gh  ", ["gh"]),
]

REJECTED = [
    "",
    "   ",
    "\t",
    "gh pr view 1; echo PWNED",
    "gh pr view 1 && id",
    "gh pr view 1 || id",
    "gh pr view 1 | sh",
    "gh pr view 1 & id",
    "gh pr view $(id)",
    "gh pr view `id`",
    "gh pr view $HOME",
    "gh pr view ${HOME}",
    "gh pr view 1\nrm -rf x",
    "gh pr view 1\r",
    "gh pr view 1 > /tmp/x",
    "gh pr view 1 >> /tmp/x",
    "gh pr view 1 < /etc/passwd",
    "gh pr view 1 <<< x",
    "gh pr view <(id)",
    "gh pr view (id)",
    "gh pr view {a,b}",
    "gh pr view *",
    "gh pr view ?",
    "gh pr view [a]",
    "gh pr view ~",
    "gh pr view ~root",
    "gh pr view #comment",
    "gh pr view !!",
    "gh pr view \\n",
    "gh pr view 1\\\n2",
    "gh pr view $'\\x41'",
    "gh pr view $\"x\"",
    "gh pr view ^x",
    "=ls",
    "gh =ls",
    "gh pr view \"$HOME\"",
    "gh pr view \"`id`\"",
    "gh pr view \"a\\b\"",
    "gh pr view \"a!b\"",
    "gh pr view 'unterminated",
    "gh pr view \"unterminated",
    "gh pr view 1\x00",
    "gh pr view 'a\x00b'",
    "gh pr view 'a\rb'",
    "gh pr view 'a\x1bb'",
    "gh pr view 'café'",
    "ｇh pr view 1",  # full-width g
    "gh pr view é",
    "gh pr view 1 " + "x" * 20001,
]


@pytest.mark.parametrize(("cmd", "words"), ACCEPTED)
def test_accepts_subset(cmd: str, words: list[str]) -> None:
    assert tokenize(cmd) == words


@pytest.mark.parametrize("cmd", REJECTED)
def test_rejects_everything_else(cmd: str) -> None:
    assert tokenize(cmd) is None


@pytest.mark.parametrize("ch", list(";&|<>(){}$`\\#~*?[]!\"'\n\r\x00^"))
def test_every_unquoted_metachar_is_rejected(ch: str) -> None:
    if ch in "\"'":
        assert tokenize(f"gh a{ch}b") is None  # unterminated
    else:
        assert tokenize(f"gh a{ch}b") is None
        assert tokenize(f"gh {ch}") is None


def test_non_string_is_rejected() -> None:
    assert tokenize(None) is None  # type: ignore[arg-type]
    assert tokenize(b"gh") is None  # type: ignore[arg-type]


@pytest.mark.parametrize("cmd", [c for c, _ in ACCEPTED if "\n" not in c or "'" in c] + ALLOW_CORPUS)
def test_agrees_with_real_bash_and_zsh(cmd: str, tmp_path) -> None:  # noqa: ANN001
    assert_oracle_agrees(cmd, tmp_path)


def test_oracle_catches_a_disagreeing_string(tmp_path) -> None:  # noqa: ANN001
    """Guard the guard: the oracle really exposes shell semantics the tokenizer rejects."""
    from tribunal_helpers import oracle, require_shell

    require_shell("bash")
    require_shell("zsh")
    assert oracle("bash", "gh $'a'", tmp_path) == ["gh", "a"]
    assert oracle("zsh", "gh {a,b}", tmp_path) == ["gh", "a", "b"]
    assert tokenize("gh $'a'") is None
    assert tokenize("gh {a,b}") is None
