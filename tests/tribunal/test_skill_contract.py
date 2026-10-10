"""The skill's own commands vs the hook: drift fails CI instead of silently adding prompts.

Every `gh ...` command the skill text tells the model to run (fenced bash blocks and inline
code spans) must be auto-approved by the hook, or be listed in EXPECTED_PROMPT. `git` commands
must NOT be approved: the hook never widens to git (recorded here as scope).
"""
from __future__ import annotations

import re

from tribunal_helpers import REPO, SHA, SKILL, THREADS_GRAPHQL, allow_gh, allowed

SKILL_FILES = [SKILL, *sorted((SKILL.parent / "references").glob("*.md"))]

# Regression window (WF-264 PR 1 -> PR 2): the three forms in today's SKILL.md that the
# parser hook correctly declines. PR 2 rewrites them (quoting, two-step branch lookup,
# `--jq` projection instead of a redirect) and then empties this set; the final assertion
# below flips to `== set()`.
EXPECTED_PROMPT = {
    "gh pr list --head $(git branch --show-current) --json number,title --jq 'length'",
    f"gh api repos/octo/repo/contents/src/app.py?ref={SHA}",
    "gh api ... --paginate > /tmp/pr_comments.json",
}

# Prose, not commands: a bare command family name or an instruction to the human.
NOT_RUN = {"gh api", "gh auth login"}

PLACEHOLDERS = {
    "{owner}": "octo",
    "{repo}": "repo",
    "{pr_number}": "12",
    "{number}": "12",
    "{head_sha}": SHA,
    "{path}": "src/app.py",
    "{branch_name}": "feature/x",
    "<branch_name>": "feature/x",
    "<thread_id_from_step_3d>": "PRRT_kwDOAbc123",
    "<commit_id>": SHA,
    "<review_commit>": SHA,
    "<path>": "src/app.py",
}

FENCE = re.compile(r"```bash\n(.*?)```", re.S)
INLINE = re.compile(r"`((?:gh|git) [^`\n]*)`")


def substitute(text: str) -> str:
    for key, val in PLACEHOLDERS.items():
        text = text.replace(key, val)
    return text


def commands() -> list[tuple[str, str]]:
    """(source file name, command) for every gh/git command in the skill text."""
    found: list[tuple[str, str]] = []
    for path in SKILL_FILES:
        text = path.read_text(encoding="utf-8")
        for block in FENCE.findall(text):
            for cmd in re.split(r"\n(?=(?:gh|git) )", block.strip()):
                found.append((path.name, substitute(cmd.strip())))
        stripped = FENCE.sub("", text)
        for span in INLINE.findall(stripped):
            found.append((path.name, substitute(span.strip())))
    return found


def test_skill_commands_were_found() -> None:
    cmds = commands()
    assert len([c for _, c in cmds if c.startswith("gh ")]) >= 15
    assert any("graphql" in c and "reviewThreads" in c for _, c in cmds)
    assert any("resolveReviewThread" in c for _, c in cmds)


def test_every_gh_command_is_allowed_or_expected_to_prompt() -> None:
    bad = []
    for name, cmd in commands():
        if not cmd.startswith("gh ") or cmd in NOT_RUN or cmd in EXPECTED_PROMPT:
            continue
        if not allowed(cmd):
            bad.append((name, cmd[:120]))
    assert not bad, f"gh commands in the skill that the hook would not approve: {bad}"


def test_expected_prompt_entries_really_prompt_and_are_still_in_the_skill() -> None:
    seen = {cmd for _, cmd in commands()}
    for cmd in EXPECTED_PROMPT:
        assert cmd in seen, f"stale EXPECTED_PROMPT entry (no longer in the skill): {cmd}"
        argv = allow_gh.tokenize(cmd)
        assert argv is None or not allow_gh.decide(argv), cmd


def test_expected_prompt_set_is_exactly_the_three_known_forms() -> None:
    # PR 2 changes this to `== set()`.
    assert len(EXPECTED_PROMPT) == 3


def test_git_commands_are_not_auto_approved() -> None:
    git = [(n, c) for n, c in commands() if c.startswith("git ")]
    assert git, "expected the skill to mention git commands"
    for name, cmd in git:
        assert not allowed(cmd), (name, cmd)


def test_embedded_thread_query_matches_the_hook_file() -> None:
    """The query in the skill and hooks/queries/threads.graphql are one document."""
    canonical = allow_gh.lex_graphql(THREADS_GRAPHQL.read_text(encoding="utf-8"))
    assert canonical
    embedded = []
    for path in SKILL_FILES:
        for block in FENCE.findall(path.read_text(encoding="utf-8")):
            m = re.search(r"-f query='\s*(query\(.*?)'\s*$", block, re.S)
            if m:
                embedded.append(allow_gh.lex_graphql(m.group(1)))
    assert embedded, "no embedded thread query found in the skill"
    assert all(e == canonical for e in embedded)


def test_embedded_resolve_mutation_matches_the_canonical_tokens() -> None:
    found = []
    for path in SKILL_FILES:
        for m in re.finditer(r"-f query='(mutation \{.*?)'", path.read_text(encoding="utf-8")):
            found.append(allow_gh.lex_graphql(substitute(m.group(1)), True))
    assert found
    assert all(f == allow_gh.RESOLVE_TOKENS for f in found)


def test_repo_root_resolves() -> None:
    assert (REPO / "plugins" / "tribunal" / "hooks" / "allow_gh.py").is_file()
