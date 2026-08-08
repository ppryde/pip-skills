# review-clone — inline PR posting + docstring pass

**Date:** 2026-05-26
**Plugin:** `review-clone`
**Status:** Approved (design)

## Problem

`review-as` review mode currently emits findings only to chat or to a local
file (`.review-clone/last-review-<alias>.md`). It never touches the GitHub PR.
The user wants the persona to post its findings **onto the PR**, with every
posted message clearly attributed to the clone via a `[From <alias>]:` prefix —
so a human reading the PR can never mistake a cloned persona for the real
reviewer.

A second, unrelated-but-bundled strand: several functions in the plugin's
Python scripts lack docstrings. Add lightweight one-liners while we are here.

## Strand A — inline PR posting

### A1. New output option

Step 5 of `review-as` review mode ("Output mode selector") gains a fourth
choice:

4. **Post inline to PR** (`post-inline-pr`)

It is selectable interactively and persistable as `output_default` via
`persona_io.write_persona`, exactly like the existing three options.

### A2. Findings carry a line anchor

To post inline, each finding must record where it fires:

- `path` — repo-relative file path
- `line` — the line number **in the file at HEAD** the comment anchors to
- `side` — `RIGHT` for added/context lines, `LEFT` for removed lines

These are drawn from the diff hunk the rule fired on (Step 3 already walks the
per-file diff). Findings that cannot be cleanly anchored to a line present in
the diff are **not dropped** — they are collected and posted as a single
general PR comment (see A4).

### A3. Posting mechanism

1. Resolve the PR for the current branch:
   `gh pr view --json number,headRepositoryOwner,headRepository -q ...`
   (or `gh pr view --json number` plus repo from `gh repo view`). If there is
   **no open PR** for the branch → tell the user, fall back to the file/chat
   output, do not post.
2. Submit **one** review batching all anchorable findings:
   ```bash
   gh api repos/{owner}/{repo}/pulls/{n}/reviews \
     -f event=COMMENT \
     -f 'comments[][path]=<path>' \
     -F 'comments[][line]=<line>' \
     -f 'comments[][side]=RIGHT' \
     -f 'comments[][body]=[From <alias>]: <severity> — <comment>

   Citation: <url>'
   ```
   Each inline comment body is prefixed `[From <alias>]:`.
3. Un-anchorable findings (A2 fallback) are concatenated into the review's
   summary `body` (also prefixed `[From <alias>]:`), or posted via
   `gh pr comment` if no anchorable findings exist.

`<alias>` is the persona's alias slug verbatim (the `<alias>` from
`/review-as-<alias>`), not a display name.

### A4. Confirmation gate (outward-facing)

Posting public comments on a PR is outward-facing and effectively
irreversible, so the skill **never auto-posts**. Before calling the API it
prints a preview:

> About to post to PR #<n>: <N> inline comments + <M> general. Proceed? (y/n)

and waits for explicit confirmation. On "no", fall back to file/chat output.

### A5. Edge cases

| Case | Behaviour |
|------|-----------|
| No open PR for branch | Inform user, fall back to file/chat, no post |
| Zero findings | Do not post; emit the persona's "nothing to say" line |
| Some findings un-anchorable | Post anchorable inline; bundle rest into summary/general comment |
| `gh api` post fails | Surface the error; the computed findings remain available in chat |

## Strand B — docstring pass

Add one-line docstrings to the functions that currently lack them in:

- `scripts/persona_io.py` — `persona_dir`, `persona_path`, `persona_exists`,
  `list_personas`, and any other bare helpers
- `scripts/collect.py` — bare private helpers (`parse_args`, `_gh_search`,
  `_gh_get`, `_login`, `_matches_path_filter`, `_compute_since`, etc.)

Constraints:
- Match the existing terse, imperative voice
  (e.g. *"Return the frontmatter dict from a PERSONA.md file."*)
- **No** behaviour or signature changes — documentation only
- Any new helper introduced by Strand A also gets a one-line docstring

## Testing

- **Strand A:** the posting logic lives in `SKILL.md` (LLM-driven `gh api`
  calls), so there is no new unit-testable Python unless a helper is extracted.
  If a `post_review` helper is added to Python, it gets a unit test that
  asserts the constructed `gh api` argv (prefix applied to every body, correct
  `path`/`line`/`side`). Mock the subprocess boundary — no live GitHub calls.
- **Strand B:** existing test suite (`pytest`) must still pass; docstrings are
  inert. No new tests required.

## Out of scope

- Resolving/replying to existing PR threads (that is `tribunal`'s domain)
- Editing or deleting previously posted clone comments
- Posting from `chat` or `refresh` modes — review mode only

## Version impact

Patch-or-minor bump to `review-clone` (new user-facing capability → minor:
0.1.1 → 0.2.0) and marketplace (1.2.1 → next). Confirm increment at PR time.
