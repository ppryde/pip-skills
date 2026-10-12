# clone-reviewer: PERSONA.md format (Step 6)

Use the persona_io helpers (`from scripts.persona_io import write_persona, persona_path`). Frontmatter shape:

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
disclaimer: "Derived from public GitHub review history of <handles>. Not endorsed by them."
```

Body sections: `## Voice & tone`, `## Rules` (one ### per rule, with severity/citation/examples), `## What they let go`, `## Drift log`.
