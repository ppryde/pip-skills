/**
 * Board layout: buckets cards into lanes by status/stage ONLY.
 *
 * Load-bearing rule (see wf005-context.md "Column / lane model"): `is_epic`
 * drives UI only (rollup line + expand-to-highlight in the components layer).
 * It NEVER changes placement — an epic card, and every one of its children,
 * is placed here purely by its own `status`/`stage`, exactly like any other
 * card. Nothing here special-cases `is_epic` or `parent` — that is the
 * guarantee that no child is ever nested/hidden/duplicated.
 */
import type { BoardCard, Stage } from "../api/types";

export type LaneKind = "backlog" | "stage" | "parked" | "done" | "archive";

export interface Lane {
  key: string;
  label: string;
  kind: LaneKind;
  stage?: Stage;
  cards: BoardCard[];
}

/** STAGE order, mirrored from plugins/overseer/scripts/models.py STAGES. */
export const STAGES: Stage[] = [
  "bootstrap",
  "planning",
  "plan-review",
  "implementation",
  "impl-review",
  "verification",
  "awaiting-merge",
];

const STAGE_LABELS: Record<Stage, string> = {
  bootstrap: "Bootstrap",
  planning: "Planning",
  "plan-review": "Plan Review",
  implementation: "Implementation",
  "impl-review": "Impl Review",
  verification: "Verification",
  "awaiting-merge": "Awaiting Merge",
};

function sortLane(cards: BoardCard[]): BoardCard[] {
  return [...cards].sort((a, b) => {
    if (a.order !== b.order) return a.order - b.order;
    return a.id.localeCompare(b.id);
  });
}

export function groupIntoLanes(cards: BoardCard[]): Lane[] {
  const backlog: BoardCard[] = [];
  const stageBuckets = new Map<Stage, BoardCard[]>(STAGES.map((s) => [s, []]));
  const parked: BoardCard[] = [];
  const done: BoardCard[] = [];
  const archive: BoardCard[] = [];

  for (const c of cards) {
    if (c.status === "planned" || (c.status === "blocked" && c.stage == null)) {
      backlog.push(c);
    } else if (
      c.stage != null &&
      (c.status === "in-flight" || c.status === "blocked") &&
      stageBuckets.has(c.stage)
    ) {
      stageBuckets.get(c.stage)!.push(c);
    } else if (c.status === "parked") {
      parked.push(c);
    } else if (c.status === "done") {
      done.push(c);
    } else if (c.status === "abandoned") {
      archive.push(c);
    } else {
      // Defensive fallback: per the frozen contract, in-flight/blocked cards
      // always carry a valid stage (server enforces this — see models.py
      // set_stage()/unblock()). If that invariant is ever violated, land the
      // card in Backlog rather than silently dropping it from the board.
      backlog.push(c);
    }
  }

  const lanes: Lane[] = [
    { key: "backlog", label: "Backlog", kind: "backlog", cards: sortLane(backlog) },
    ...STAGES.map((stage): Lane => ({
      key: `stage:${stage}`,
      label: STAGE_LABELS[stage],
      kind: "stage",
      stage,
      cards: sortLane(stageBuckets.get(stage)!),
    })),
    { key: "parked", label: "Parked", kind: "parked", cards: sortLane(parked) },
    { key: "done", label: "Done", kind: "done", cards: sortLane(done) },
    { key: "archive", label: "Archive", kind: "archive", cards: sortLane(archive) },
  ];

  return lanes;
}
