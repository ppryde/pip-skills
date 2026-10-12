// The session's name as the transcript holds it, and the archive name a handover gives the
// outgoing session — PROBES §8, §15. Only a `custom-title` line is a name; Claude Code's own
// `ai-title` is not.

export const ARCHIVE_PREFIX = 'Archive: '

// Prints the transcript's last custom-title line; exits 1 when it has none, 2 when grep cannot
// read it. Positional args: $1 = transcript path.
export const TITLE_CMD = 'out=$(grep -F \'"type":"custom-title"\' "$1"); s=$?; [ "$s" -eq 0 ] && printf \'%s\\n\' "$out" | tail -n 1; exit $s'

/** The last custom title in transcript text: null = none, undefined = a title line that does not parse (cannot tell). */
export function lastTitle(text: string): string | null | undefined {
  const lines = text.split('\n')
  for (let i = lines.length - 1; i >= 0; i--) {
    const line = lines[i] ?? ''
    if (!line.includes('"type":"custom-title"')) continue
    try {
      const row = JSON.parse(line) as { customTitle?: unknown }
      return typeof row.customTitle === 'string' ? row.customTitle : undefined
    } catch {
      return undefined
    }
  }
  return null
}

export const isArchived = (name: string): boolean => name.startsWith(ARCHIVE_PREFIX)

/** The outgoing session's name: one prefix, never nested. */
export const archiveName = (name: string): string => (isArchived(name) ? name : `${ARCHIVE_PREFIX}${name}`)

/** The name a successor takes from it: every archive prefix off; '' when nothing is left. */
export function unarchived(name: string): string {
  let n = name
  while (isArchived(n)) n = n.slice(ARCHIVE_PREFIX.length)
  return n.trim()
}
