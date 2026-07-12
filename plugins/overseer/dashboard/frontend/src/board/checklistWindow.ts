/**
 * A single task-checklist row, as served by the backend on both `BoardCard`
 * and `CardDetail` (see plugins/overseer/scripts/models.py `Card.from_text`
 * — `task`/`subject`/`status` are always coerced to strings, and `status`
 * passes through verbatim with NO enum/validation: unknown values (or the
 * literal string `"None"`, from null YAML frontmatter) are expected and must
 * fall back to "pending" styling — see `ChecklistRows`'s `bucket()`.
 */
export interface ChecklistEntry {
  task: string;
  subject: string;
  status: string;
}

export interface ChecklistWindowResult {
  visible: ChecklistEntry[];
  activeIndex: number | null;
}

/**
 * Pure windowing logic (no React) for the tile's 5-row focus window.
 * "Active" is the entry the user most likely cares about right now:
 *   1. the first `in_progress` entry, else
 *   2. the first entry that isn't `completed` (covers "pending"/unknown
 *      statuses that haven't started), else
 *   3. the last entry (an all-completed checklist highlights its tail).
 *
 * The window is `max` entries wide, centred on the active entry, then
 * clamped to the list's bounds so short lists never get padding and long
 * lists never scroll past either end.
 */
export function checklistWindow(
  entries: ChecklistEntry[],
  max = 5
): ChecklistWindowResult {
  if (entries.length === 0) return { visible: [], activeIndex: null };

  let active = entries.findIndex((e) => e.status === "in_progress");
  if (active === -1) active = entries.findIndex((e) => e.status !== "completed");
  if (active === -1) active = entries.length - 1;

  const half = Math.floor(max / 2);
  const start = Math.max(0, Math.min(active - half, entries.length - max));
  const visible = entries.slice(start, start + max);

  return { visible, activeIndex: active - start };
}
