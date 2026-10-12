# Tasks and work tracking

Read when you set up the shared task list, or tag work with a card.

## Work tracking
Every in-session todo (a TodoWrite item or an inline checklist entry) carries the
`[<id>]` prefix of the card it serves: traceability from live work to the ledger
("if it isn't in the ledger, it didn't happen," at the todo level). Multiple cards
may be in flight (stacks/sprints), so tag per-card; a todo with no card is
`[no-card]`. When work outgrows a card's scope, spin a **child card** off it
(`new-card`, then `set-field <child> --parent <card>`), which promotes the
overflowing card to an epic, rather than letting it sprawl. The concrete
companion to the drift watchdog's scope-creep gate. For native tasks
(TaskCreate), the `metadata: {card: <id>}` join replaces the `[<id>]` prefix;
the prefix rule remains for any non-task todo surface.

## Tasks
Claude Code's native task list (`TaskCreate`/`TaskUpdate`) is the agent's live
checklist; a card's `checklist:` frontmatter is its durable projection,
written ONLY by the `checklist-sync-hook` (overseer's `PostToolUse` hook on
`TaskCreate|TaskUpdate`) — never hand-edit a card's checklist yourself.
- **Bootstrap (once per project):** ensure `.claude/settings.json` (or
  `.local`) has `env.CLAUDE_CODE_TASK_LIST_ID` (default: a slug of the
  project root dir name). If you write it fresh, announce loudly: "restart
  this CLI once to adopt the shared task list — /clear is not sufficient."
  You may spawn the replacement session yourself: `main=$(dirname "$(git
  rev-parse --path-format=absolute --git-common-dir)") && (cd "$HOME" &&
  tmux new-session -d -s <name> -c "$main" -e CLAUDE_CODE_TASK_LIST_ID=<id>
  claude)` (append `--plugin-dir <repo>/plugins` during development so the
  new session loads the working-tree hooks) — then tell the user to `tmux
  attach -t <name>` and close this one. **The two directories are not the
  same directory and must not be collapsed:**
  - `cd "$HOME"` — the tmux SERVER's cwd. If no server is running this
    command starts one, and a tmux server keeps its launching shell's cwd
    for life. Point that at a worktree and every future session on that
    server starts in a dead directory once the worktree is removed
    (`getcwd: cannot access parent directories`). `$HOME` is the one
    directory that is always there, so the server is rooted in it.
  - `-c "$main"` — the SESSION's cwd: the main repo folder (via
    `git-common-dir`), never a worktree, so the new CLI opens in the repo.

  This is an install-time relaunch only, not a handover path; vigil's
  in-place `/clear` still owns handovers.
- **Working rule:** picking up a card → break it into tasks via `TaskCreate`
  with `metadata: {card: <id>}`; work tasks `in_progress` → `completed`.
  Never hand-edit a card's checklist — the sync owns it. Card-level
  transitions (`set-stage`, `done`, `block`, ...) stay CLI verbs as today.
- **Boundary check:** completing tasks is exactly where vigil's threshold
  nudge fires — before a card-level transition that bypasses the task list,
  run `vigil context` per the vigil trigger spec.
- **Sprint teardown:** tasks for done cards may be marked `deleted` (list
  hygiene); the card's checklist remains — it is the durable record.
