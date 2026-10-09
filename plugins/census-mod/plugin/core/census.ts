export type CensusEnv = {
  CENSUS_MOD_STORE?: string
  CENSUS_STORE?: string
  CLAUDE_CONFIG_DIR?: string
  HOME?: string
}

const trim = (p: string): string => (p.length > 1 ? p.replace(/\/+$/, '') || '/' : p)
/** Census reads a store ending `.json` as that FILE: its census dir is the parent (store.census_dir). */
const asDir = (p: string): string => (p.endsWith('.json') ? trim(p.slice(0, p.lastIndexOf('/')) || '/') : p)
const expand = (p: string, home?: string): string => (home && (p === '~' || p.startsWith('~/')) ? home.replace(/\/+$/, '') + p.slice(1) : p)

/** Shadow mode: the store value as given (`~` expanded), which census itself reads, `.json` and all. */
export function shadowStore(env: CensusEnv): string | null {
  return env.CENSUS_MOD_STORE ? trim(expand(env.CENSUS_MOD_STORE, env.HOME)) : null
}

/** Shadow mode: the DIR that store lives in, where `cli.path` sits. */
export function shadowDir(env: CensusEnv): string | null {
  const store = shadowStore(env)
  return store ? asDir(store) : null
}

/** The census dir readers use: `CENSUS_STORE`, else `<config dir>/census`. */
export function censusDir(env: CensusEnv): string | null {
  if (env.CENSUS_STORE) return asDir(trim(expand(env.CENSUS_STORE, env.HOME)))
  const root = env.CLAUDE_CONFIG_DIR ? trim(env.CLAUDE_CONFIG_DIR) : env.HOME ? `${trim(env.HOME)}/.claude` : null
  return root ? `${root}/census` : null
}

/**
 * census-mod records through its OWN bundled copy of census's ingest (`<plugin root>/scripts/cli.py`), never through a
 * census plugin: a Python script run under python3 with a list argv.
 */
export const bundledCli = (pluginRoot: string): string => `${pluginRoot.replace(/[\\/]+$/, '')}/scripts/cli.py`
export const ingestArgv = (cli: string): string[] => ['python3', cli, 'ingest']

/** Shadow mode points the child's census at the shadow dir; ingest honours `CENSUS_STORE`. */
export function ingestEnv(env: CensusEnv): Record<string, string> | undefined {
  // Unchanged, `.json` included: census reads a file-valued store itself; only our pointer lookup wants the parent.
  const store = shadowStore(env)
  return store ? { CENSUS_STORE: store } : undefined
}

/** Time budgets (ms) */
export const INGEST_TIMEOUT_MS = 10_000
export const COALESCE_MS = 2000
export const END_RESERVE_MS = 200
export const END_MIN_MS = 300

/**
 * `timeoutMs` for the final ingest so it finishes inside `session.end`'s shared budget, or null to
 * skip it: with under END_MIN_MS left an ingest would only overrun the exit.
 */
export function endTimeoutMs(remainingMs: number): number | null {
  if (!Number.isFinite(remainingMs)) return 1000
  if (remainingMs < END_MIN_MS) return null
  return Math.min(1000, Math.floor(remainingMs) - END_RESERVE_MS)
}

/** How long to wait before the next ingest may run: 0 when the last was over `COALESCE_MS` ago. */
export function delayFor(now: number, lastAt: number | null): number {
  return lastAt === null ? 0 : Math.max(0, lastAt + COALESCE_MS - now)
}
