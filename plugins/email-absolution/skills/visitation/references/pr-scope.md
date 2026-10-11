# Visitation scope, changed lines and existing violations

Read at Step 2 (scope). Section names here are plain headings, not `§` citations. `audit.md` and `common.md` still apply.

## Scope

**Branch/PR mode (default):**
```bash
git diff --name-status -M --diff-filter=ACMRT '<base>'
```

`<base>` is resolved as in `audit.md §Scope` (Elder scope). Omitting a trailing `HEAD` includes uncommitted edits, so a run before opening a PR works.

Include files with status `A` (added), `M` (modified), `T` (type change) and
`R`/`C` (renamed/copied — the destination path is in scope).
Deleted files are excluded by the filter — deleted templates have no violations.
Filter to `email_paths` and known email extensions.

**PR number mode:**
The PR number must match `^[0-9]+$`; refuse anything else before building the command. Audit the PR's head commit, not the working tree (which is usually another branch):
```bash
gh pr view '<number>' --json headRefOid,baseRefName,files
```
- `headRefOid` is the head commit (40 hex digits; refuse anything else). If `git cat-file -e '<oid>^{commit}'` fails, run `git fetch origin 'pull/<number>/head'` once (the one git command here that is not read-only: it writes objects and FETCH_HEAD, nothing else); if the commit is still missing, report the PR as not accessible.
- `files` lists the changed paths; drop entries whose `changeType` is `DELETED`, keep the rest (the `path` is the destination for a rename), and filter to `email_paths` and the email extensions as above. A path that starts with `-` or `/`, or has a `..` part, is refused.
- Read every file from that commit: `scan --rev '<oid>' --files ...` for Phase 1 (`audit.md §Audit pass`) and `git show '<oid>:<path>'` for Phase 2 and the line numbers. Never read the working-tree copy in PR mode.
- `baseRefName` must match `^[A-Za-z0-9._][A-Za-z0-9._/-]*$`. The diff base is `git merge-base '<oid>' 'origin/<baseRefName>'`; if that does not resolve, treat every line as changed (see Changed lines).

**Single file mode:** Named file only.

If no email template files are found in scope:
> "The Visitation finds no email templates in this branch's changes.
> If templates were moved, renames are followed automatically; if the base
> branch was wrong, name it explicitly or check `git diff --name-status` manually."

## Changed lines

A finding is **in the diff** when its line is one of the added or modified lines of its file, **outside the diff** otherwise. Get the added ranges for the files in scope:

```bash
python3 '<rules.py>' hunks --base '<merge-base>' [--rev '<oid>'] --files '<file>' ['<file>' ...]
```
`--base` is the same base as the scope diff (the merge-base sha, quoted as in `common.md §Rules`); `--rev` is the PR head in PR mode only. Each output line is `path: 12-15,40` (the added lines), `path: none` or `path: unknown`. `unknown` (git could not say: an added file not yet tracked, a missing base) and single-file mode mean every line counts as changed. Absence findings (a whole-file finding) count as in the diff. If `python3` is unavailable, use `git diff -U0` and read the `+start,count` of each `@@` header by hand.

## Existing violations (verdict)

Classify each finding as in the diff or outside it (Changed lines). A mortal sin anywhere in a touched file stays a mortal sin and blocks, but one outside the diff is labelled `(pre-existing)` and listed after the new ones under the same MORTAL SINS heading, so the author can tell what this change introduced. Venial and counsel findings outside the diff are existing debt: they are not listed in VENIAL SINS or COUNSEL, only counted per file in an EXISTING DEBT section (counts by severity, with the ids). Overrides apply first, so an overridden mortal is classified at its new severity.
