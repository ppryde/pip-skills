---
description: Hand over now — assemble a handover (session snapshot + your notes) and reset context via /clear, per vigil's protocol.
argument-hint: [optional note on what a fresh session must know]
---

The user is asking you to hand over context now (a manual reset). Follow vigil's
protocol (`skills/vigil/SKILL.md`):

1. **Finish or hold.** If work is in flight, wait for it to return — never hand
   over mid-task. If a live discussion is mid-thread, confirm before clearing.
2. **Write the handover.** Run `vigil handover --notes "<the critical prose a
   fresh you must know that isn't obvious from the repo>"` via the vigil CLI.
   Fold in anything the user passed as an argument. Keep the notes tight — the
   snapshot already captures cwd, branch, status, and recent files. If
   `context.mode` is `remote` (check `vigil config get context.mode`), the next
   session cannot open file paths — inline anything it must read with
   repeatable `--inline <path>` instead of referencing it.
3. **Reset, per mode.**
   - **auto** (under tmux, begun): the Stop hook sends `/clear` at turn end;
     `SessionStart` re-injects the handover.
   - **manual** (no tmux): tell the user to type `/clear` now.
   - If vigil isn't watching here yet, run `vigil begin` first (it reports auto
     vs manual).
