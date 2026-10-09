export const NAME = 'census-mod'
export const SCHEMA = 1

// null when neither is set: a relative `.claude` would land under the session's cwd.
/** `/a/b//` -> `/a/b`; `/` stays `/` (a bare trim would leave the empty string). */
export const trimSlashes = (p: string): string => (p.replace(/\/+$/, '') || (p.startsWith('/') ? '/' : p))

export function configRoot(env: { CLAUDE_CONFIG_DIR?: string; HOME?: string }): string | null {
  if (env.CLAUDE_CONFIG_DIR) return trimSlashes(env.CLAUDE_CONFIG_DIR)
  return env.HOME ? `${trimSlashes(env.HOME)}/.claude` : null
}

// Where Claude Code keeps a session's transcript, for when no hook has carried the path yet (a hot
// reload fires session.start but not classic.SessionStart). Ported from context-vigil-mod.
export function transcriptPathFor(root: string, cwd: string, sessionId: string): string {
  return `${root === '/' ? '' : root}/projects/${cwd.replace(/[^A-Za-z0-9]/g, '-')}/${sessionId}.jsonl`
}
