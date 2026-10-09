export type SessionRow = {
  pid: number
  sessionId: string
  /** The tmux session name, absent when it runs outside tmux. */
  tmux?: string
  cwd: string
  repo: string
  /** The worktree name when cwd is under `<repo>/.claude/worktrees/<name>`. */
  worktree?: string
  branch?: string
  /** The tag of the config dir it was read from, when that is not the session's own (`personal`). */
  account?: string
  /** `busy`, `idle`, `waiting`, `shell`, ... as the session reports it. */
  status: string
  /** Why it waits (`input needed`), while `status` is `waiting`. */
  waitingFor?: string
  kind: string
  /** Epoch ms of its last status change. */
  lastActive: number
  /** Its `/rename` title, else the AI-written one. */
  title?: string
  /** The last prompt the person typed (never a teammate's or a task's), whitespace collapsed. */
  prompt?: string
  /** Epoch ms of that prompt. */
  promptAt?: number
}

declare module 'claude-code' {
  interface PluginState {
    'agent-roster': {
      /** `error`: why the last scan failed, while the rows are the last good ones. */
      sessions: { rows: SessionRow[]; checkedAt: number; selfId?: string; error?: string; warnings?: string[] }
      /** The pid whose kill button was pressed and awaits confirmation. */
      pendingKill: number | null
      /** Whether idle sessions quiet for over a day are unfolded. */
      showOlder: boolean
      /** The repo tab in view; null for All. */
      repoTab: string | null
    }
  }
}
