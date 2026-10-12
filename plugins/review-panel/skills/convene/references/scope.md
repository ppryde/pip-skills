# Scope: the diff (convene Step 2)

Make a scratch dir once: run `mktemp -d -t review-panel.XXXXXX` on its own. `<dir>` below.

## `changed`

Work against the remote base, so unpushed and uncommitted work is included.

1. Base: `git symbolic-ref --short refs/remotes/origin/HEAD`, strip the `origin/`
   prefix; `main` if that fails. Call it `<base>`. If a PR exists,
   `gh pr view --json baseRefName -q .baseRefName` wins.
2. `git fetch -q origin '<base>' || true`
3. The diff, one unified file, the single input every subagent gets:
   `git diff --merge-base --diff-filter=ACMR -M -U3 'origin/<base>' -- > <dir>/review.diff`
   (`ACMR` = added, copied, modified, renamed; `-M` follows renames; tracked staged and
   unstaged edits are in). With `targets`, add each glob after `--` as a
   single-quoted pathspec `':(glob)<glob>'`.
4. Changed file list: the same command with `--name-only` instead of `-U3`.
5. Untracked files (`git ls-files -o --exclude-standard`) are listed to the user and
   offered, never assumed.
6. Empty diff → say "Nothing to review: no changes against `origin/<base>`" and stop.

**Quoting.** `<base>` and every path or glob come from a branch, a PR or config, so put
each in single quotes, escaping an embedded `'` as `'\''`; never double quotes. A value
with a newline or NUL is skipped, with a note.

## `full`

All tracked files matching `targets` (or the repo default): `git ls-files` filtered by
the globs. There is no diff; reviewers Read the files.

## Size

If scope is over ~100 files or the diff is over ~3000 lines, warn and ask whether to
proceed, narrow to directories, or switch to changed.
