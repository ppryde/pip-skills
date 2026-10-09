import { configRootOf, joinPath, trimSeps } from './home'
import type { HomeEnv } from './home'

export const NAME = 'census-mod'
export const SCHEMA = 1

/** `/a/b//` -> `/a/b`; `C:\x\` -> `C:\x`; a root stays a root (a bare trim would leave the empty string). */
export const trimSlashes = trimSeps

/** The config dir: CLAUDE_CONFIG_DIR, else <home>/.claude (home: HOME, USERPROFILE, HOMEDRIVE+HOMEPATH); null if none can be told. */
export function configRoot(env: HomeEnv): string | null {
  return configRootOf(env)
}

// Where Claude Code keeps a session's transcript, for when no hook has carried the path yet (a hot
// reload fires session.start but not classic.SessionStart). Ported from context-vigil-mod.
export function transcriptPathFor(root: string, cwd: string, sessionId: string): string {
  return joinPath(root, 'projects', cwd.replace(/[^A-Za-z0-9]/g, '-'), `${sessionId}.jsonl`)
}
