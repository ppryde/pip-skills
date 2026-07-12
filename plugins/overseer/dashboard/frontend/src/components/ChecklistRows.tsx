import { useEffect, useRef } from "react";
import type { ChecklistEntry } from "../board/checklistWindow";

export interface ChecklistRowsProps {
  entries: ChecklistEntry[];
  /** Tile mode: renders inside an edge-faded fixed-height focus window.
   * Omitted (false) for the drawer's full, unfaded list. */
  windowed?: boolean;
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
 * (e.g. the board poll surfacing a newly-added task) animate in.
 */
function ChecklistRows({ entries, windowed = false }: ChecklistRowsProps) {
  // Seeded synchronously on first render (not via useEffect) so the very
  // first paint has zero "new" rows — see the doc comment above.
  const prevIdsRef = useRef<Set<string> | null>(null);
  if (prevIdsRef.current === null) {
    prevIdsRef.current = new Set(entries.map((e) => e.task));
  }
  const prevIds = prevIdsRef.current;

  // After THIS render commits, remember its ids as "the last render" for
  // the NEXT render's appear diff.
  useEffect(() => {
    prevIdsRef.current = new Set(entries.map((e) => e.task));
  });

  return (
    <ul className={windowed ? "checklist checklist--windowed" : "checklist"}>
      {entries.map((e) => {
        const b = bucket(e.status);
        const isNew = !prevIds.has(e.task);
        return (
          <li
            key={e.task}
            className={
              "checklist__row checklist__row--" +
              b +
              (isNew ? " checklist__row--appear" : "")
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
