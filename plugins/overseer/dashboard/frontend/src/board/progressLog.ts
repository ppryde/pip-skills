export interface ProgressLogEntry {
  timestamp: string;
  note: string;
  tokens: string;
}

// Mirrors the EXACT line format Card.log_progress() emits
// (plugins/overseer/scripts/models.py:318):
//   f"- {now} — {note} (~{format_tokens(tokens)} tokens)"
const LINE_RE = /^- (\S+) — (.+?) \(~([^)]+) tokens\)$/;

/**
 * Parses a "## Progress log" section's raw text into structured entries for
 * the quest-log timeline (WF-030 chunk 9, stretch).
 *
 * Returns null — NEVER a partial list — if any line fails to match, or if
 * there's nothing to parse. `log_progress`'s `note` parameter is
 * unconstrained free text (see models.py's own docstring): an embedded
 * newline in a note splits what the backend wrote as ONE logical bullet
 * across TWO physical lines once rendered, and neither resulting line
 * matches the full-line pattern on its own. Silently keeping only the
 * lines that happen to match would misrepresent the log (silently
 * dropping/reordering entries) rather than admitting the section can't be
 * parsed — so any single unparseable line invalidates the whole result,
 * and callers fall back to plain-section rendering (the existing
 * MarkdownView path).
 */
export function parseProgressLog(text: string): ProgressLogEntry[] | null {
  const lines = text.split("\n").filter((l) => l.trim() !== "");
  if (lines.length === 0) return null;

  const entries: ProgressLogEntry[] = [];
  for (const line of lines) {
    const match = LINE_RE.exec(line);
    if (!match) return null;
    const [, timestamp, note, tokens] = match;
    entries.push({ timestamp, note, tokens });
  }
  return entries;
}
