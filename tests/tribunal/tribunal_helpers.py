"""Shared helpers for the tribunal hook tests: hook import, corpus, shell oracle.

Nothing here touches real user state: the oracle shells run with an empty
environment from an empty temp directory, and the hook never executes anything.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PLUGIN = REPO / "plugins" / "tribunal"
HOOKS = PLUGIN / "hooks"
SKILL = PLUGIN / "skills" / "reckoning" / "SKILL.md"
THREADS_GRAPHQL = HOOKS / "queries" / "threads.graphql"

if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

import allow_gh  # noqa: E402  (path set up above)

READ_QUERY = THREADS_GRAPHQL.read_text(encoding="utf-8")
RESOLVE_MUTATION = (
    'mutation { resolveReviewThread(input: {threadId: "PRRT_kwDOAbc123"}) '
    "{ thread { isResolved } } }"
)
SHA = "0123456789abcdef0123456789abcdef01234567"


def allowed(cmd: str) -> bool:
    argv = allow_gh.tokenize(cmd)
    return argv is not None and allow_gh.decide(argv)


def read_cmd(
    *,
    query: str = READ_QUERY,
    owner: str = "octo",
    repo: str = "repo",
    number: str = "12",
    owner_flag: str = "-f",
    number_flag: str = "-F",
    paginate: bool = True,
) -> str:
    return (
        "gh api graphql"
        + (" --paginate" if paginate else "")
        + f" {owner_flag} owner='{owner}' -f repo='{repo}' {number_flag} number={number}"
        + f" -f query='{query}'"
    )


def resolve_cmd(mutation: str = RESOLVE_MUTATION, flag: str = "-f") -> str:
    return f"gh api graphql {flag} query='{mutation}'"


# --------------------------------------------------------------------------- oracle

_SHELLS = {
    "bash": ["/usr/bin/env", "-i", "PATH=/nonexistent", "/bin/bash", "-r", "-c"],
    "zsh": ["/usr/bin/env", "-i", "/bin/zsh", "-f", "-c"],
}
_cache: dict[tuple[str, str], list[str] | None] = {}


def shell_available(shell: str) -> bool:
    return Path({"bash": "/bin/bash", "zsh": "/bin/zsh"}[shell]).exists()


def require_shell(shell: str) -> None:
    if shell_available(shell):
        return
    if shell == "zsh" and sys.platform == "darwin":
        pytest.fail("/bin/zsh must exist on darwin")
    pytest.skip(f"{shell} not installed")


def oracle(shell: str, cmd: str, cwd: Path) -> list[str] | None:
    """The words `shell` really produces for `cmd`, via the printf builtin only.

    Run only on strings the tokenizer already accepted. `bash -r` refuses redirections and
    /-prefixed commands, so even a tokenizer bug cannot execute anything here.
    """
    key = (shell, cmd)
    if key not in _cache:
        script = "printf '%s\\0' " + cmd
        proc = subprocess.run(
            [*_SHELLS[shell], script],
            cwd=cwd,
            capture_output=True,
            timeout=20,
            check=False,
        )
        if proc.returncode != 0:
            _cache[key] = None
        else:
            parts = proc.stdout.decode("utf-8", "surrogateescape").split("\0")
            _cache[key] = parts[:-1]
    return _cache[key]


def assert_oracle_agrees(cmd: str, cwd: Path) -> None:
    argv = allow_gh.tokenize(cmd)
    assert argv is not None
    for shell in ("bash", "zsh"):
        require_shell(shell)
        assert oracle(shell, cmd, cwd) == argv, (shell, cmd)


# --------------------------------------------------------------------------- corpus

# Every command shape tribunal:reckoning emits (bare and quoted forms of the same argv).
ALLOW_CORPUS = [
    "gh auth status",
    "gh repo view --json nameWithOwner -q .nameWithOwner",
    "gh repo view --json isFork -q .isFork",
    "gh repo view --json parent --jq .parent.nameWithOwner",
    "gh repo view octo/repo --json nameWithOwner",
    "gh pr view",
    "gh pr view 12",
    "gh pr view --json number -q .number",
    "gh pr view 12 --json state,title -q '.state + \" \" + .title'",
    "gh pr view 12 --json headRefName -q .headRefName",
    "gh pr view 12 --repo octo/repo --json headRefOid -q .headRefOid",
    "gh pr view 12 -R octo/repo --json headRefOid --jq=.headRefOid",
    "gh pr view feature/x --json number",
    "gh pr list --head feature/x --json number,title --jq 'length'",
    "gh pr list --head 'feature/x' --json number,title,url",
    "gh pr list --state open --limit 30 --json number",
    "gh pr list -R octo/repo --head=feature/x",
    f"gh api repos/octo/repo/commits/{SHA}/check-runs -q '.check_runs[]' --paginate",
    "gh api repos/octo/repo/pulls/12/comments --paginate --jq '.[] | {id, node_id, user: .user.login, body}'",
    "gh api repos/octo/repo/issues/12/comments --paginate --jq '.[] | {id, user: .user.login}'",
    "gh api repos/octo/repo/pulls/12/reviews --paginate --jq '.[] | {id, state}'",
    f"gh api 'repos/octo/repo/contents/src/app.py?ref={SHA}'",
    f'gh api "repos/octo/repo/contents/src/app.py?ref={SHA}&page=2"',
    f"gh api repos/octo/repo/commits/{SHA}/status --jq '.statuses[] | {{context, state}}'",
    "gh api repos/octo/repo/pulls/12/comments --cache 1h",
    read_cmd(),
    read_cmd(paginate=False),
    read_cmd(owner_flag="--raw-field", number_flag="--field"),
    read_cmd(query=" ".join(READ_QUERY.split())),
    resolve_cmd(),
    resolve_cmd(flag="--raw-field"),
    resolve_cmd(RESOLVE_MUTATION.replace("{", "{ ").replace("}", " }")),
]
