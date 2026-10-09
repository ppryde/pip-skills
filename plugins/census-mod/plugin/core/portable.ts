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

// Windows has no argv-only move/delete: `cmd /c` would parse the paths as a command line. So there, nothing is spawned:
// the caller writes the file in place and empties a backup instead of deleting it (see the hooks file).

/** Rename `from` over `to` with `mv -f`; null on Windows. */
export const moveArgv = (from: string, to: string): string[] | null => (onWindows(to) ? null : ['mv', '-f', from, to])

/** Remove a file, quietly when it is not there, with `rm -f`; null on Windows. */
export const removeArgv = (path: string): string[] | null => (onWindows(path) ? null : ['rm', '-f', path])

/** Copy keeping the mode (POSIX only: a Windows file has no mode to keep, so there is nothing to run). */
export const copyModeArgv = (from: string, to: string): string[] | null => (onWindows(to) ? null : ['cp', '-p', from, to])

/** The last `bytes` UTF-8 bytes of the text (as `tail -c` takes them), not the last UTF-16 units: a cut mid-character is dropped. */
export function tailBytes(text: string, bytes: number): string {
  let used = 0
  let i = text.length
  while (i > 0) {
    const code = text.charCodeAt(i - 1)
    const isLow = code >= 0xdc00 && code <= 0xdfff && i > 1
    const size = isLow ? 4 : code < 0x80 ? 1 : code < 0x800 ? 2 : 3
    if (used + size > bytes) break
    used += size
    i -= isLow ? 2 : 1
  }

  return text.slice(i)
}

/** What `tail -c N file | grep -o '"cache_creation":{[^}]*}'` prints, from the file's text (for where there is no sh). */
export function cacheLinesFromText(text: string, bytes = 65536): string {
  return (tailBytes(text, bytes).match(/"cache_creation":\{[^}]*\}/g) ?? []).join('\n')
}

/** What `grep -F '"type":"custom-title"'` prints (the last `bytes` of the file only when given). */
export function titleLinesFromText(text: string, bytes?: number): string {
  return (bytes ? tailBytes(text, bytes) : text).split('\n').filter(l => l.includes('"type":"custom-title"')).join('\n')
}
