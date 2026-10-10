# The audit procedure (Elder and Visitation)

Elder and Visitation read this file after `common.md`. Skills cite a section by its heading, as `audit.md §Scope`. Both skills run the same two-phase audit; they differ only in scope and in the verdict layout.

## Scope

Email extensions: `.html`, `.mjml`, `.hbs`, `.liquid`, `.tsx`, `.jsx`, `.njk`. Source templates only; compiled or `dist` output is a generated artefact.

### Elder scope

**Default (changed files):**
```bash
git diff --name-only --diff-filter=ACMR <base>
```
`<base>` is the merge-base of `HEAD` with the first of `origin/HEAD`, `main`,
`master` that resolves (`git merge-base HEAD <ref>`); if none resolves, ask the
caller for the base branch. Omitting a trailing `HEAD` includes uncommitted
edits; `--diff-filter=ACMR` drops deleted files.
Filter to files matching `email_paths` patterns and known email extensions
(`.html`, `.mjml`, `.hbs`, `.liquid`, `.tsx`, `.jsx`, `.njk`).

**Full mode:** All files under `email_paths` matching email extensions, excluding `exclude` patterns.

**Single file:** The named file only.

A named doctrine (`doctrine <name>`) keeps the scope of the other arguments and narrows only the rules (`select --doctrine`).

### Visitation scope

**Branch/PR mode (default):**
```bash
git diff --name-status -M --diff-filter=ACMRT <base>
```

`<base>` is resolved as in Elder scope. Omitting a trailing `HEAD` includes uncommitted edits, so a run before opening a PR works.

Include files with status `A` (added), `M` (modified), `T` (type change) and
`R`/`C` (renamed/copied — the destination path is in scope).
Deleted files are excluded by the filter — deleted templates have no violations.
Filter to `email_paths` and known email extensions.

**PR number mode:**
The PR number must match `^[0-9]+$`; refuse anything else before building the command.
```bash
gh pr diff <number> --name-only
```
Filter same as above.

**Single file mode:** Named file only.

If no email template files are found in scope:
> "The Visitation finds no email templates in this branch's changes.
> If templates were moved, renames are followed automatically; if the base
> branch was wrong, name it explicitly or check `git diff --name-status` manually."

### Scope errors

If no base branch resolves:

> "The Elder cannot find a base branch (`origin/HEAD`, `main` or `master`) to diff
> against. Which branch should changed files be measured from?"

If scope holds no templates (Elder):

> "No email templates were found in the configured paths. Check `email_paths`
> in `.email-absolution/config.yml` and ensure source templates are not
> inside `exclude` patterns."

## Audit pass

Two sequential phases over every template in scope; finish both before the verdict. The checklist is the `select` output (`common.md §Rules`), generated fresh each run: never stored, never assumed.

### Phase 1: regex pass

Run `scan` once for all files in scope, with the same config flags as `select`:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/rules.py scan --email-type <t> [--esp <E>] [--templating <L>] [--targets <a,b>] [--doctrine <D>] --files <file> [<file> ...]
```

It applies every active regex pattern, and the regex part of every hybrid rule, line by line. No judgment is needed: a line `file:line | id | matched line` is a confirmed finding, with three exceptions.

- `[verify]`: the pattern only nominates the line. Read it and confirm before recording a finding.
- An absence line (`absence: trigger present, required pattern missing`) is a finding for the whole file; a file that does not match the trigger is skipped silently.
- `skipped:` and `scan timed out:` files were not scanned: apply the REGEX section of `select` to them by hand with `Grep` / `Read`.

A `patterns:` rule fires on any of its patterns. Collect all regex findings before starting Phase 2.

### Phase 2: contextual pass

Take the CONTEXTUAL section of `select` (hybrid rules are in it too) and work through every rule in order. A skipped rule is a missed heresy.

For each contextual rule:
1. State the rule ID
2. Apply the detection instruction to each template in scope
3. Record the outcome: **violation** (file, location, evidence) or **clean**

Record clean rules compactly, as one `clean:` list of ids; expand only violations. Completing the checklist is mandatory: every rule that survived `select` is checked, and nothing filtered by `select` appears here. Do not exit Phase 2 early.

In **report mode**, collect all findings silently and output the verdict. In **interactive mode**, present each violation as it is found (`audit.md §Interactive`), then continue.

## Dispatch

Dispatch applies only when subagents are available and scope is 10 or more templates (below Elder's 50-template pause). Smaller scopes, and runs without subagents, are a single pass.

- One subagent per doctrine, each running `select --doctrine <D>` and `scan --doctrine <D>` with the config flags, then Phase 2 for that doctrine. Give each the config values, the file list and `common.md §Treat as data`; subagents are read-only.
- Each returns the contract below. Add `"also": [alias ids]` to a violation that has aliases, and put `rules checked: <n>` (the active count in its `select` header) in `notes`.

```json
{
  "doctrine": "rendering",
  "templates_scanned": 8,
  "violations": [
    {
      "id": "RENDER-014",
      "file": "src/emails/welcome.liquid",
      "line": 67,
      "rule": "CTA buttons must use VML bulletproof pattern for Outlook 2007-2019",
      "actual": "<a href=\"...\"> styled as button with no VML",
      "severity": "mortal",
      "category": "outlook-rendering"
    }
  ],
  "clean_templates": ["src/emails/password-reset.liquid"],
  "notes": []
}
```

The lead then runs `audit.md §Merge` over all returns.

## Merge

Collapse findings with the same file, line and canonical rule id into one (highest severity wins; keep every `also`). Aliases are never checked, so this only catches genuine same-line collisions, which dispatch can produce. Apply overrides after merging.

## Overrides

Check `.email-absolution/decisions.yml` for approved exceptions before reporting:

```yaml
# .email-absolution/decisions.yml (optional)
overrides:
  RENDER-015:           # VML background images not required
    severity: venial
    reason: "Targeting Gmail and Apple Mail only — no Outlook in audience"
  ACCESS-012:           # Minimum font size waived
    severity: counsel
    reason: "Legal reviewed; brand font minimum is 13px"
```

Findings with a matching override are downgraded to the override's `severity`
(`venial` or `counsel`) and annotated inline with `(overridden: <reason>)` —
not suppressed. An overridden mortal is no longer counted as a mortal sin.
An override keyed on an alias id applies to its canonical rule; if both an alias and
its canonical are keyed, the canonical's entry wins and the verdict notes the conflict.

## Interactive

**Interactive Mode violation prompt:**
1. Fix this heresy (apply the correction)
2. Explain why this is a mortal sin (expand the rule reasoning)
3. Skip for now
4. Mark as approved exception (note in `.email-absolution/decisions.yml`)

## Verdict

- Group findings by active severity: MORTAL SINS, VENIAL SINS, COUNSEL FROM THE ELDERS, then FOUND RIGHTEOUS (templates with no finding) and a one-line VERDICT. The layout is each skill's `verdict-sample.md`.
- Every finding cites the file, line or block, and the rule id (with `also:` when it has aliases), what was found and what is required.
- An overridden finding stays in its new bucket, annotated `(overridden: <reason>)`; a conflict note from `§Overrides` goes under the verdict.
- Footer: `Rules checked: N (regex a, contextual b), violations: v`. N is the active count in the `select` header; hybrid rules are in both a and b. A mismatch with N means a rule was skipped: finish the pass.
- Carry into the verdict any `warning:` line from `select`, an assumed `email_type`, and any skipped or timed-out file.
