// The session's name as the transcript holds it, and the archive name a handover gives the
// outgoing session — PROBES §8, §15. Only a `custom-title` line is a name; Claude Code's own
// `ai-title` is not.

export const ARCHIVE_PREFIX = 'Archive: '

// A title row as the engine writes it: `type` is its first key (all 2,419 custom-title rows in two
// accounts' transcripts, 2026-10-12). Anchored, so text nested in another row (a tool input) never matches.
export const TITLE_ROW = '{"type":"custom-title"'

// Prints the transcript's last title row; exits 1 when it has none, 2 when grep cannot read it.
// Positional args: $1 = transcript path. (BRE: `{` is literal.)
export const TITLE_CMD = `out=$(grep '^${TITLE_ROW}' "$1"); s=$?; [ "$s" -eq 0 ] && printf '%s\\n' "$out" | tail -n 1; exit $s`

/** The last custom title in transcript text: null = none, undefined = a title line that does not parse (cannot tell). */
export function lastTitle(text: string): string | null | undefined {
  const lines = text.split('\n')
  for (let i = lines.length - 1; i >= 0; i--) {
    const line = lines[i] ?? ''
    if (!line.startsWith(TITLE_ROW)) continue
    let row: { type?: unknown; customTitle?: unknown }
    try {
      row = JSON.parse(line) as typeof row
    } catch {
      return undefined
    }
    if (row?.type !== 'custom-title') continue
    return typeof row.customTitle === 'string' ? row.customTitle : undefined
  }
  return null
}

export const isArchived = (name: string): boolean => name.startsWith(ARCHIVE_PREFIX)

/** The outgoing session's name: one prefix, never nested. */
export const archiveName = (name: string): string => (isArchived(name) ? name : `${ARCHIVE_PREFIX}${name}`)
