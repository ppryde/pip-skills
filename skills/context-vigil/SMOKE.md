# Manual smoke — run before merge (dev-only, not shipped)

Needs a real Claude session and a human. Record results in the PR description.

Use a scratch config dir so nothing touches the real account:

```bash
export CLAUDE_CONFIG_DIR=$(mktemp -d)/claude   # then log in when prompted
skills/context-vigil/scripts/context-vigil install --yes --threshold 5 --launcher on-demand
```

- [ ] `claude-tmux` in a scratch repo; work until the nudge appears (about 5%).
- [ ] The agent writes notes and runs `handover --file`.
- [ ] `/clear` is sent automatically.
- [ ] The fresh session resumes with the handover's Next Step.
- [ ] Plain `claude` (no tmux): nudge, then handover, then "handover saved — type /clear, then send any message".
- [ ] After typing `/clear` the handover is injected, but nothing happens until you send a message (e.g. "go"); then it resumes from the Next Step.
- [ ] The handover's git section is a few pointer lines (branch, base, counts, commands), with no file list.
- [ ] Close the terminal after a handover but before `/clear`; a fresh launch shows the "handover is waiting" notice and does not load it.
- [ ] `context-vigil uninstall --yes` leaves `settings.json` and the rc file identical to their pre-install contents.
