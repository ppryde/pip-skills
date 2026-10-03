# Manual smoke — run before merge (dev-only, not shipped)

Needs a real Claude session and a human. Record results in the PR description.

Use a scratch config dir so nothing touches the real account, and
`--launcher not-now` so nothing touches your real shell rc (call `claude-tmux`
by path instead of through the alias):

```bash
export CLAUDE_CONFIG_DIR=$(mktemp -d)/claude   # then log in when prompted
skills/context-vigil/scripts/context-vigil install --yes --threshold 5 --launcher not-now
alias claude-tmux="$PWD/skills/context-vigil/scripts/claude-tmux"
```

To exercise the rc edit itself, point it at a scratch home, never your own:
`HOME=$(mktemp -d) ZDOTDIR= SHELL=/bin/zsh skills/context-vigil/scripts/context-vigil launcher on-demand`
(dry run; add `--yes` to apply inside that scratch home).

- [ ] The `install` / `launcher` / `uninstall` output is a summary — file paths, our own lines and command strings — with no line of the rc file, no settings `env` and no other hook's command.
- [ ] `ls -ld "$CLAUDE_CONFIG_DIR/context-vigil"` is `drwx------`, and the files under it are `-rw-------`.
- [ ] `claude-tmux` in a scratch repo; work until the nudge appears (about 5%).
- [ ] The agent runs `notes-path`, writes its notes in the file it prints (never in the repo) and runs `handover --file <that path>`; the notes file is gone afterwards.
- [ ] `/clear` is sent automatically.
- [ ] The fresh session resumes with the handover's Next Step.
- [ ] Plain `claude` (no tmux): nudge, then handover, then "handover saved — type /clear, then send any message".
- [ ] After typing `/clear` the handover is injected, but nothing happens until you send a message (e.g. "go"); then it resumes from the Next Step.
- [ ] The handover's git section is a few pointer lines (branch, base, counts, commands), with no file list.
- [ ] Close the terminal after a handover but before `/clear`; a fresh launch shows the "handover is waiting" notice and does not load it.
- [ ] `context-vigil uninstall --yes` leaves `settings.json` and the rc file semantically equal (same keys and values) to their pre-install contents; formatting may differ.

## Live harness

`dev/live-smoke` automates much of this checklist against a real claude in a
dedicated tmux socket with sandboxed hooks (`auto`, `headless`, or step by step
with `up`/`send`/`peek`/`state`). It spends real tokens, never touches real
settings or rc files, and is dev-only, so `dev/` and `SMOKE.md` are excluded
from the agents.md copy. See `dev/README.md`.
