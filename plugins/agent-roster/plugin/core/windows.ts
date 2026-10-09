// The Windows stand-ins for the POSIX tools the roster shells out to. Pure: no `$`.
import { isAbsolute } from './home'

/** A drive or UNC path is a Windows one; `/x` is POSIX. The mod cannot see the OS, so the config dir says. */
export const onWindowsPath = (path: string): boolean => isAbsolute(path) && !path.startsWith('/')

/** Pids are integers from the registry; anything else is dropped before it can reach a command line. */
const safePids = (pids: readonly number[]): number[] => pids.filter(p => Number.isInteger(p) && p > 4)

/**
 * The PowerShell that lists, one tab-separated line per pid, `pid <TAB> creation epoch ms <TAB> command line`. The pids
 * are integers checked above, so nothing the registry holds is ever spelled into the script as text.
 */
export function procListArgv(pids: readonly number[]): string[] | null {
  const ok = safePids(pids)
  if (ok.length === 0) return null
  const filter = ok.map(p => `ProcessId=${p}`).join(' OR ')
  const script =
    `Get-CimInstance Win32_Process -Filter '${filter}' | ForEach-Object { ` +
    '"$($_.ProcessId)`t$([DateTimeOffset]$_.CreationDate).ToUnixTimeMilliseconds())`t$($_.CommandLine)" }'

  return ['powershell', '-NoProfile', '-NonInteractive', '-Command', script]
}

export type WinProc = { createdMs: number; command: string }

/** The `procListArgv` output as pid -> creation time and command line. */
export function procsInList(out: string): Map<number, WinProc> {
  const procs = new Map<number, WinProc>()
  for (const line of out.split('\n')) {
    const [pid, created, ...rest] = line.replace(/\r$/, '').split('\t')
    if (/^\d+$/.test(pid ?? '') && /^\d+$/.test(created ?? '')) procs.set(Number(pid), { createdMs: Number(created), command: rest.join('\t') })
  }

  return procs
}

/**
 * Is this command line Claude Code: the `claude` executable, or a runtime running claude-code's entrypoint? A bare
 * `node.exe` or `bun.exe` is not: a reused pid could be any Node app.
 */
export function isClaudeCommand(command: string): boolean {
  const first = /^"([^"]*)"|^(\S+)/.exec(command.trim())
  const head = first?.[1] ?? first?.[2] ?? ''
  if (/(^|[\\/])claude(\.exe)?$/i.test(head)) return true

  return /(^|[\\/"'\s])@anthropic-ai[\\/]claude-code[\\/]/i.test(command)
}

/** Ending a pid: `kill`, or `taskkill /PID n /F` on Windows (a console app ignores the polite form). */
export const killArgv = (pid: number, windows: boolean): string[] => (windows ? ['taskkill', '/PID', String(pid), '/F'] : ['kill', String(pid)])
