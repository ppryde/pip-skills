# context-vigil live smoke harness (dev-only, not shipped)

Drives a real `claude` in a detached tmux session to exercise nudge, handover,
`/clear` and resume end to end. **It spends real account tokens** (a cheap model
by default, `--model haiku`); run it only with the owner's approval.

## What it touches

- Creates a private sandbox with `mkdtemp` (0700, unpredictable name) inside
  `${TMPDIR}/cv-smoke-<uid>/` (0700, must be yours: a planted or open one is
  refused), holding a scratch git repo (`repo/`), the context-vigil data root
  (`data/`, as `CONTEXT_VIGIL_HOME`) and `settings.json`.
- Hooks and the status line are injected with `claude --settings <that file>`,
  using the same events, matchers and commands as `install`. Threshold defaults
  to 2%, cooldown to 0.
- Uses a dedicated tmux socket (`tmux -L cv-smoke`), fresh server per run,
  `kill-server` on `down`.
- Uses the real `CLAUDE_CONFIG_DIR` for auth and writes the session transcripts
  there as any claude run does. It never writes your real `settings.json`, rc
  files or `~/.claude*` config, and never prints environment values or the
  sandbox settings' `env`. The sandbox lives in `$TMPDIR`. Everything it echoes
  from the pane or a run (`peek`, timeout tails, `state` first lines, headless
  output) is passed through a redactor that masks known token formats
  (`sk-…`, `AKIA…`, `ghp_…`/`github_pat_…`, `xox?-…`, `AIza…`, private-key
  blocks, JWTs, credentials in URLs, `KEY=`-style assignments) plus any
  `token=`/`password:`/`api_key`/`Bearer …` in any case, as `[redacted]` —
  belt and braces, in case the model prints something it found. `state` prints
  only allow-listed session-record fields, and masks a key-shaped value even
  there.
- Permissions are narrow: `Bash(<this checkout>/scripts/context-vigil:*)`,
  `Bash(cp:*)`, Read, Write, Edit. `--yolo` skips permission prompts instead.
- Pointer file `${TMPDIR}/cv-smoke-<uid>/current.json` (0600, refused unless
  yours and private) records the active sandbox; `down --purge` deletes only a
  sandbox inside that private dir.
- The `headless` scenario has the model write its notes in the file
  `context-vigil notes-path` prints, never in the scratch repository.

## Commands

    D=skills/context-vigil/dev/live-smoke
    $D up --dry-run            # write sandbox, print the tmux/claude command only
    $D up [--model M] [--threshold N] [--sandbox PATH] [--yolo]
    $D peek [-n 30]            # last pane lines
    $D send "text"             # type text + Enter
    $D wait-for REGEX [--timeout 120]
    $D state                   # data-root tree, session records, census windows, archives
    $D transcripts             # scratch-project transcripts with line counts
    $D down [--purge]
    $D auto [--model M] [--timeout 300]      # scripted attended scenario, PASS/FAIL
    $D headless [--model M]                  # claude -p handover, then --resume

`auto`: up, accept the folder-trust prompt, grow context, wait for the nudge,
reply to hand over, wait for the archive and a new session id, then check the
archive holds a Next Step and the new transcript has the resume preamble and
kick prompt. `headless`: a `claude -p` run hands over, then `handover --resume`
must find it in the headless location.

Manual driving: `up`, then `peek`/`send` in turn (accept the trust prompt with
`send ""`), `state` to inspect, `down` when done.
