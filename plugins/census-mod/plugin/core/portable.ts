// What the hooks file runs outside the engine, per platform. Pure: no `$`. A path says which platform it is on
// (`C:\x` and `\\server\x` are Windows, `/x` is POSIX), so nothing here sniffs the OS.
import { isAbsolute } from './home'

export const onWindows = (path: string): boolean => isAbsolute(path) && !path.startsWith('/')

/** Python launchers to try, in order: `python3` (macOS, Linux), `python`, then the Windows launcher `py -3`. */
export const PYTHON_CANDIDATES: readonly (readonly string[])[] = [['python3'], ['python'], ['py', '-3']]

/** The first launcher whose `--version` ran, given a probe that says whether one did; null when none. */
export async function pickPython(works: (argv: string[]) => Promise<boolean>): Promise<string[] | null> {
  for (const candidate of PYTHON_CANDIDATES) {
    const argv = [...candidate, '--version']
    if (await works(argv).catch(() => false)) return [...candidate]
  }
  return null
}

/** Rename `from` over `to`: `mv -f`, or `cmd /c move /Y` on Windows. */
export const moveArgv = (from: string, to: string): string[] =>
  onWindows(to) ? ['cmd', '/c', 'move', '/Y', from, to] : ['mv', '-f', from, to]

/** Remove a file, quietly when it is not there: `rm -f`, or `cmd /c del /F /Q` on Windows. */
export const removeArgv = (path: string): string[] =>
  onWindows(path) ? ['cmd', '/c', 'del', '/F', '/Q', path] : ['rm', '-f', path]

/** Copy keeping the mode (POSIX only: a Windows file has no mode to keep, so there is nothing to run). */
export const copyModeArgv = (from: string, to: string): string[] | null => (onWindows(to) ? null : ['cp', '-p', from, to])

/** What `tail -c N file | grep -o '"cache_creation":{[^}]*}'` prints, from the file's text (for where there is no sh). */
export function cacheLinesFromText(text: string, bytes = 65536): string {
  return (text.slice(-bytes).match(/"cache_creation":\{[^}]*\}/g) ?? []).join('\n')
}

/** What `grep -F '"type":"custom-title"'` prints (the last `bytes` of the file only when given). */
export function titleLinesFromText(text: string, bytes?: number): string {
  return (bytes ? text.slice(-bytes) : text).split('\n').filter(l => l.includes('"type":"custom-title"')).join('\n')
}
