export const NAME = 'census-mod'
export const SCHEMA = 1

// null when neither is set: a relative `.claude` would land under the session's cwd.
export function configRoot(env: { CLAUDE_CONFIG_DIR?: string; HOME?: string }): string | null {
  if (env.CLAUDE_CONFIG_DIR) return env.CLAUDE_CONFIG_DIR.replace(/\/+$/, '')
  return env.HOME ? `${env.HOME.replace(/\/+$/, '')}/.claude` : null
}

// Where Claude Code keeps a session's transcript, for when no hook has carried the path yet (a hot
// reload fires session.start but not classic.SessionStart). Ported from context-vigil-mod.
export function transcriptPathFor(root: string, cwd: string, sessionId: string): string {
  return `${root}/projects/${cwd.replace(/[^A-Za-z0-9]/g, '-')}/${sessionId}.jsonl`
}
