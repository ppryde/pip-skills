export type SessionRow = {
  pid: number
  sessionId: string
  /** Which config dir's registry it came from: `personal` or `work`. */
  account: string
  /** The tmux session name, absent when it runs outside tmux. */
  tmux?: string
  cwd: string
  repo: string
  /** The worktree name when cwd is under `<repo>/.claude/worktrees/<name>`. */
  worktree?: string
  branch?: string
  /** `busy`, `idle`, `waiting`, `shell`, ... as the session reports it. */
  status: string
  /** Why it waits (`input needed`), while `status` is `waiting`. */
  waitingFor?: string
  kind: string
  /** Epoch ms of its last status change. */
  lastActive: number
  /** The last prompt its transcript recorded, whitespace collapsed. */
  lastPrompt?: string
}

declare module 'claude-code' {
  interface PluginState {
    'agent-roster': {
      sessions: { rows: SessionRow[]; checkedAt: number; selfId?: string }
    }
  }
}
