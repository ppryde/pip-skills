import type { Proc } from './types'

/**
 * Claude Code's own session registry holds `<config dir>/sessions/<pid>.json` per live process,
 * with the `procStart` string (ps lstart text, in another zone: only ever compared as a string)
 * and the version. The entry whose `sessionId` is ours names our process.
 */
export function findProc(files: { text: string }[], sessionId: string): Proc | null {
  for (const f of files) {
    let d: unknown
    try {
      d = JSON.parse(f.text)
    } catch {
      continue
    }
    const r = d as { pid?: unknown; sessionId?: unknown; procStart?: unknown; version?: unknown }
    if (r.sessionId !== sessionId || typeof r.pid !== 'number' || r.pid <= 1 || typeof r.procStart !== 'string') continue
    return { pid: r.pid, procStart: r.procStart, ...(typeof r.version === 'string' ? { version: r.version } : {}) }
  }
  return null
}

/** The last `custom-title` row of `grep -F '"type":"custom-title"'` output. */
export function lastTitle(stdout: string): string | null {
  const lines = stdout.split('\n').filter(l => l.includes('"custom-title"'))
  for (let i = lines.length - 1; i >= 0; i--) {
    try {
      const t = (JSON.parse(lines[i] ?? '') as { customTitle?: unknown }).customTitle
      if (typeof t === 'string' && t.trim()) return t.trim()
    } catch {
      // a row cut mid-write; try the one before
    }
  }
  return null
}

export const TITLE_ARGV = (path: string): string[] => ['grep', '-h', '-F', '"type":"custom-title"', path]
