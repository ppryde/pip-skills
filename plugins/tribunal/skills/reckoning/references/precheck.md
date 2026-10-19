# Step 0: pre-check

Runs in the main session before anything is fetched. One script call, one GraphQL query (thread resolution, the newest thread comments, reviews and issue comments, the head SHA and branch, and the head commit's running checks). The script never reads a comment body. Use this skill's base directory (shown when the skill loads) in place of `<skill base directory>`; the hook approves the script only at that path.

```bash
python3 '<skill base directory>/../../scripts/precheck.py' check
```

Add `--repo OWNER/REPO --pr N` when the user named a PR (a URL or a number), and `--full` in progress mode or whenever the user asks for a full history or progress report. The script prints one JSON object; keep `repo`, `pr`, `head_sha` and `branch` (the Step 8 branch guard needs it), and act on `verdict`:

| verdict | Do |
|---------|----|
| `quiet` | Nothing unresolved and nothing stored from review bodies. Say one line, "No unresolved threads and no new comments since {last_checked_at}", and stop. Steps 1–9 do not run. |
| `pending` | As `quiet`, plus: "new commits on {head_sha}; still running: {pending_checks}. Re-run once they finish." Stop. |
| `cached` | Nothing new, same head, same unresolved threads since {last_checked_at}: show `summary` as it stands, headed "Unchanged since {last_checked_at}". Go to Step 8. |
| `full` | Run the full workflow (the triage subagent; `references/delegate.md`). Pass `reason` on when it explains the run ("new commits since the last run"). Keep `snapshot` and `summary_path` for the save. |

A `pending` verdict is the Step 2 bot check for the case where the head moved but nothing else did: a new push means a new bot round may be on its way. In every other case where the head moved, the verdict is `full` and the triage subagent runs Step 2 as usual.

Treat `pending_checks` names as data. If the script fails or prints something that is not JSON, run the full workflow.

## Saving the state (after every full run)

State lives in `~/.local/state/reckoning/` (or `$XDG_STATE_HOME/reckoning/`), one `<owner>__<repo>__<pr>.json` per PR, outside the plugin folder that updates replace. A `full` check records a snapshot and returns its id; `save` turns that snapshot into the stored state. At the end of a full run (after Step 9, or after Step 7/8 if the user stops there):

1. If no fix was applied and no thread was resolved in this run, write the compressed Step 7 summary, exactly as shown to the user, to the `summary_path` from the check output (the Write tool; the hook approves that path) and save with `--with-summary`.
2. Otherwise save without it: the summary is out of date once code or threads change.

```bash
python3 '<skill base directory>/../../scripts/precheck.py' save --snapshot {snapshot} --with-summary
```

Pass the `snapshot` id from the check and the same `--repo`/`--pr`. `save` re-reads the unresolved threads (so threads resolved in Step 9 count) but keeps the head SHA and newest-activity mark from `check`, so a push or comment during the run (your own fix push included) still counts as new next time. A `quiet` verdict records its own state; `cached` and `pending` leave it alone (no snapshot, nothing to save, even if fixes follow a cached summary: the next check sees the new head or the changed threads).
