// The Windows stand-ins for the POSIX tools the roster shells out to. Pure: no `$`.
import { isAbsolute } from './home'

/** A drive or UNC path is a Windows one; `/x` is POSIX. The mod cannot see the OS, so the config dir says. */
export const onWindowsPath = (path: string): boolean => isAbsolute(path) && !path.startsWith('/')

/** `tasklist /FO CSV /NH` rows (`"claude.exe","1234","Console","1","50,000 K"`): the pids whose image is Claude Code. */
export function claudePidsInTasklist(csv: string): Set<number> {
  const pids = new Set<number>()
  for (const line of csv.split('\n')) {
    const m = /^"([^"]+)","(\d+)"/.exec(line.trim())
    if (m && /^(claude|node|bun)(\.exe)?$/i.test(m[1]!) && Number(m[2]) > 4) pids.add(Number(m[2]))
  }

  return pids
}

/** Ending a pid: `kill`, or `taskkill /PID n /F` on Windows (a console app ignores the polite form). */
export const killArgv = (pid: number, windows: boolean): string[] => (windows ? ['taskkill', '/PID', String(pid), '/F'] : ['kill', String(pid)])
