# clone-reviewer: PERSONA.md format (Step 6)

Write the persona with the CLI, by absolute path (no import): put the frontmatter as one JSON object in a temp file and the body markdown in another, both written with the **Write tool** (`mktemp -d -t review-clone.XXXXXX` on its own for the dir), then run

```bash
python3 <plugin>/scripts/persona_io.py write --alias '<alias>' --frontmatter <fm.json> --body <body.md>
```

It writes to the account's persona dir with owner-only permissions. Frontmatter shape (as JSON keys):

```yaml
alias: <alias>
handles:
  - <handle1>
repo: <repo>
filters:
  paths: [...]
  extensions: [...]
window:
  months: <n>
  since: "<iso>"
tone: <copy|neutral>
authoring_voice: <true|false>
last_scanned_at: "<iso>"
snapshot:
  prs: <n>
  review_comments: <n>
  issue_comments: <n>
  pr_descriptions: <n>
output_default: null
drift_log: []
drift_log_archived_count: 0
source_visibility: <public|private|internal>
private_source: <true|false>
disclaimer: "Derived from public GitHub review history of <handles>. Not endorsed by them."
```

Body sections: `## Voice & tone`, `## Rules` (one ### per rule, with severity/citation/examples), `## What they let go`, `## Drift log`.

For a `private_source` persona the disclaimer reads "Derived from the private-repo review history of <handles>. Not endorsed by them. Keep this persona private." and `source_visibility`/`private_source` come from the snapshot.
