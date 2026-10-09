import { configRootOf, joinPath } from './home'
import type { HomeEnv } from './home'

export const NAME = 'context-vigil-mod'
export const TOOL = 'vigil_handover'
export const TOOL_FULL = `mcp__${NAME}__${TOOL}`
export const COMMANDS = { handover: 'vigil-handover', handoverShort: 'vho', setup: 'vigil-setup', overrides: 'vigil-overrides' } as const

// null when no home can be told (CLAUDE_CONFIG_DIR, HOME, USERPROFILE, HOMEDRIVE+HOMEPATH): a relative `.claude`
// would land under the session's cwd, so callers write nothing.
export function configRoot(env: HomeEnv): string | null {
  return configRootOf(env)
}

export function handoverPath(root: string, session: string, n: number): string {
  return joinPath(root, NAME, 'handovers', `${session}-${n}.md`)
}

export function overridesPath(root: string): string {
  return joinPath(root, NAME, 'overrides.json')
}

export function eventsPath(root: string, day: string, session: string): string {
  return joinPath(root, NAME, 'events', day, `${session}.jsonl`)
}

// TEMPORARY (interlock): where classic context-vigil keeps a session record.
export function classicSessionPath(root: string, session: string): string {
  return joinPath(root, 'context-vigil', 'sessions', `${session}.json`)
}
