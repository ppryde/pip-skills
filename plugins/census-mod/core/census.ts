export type CensusEnv = {
  CENSUS_MOD_STORE?: string
  CENSUS_STORE?: string
  CENSUS_CLI?: string
  CLAUDE_CONFIG_DIR?: string
  HOME?: string
}

const trim = (p: string): string => (p.length > 1 ? p.replace(/\/+$/, '') : p)
const expand = (p: string, home?: string): string => (home && (p === '~' || p.startsWith('~/')) ? home.replace(/\/+$/, '') + p.slice(1) : p)

/** Shadow mode: the dir the mod records to instead of census's own, when set. */
export function shadowDir(env: CensusEnv): string | null {
  return env.CENSUS_MOD_STORE ? trim(expand(env.CENSUS_MOD_STORE, env.HOME)) : null
}

/** The census dir readers use: `CENSUS_STORE`, else `<config dir>/census`. */
export function censusDir(env: CensusEnv): string | null {
  if (env.CENSUS_STORE) return trim(expand(env.CENSUS_STORE, env.HOME))
  const root = env.CLAUDE_CONFIG_DIR ? trim(env.CLAUDE_CONFIG_DIR) : env.HOME ? `${trim(env.HOME)}/.claude` : null
  return root ? `${root}/census` : null
}

/**
 * The `cli.path` pointers to try, in order. The shadow dir's own pointer comes first (ingest
 * writes it there), then the real census dir's, which is where a shadow dir learns the CLI from.
 */
export function pointerFiles(env: CensusEnv): string[] {
  const dirs = [shadowDir(env), censusDir(env)].filter((d): d is string => d !== null)
  return [...new Set(dirs)].map(d => `${d}/cli.path`)
}

/** Run a `.py` under python3, anything else as the executable itself. */
export const ingestArgv = (cli: string): string[] => (cli.endsWith('.py') ? ['python3', cli, 'ingest'] : [cli, 'ingest'])

/** Shadow mode points the child's census at the shadow dir; ingest honours `CENSUS_STORE`. */
export function ingestEnv(env: CensusEnv): Record<string, string> | undefined {
  const dir = shadowDir(env)
  return dir ? { CENSUS_STORE: dir } : undefined
}

export const WHICH_ARGV = ['sh', '-c', 'command -v census'] as const

/** Time budgets (ms) */
export const INGEST_TIMEOUT_MS = 10_000
export const COALESCE_MS = 2000
export const END_RESERVE_MS = 300
export const END_MIN_MS = 200

/** `timeoutMs` for the final ingest so it finishes under `session.end`'s shared budget. */
export function endTimeoutMs(remainingMs: number): number {
  if (!Number.isFinite(remainingMs)) return 1000
  return Math.max(END_MIN_MS, Math.min(1000, Math.floor(remainingMs) - END_RESERVE_MS))
}

/** How long to wait before the next ingest may run: 0 when the last was over `COALESCE_MS` ago. */
export function delayFor(now: number, lastAt: number | null): number {
  return lastAt === null ? 0 : Math.max(0, lastAt + COALESCE_MS - now)
}
