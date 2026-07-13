import { useEffect, useRef } from "react";
import type { ChecklistEntry } from "../board/checklistWindow";

export interface ChecklistRowsProps {
  entries: ChecklistEntry[];
  /** Tile mode: renders as a fixed-height sliding-wheel window (active row
   * centred and full-strength, neighbours faded per `activeIndex`).
   * Omitted (false) for the drawer's full, unfaded list. */
  windowed?: boolean;
  /** Index into `entries` of the active row (from `checklistWindow`).
   * Only meaningful when `windowed` — drives the per-row fade and the
   * slide animation when the active task advances. Ignored otherwise. */
  activeIndex?: number | null;
}

type Bucket = "in_progress" | "completed" | "pending";

/** ANY status other than the two known in-progress-workflow values buckets
 * to "pending" — this deliberately also covers the literal string "None"
 * (backend `str(None)` for null YAML frontmatter) and any future/unknown
 * status the backend passes through verbatim. */
function bucket(status: string): Bucket {
  return status === "in_progress" || status === "completed" ? status : "pending";
}

const GLYPH: Record<Bucket, string> = {
  pending: "○",
  in_progress: "●",
  completed: "✓",
};

/**
 * Renders a checklist as a plain, INERT `<ul>` of `<li>` rows — no
 * button/anchor/role anywhere. This is deliberate: the tile usage renders
 * these rows INSIDE `TileShell`'s non-interactive body div (see that
 * file's comment on the no-nested-interactive invariant), so a stray
 * interactive element here would nest inside the body's click target and
 * break the Board/TileShell no-nested-interactive sweep tests.
 *
 * Rows whose `task` id wasn't present in the PREVIOUS render get the
 * `--appear` class for one render, driving the fade/slide-in motion in
 * styles.css (`checklist__row--appear`). On the very first mount nothing
 * is "new" relative to a checklist that didn't exist before, so no row
 * appears animated on initial paint — only rows added by a later refresh
 * (e.g. the board poll surfacing a newly-added task) animate in. Since the
 * tile only ever passes its WINDOWED subset as `entries`, a row that
 * scrolls into view because the wheel advanced counts as "new" here too —
 * that's deliberate, it's the row's first appearance in the window.
 *
 * When `windowed`, `activeIndex` also drives two more windowed-only
 * effects, both keyed off distance from the active row rather than raw
 * position (the active row isn't always centred — see checklistWindow's
 * clamping): each row gets a `checklist__row--active` /`--dist-1` /
 * `--dist-2` class (opacity fade toward the wheel's edges), and if the
 * ACTIVE entry's `task` id changed since the last render (the wheel
 * advanced to the next task), the `<ul>` gets `checklist--shift` for one
 * render, driving a settle-into-place slide in styles.css. Both use the
 * same seed-on-mount + useEffect-refresh pattern as `prevIdsRef` above so
 * neither fires on initial paint.
 */
function ChecklistRows({
  entries,
  windowed = false,
  activeIndex = null,
}: ChecklistRowsProps) {
  // Seeded synchronously on first render (not via useEffect) so the very
  // first paint has zero "new" rows — see the doc comment above.
  const prevIdsRef = useRef<Set<string> | null>(null);
  if (prevIdsRef.current === null) {
    prevIdsRef.current = new Set(entries.map((e) => e.task));
  }
  const prevIds = prevIdsRef.current;

  // Same seed-on-mount pattern, tracking the ACTIVE row's task id so a
  // change (the wheel advancing) can be told apart from a mount.
  const activeTask = activeIndex != null ? (entries[activeIndex]?.task ?? null) : null;
  const prevActiveTaskRef = useRef<string | null>(activeTask);
  const didAdvance = windowed && activeTask !== null && prevActiveTaskRef.current !== activeTask;

  // After THIS render commits, remember its ids/active task as "the last
  // render" for the NEXT render's appear/shift diff.
  useEffect(() => {
    prevIdsRef.current = new Set(entries.map((e) => e.task));
    prevActiveTaskRef.current = activeTask;
  });

  return (
    <ul
      className={
        "checklist" +
        (windowed ? " checklist--windowed" : "") +
        (didAdvance ? " checklist--shift" : "")
      }
    >
      {entries.map((e, i) => {
        const b = bucket(e.status);
        const isNew = !prevIds.has(e.task);
        const dist = windowed && activeIndex != null ? Math.min(Math.abs(i - activeIndex), 2) : null;
        return (
          <li
            key={e.task}
            className={
              "checklist__row checklist__row--" +
              b +
              (isNew ? " checklist__row--appear" : "") +
              (dist === 0 ? " checklist__row--active" : "") +
              (dist === 1 || dist === 2 ? ` checklist__row--dist-${dist}` : "")
            }
          >
            <span className="checklist__glyph" aria-hidden="true">
              {GLYPH[b]}
            </span>
            <span className="checklist__subject">{e.subject}</span>
          </li>
        );
      })}
    </ul>
  );
}

export default ChecklistRows;
