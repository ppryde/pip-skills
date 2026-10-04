export const NAME = 'context-vigil-mod'
export const TOOL = 'vigil_handover'
export const TOOL_FULL = `mcp__${NAME}__${TOOL}`
export const COMMANDS = { handover: 'vho', handoff: 'vhandoff', setup: 'vsetup' } as const

export function configRoot(env: { CLAUDE_CONFIG_DIR?: string; HOME?: string }): string {
  if (env.CLAUDE_CONFIG_DIR) return env.CLAUDE_CONFIG_DIR.replace(/\/+$/, '')
  return env.HOME ? `${env.HOME.replace(/\/+$/, '')}/.claude` : '.claude'
}

export function handoverPath(root: string, session: string, n: number): string {
  return `${root}/${NAME}/handovers/${session}-${n}.md`
}

export function eventsPath(root: string, day: string, session: string): string {
  return `${root}/${NAME}/events/${day}/${session}.jsonl`
}

// TEMPORARY (interlock): where classic context-vigil keeps a session record.
export function classicSessionPath(root: string, session: string): string {
  return `${root}/context-vigil/sessions/${session}.json`
}
