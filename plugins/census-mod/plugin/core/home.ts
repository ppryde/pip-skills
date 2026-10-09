// Where "home" and the config dir are, on macOS, Linux and Windows. THE SAME FILE lives in census-mod, context-vigil-mod
// and agent-roster (plugins share no code); tests/census/test_home_copies.py fails if the copies differ.
//
// Rule: the config dir is CLAUDE_CONFIG_DIR, else <home>/.claude; <home> is HOME, else USERPROFILE, else
// HOMEDRIVE+HOMEPATH. `~`, `~/x` and `~\x` expand with the same home.

export type HomeEnv = {
  CLAUDE_CONFIG_DIR?: string
  HOME?: string
  USERPROFILE?: string
  HOMEDRIVE?: string
  HOMEPATH?: string
}

/** What was looked at, for messages: name the variables actually checked. */
export const HOME_VARS_CHECKED = 'CLAUDE_CONFIG_DIR, HOME, USERPROFILE and HOMEDRIVE+HOMEPATH'

const nonEmpty = (v: string | undefined): string | undefined => (v && v.trim() ? v : undefined)

/** The home dir: HOME, else USERPROFILE, else HOMEDRIVE+HOMEPATH; null when none is set. */
export function homeOf(env: HomeEnv): string | null {
  const home = nonEmpty(env.HOME) ?? nonEmpty(env.USERPROFILE)
  if (home) return home
  const drive = nonEmpty(env.HOMEDRIVE)
  const path = nonEmpty(env.HOMEPATH)
  return drive && path ? `${drive}${path}` : null
}

/** The separator a base path uses: a backslash when it has one and no slash (`C:\Users\x`), else a slash. */
export const sepOf = (p: string): '/' | '\\' => (p.includes('\\') && !p.includes('/') ? '\\' : '/')

/** Whether a path is absolute on either platform: `/x`, `C:\x`, `C:/x`, `\\server\share`. */
export const isAbsolute = (p: string): boolean => p.startsWith('/') || p.startsWith('\\\\') || /^[A-Za-z]:[\\/]/.test(p)

/**
 * Trailing separators dropped (slash or backslash), the root kept: `/a/b//` -> `/a/b`, `/` -> `/`,
 * `C:\Users\x\` -> `C:\Users\x`, `C:\` -> `C:\`.
 */
export function trimSeps(p: string): string {
  if (/^[A-Za-z]:$/.test(p)) return p // `C:` is the drive-relative cwd of C:, not the root `C:\`
  if (/^[A-Za-z]:[\\/]+$/.test(p)) return `${p.slice(0, 2)}${p.includes('/') ? '/' : '\\'}`
  const t = p.replace(/[\\/]+$/, '')
  return t || (/^[\\/]/.test(p) ? p[0] ?? '/' : p)
}

/** `base` + parts, joined with the separator the base uses, so `C:\Users\x` + `.claude` stays all backslashes. */
export function joinPath(base: string, ...parts: string[]): string {
  const sep = sepOf(base)
  const root = trimSeps(base)
  const tail = parts.map(p => p.replace(/^[\\/]+|[\\/]+$/g, '')).filter(Boolean).join(sep)
  const joined = root.endsWith('/') || root.endsWith('\\') || /^[A-Za-z]:$/.test(root) ? `${root}${tail}` : `${root}${sep}${tail}`
  return tail ? joined.replace(sep === '\\' ? /\//g : /\\/g, sep) : root
}

/** `~`, `~/x` or `~\x` with the home dir (in the home's own separator); anything else unchanged. */
export function expandHome(p: string, env: HomeEnv): string {
  const home = homeOf(env)
  if (!home || !(p === '~' || p.startsWith('~/') || p.startsWith('~\\'))) return p
  return p === '~' ? trimSeps(home) : joinPath(home, p.slice(2))
}

/** The config dir: CLAUDE_CONFIG_DIR, else <home>/.claude; null when neither can be told. */
export function configRootOf(env: HomeEnv): string | null {
  const set = nonEmpty(env.CLAUDE_CONFIG_DIR)
  if (set) return trimSeps(set)
  const home = homeOf(env)
  return home ? joinPath(home, '.claude') : null
}

/** A path as a comparison key: one separator, no trailing one, lower-cased when it is a Windows (drive or UNC) path. */
export function pathKey(p: string): string {
  const flat = p.replace(/\\/g, '/')
  const trimmed = flat.length > 1 ? flat.replace(/\/+$/, '') || '/' : flat
  return /^[A-Za-z]:/.test(p) || p.startsWith('\\\\') ? trimmed.toLowerCase() : trimmed
}
