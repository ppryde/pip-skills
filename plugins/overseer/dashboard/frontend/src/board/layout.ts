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

export const STAGE_LABELS: Record<Stage, string> = {
  bootstrap: "Bootstrap",
  planning: "Planning",
  "plan-review": "Plan Review",
  implementation: "Implementation",
  "impl-review": "Impl Review",
  verification: "Verification",
  "awaiting-merge": "Awaiting Merge",
};

/** Blank/missing timestamps parse to epoch 0 (sort last under a desc
 * comparator) — same blank-tolerant contract documented on `BoardCard.created`
 * / `BoardCard.updated` in api/types.ts. */
function parseRecency(value: string | null | undefined): number {
  if (!value) return 0;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

/** Recency comparator: `updated` desc, tiebreak `created` desc, then `id`
 * ascending for a fully deterministic order (two cards with identical
 * updated/created timestamps always render in the same relative order). */
function compareRecency(a: BoardCard, b: BoardCard): number {
  const updatedDelta = parseRecency(b.updated) - parseRecency(a.updated);
  if (updatedDelta !== 0) return updatedDelta;
  const createdDelta = parseRecency(b.created) - parseRecency(a.created);
  if (createdDelta !== 0) return createdDelta;
  return a.id.localeCompare(b.id);
}

function mostRecent(a: BoardCard, b: BoardCard): BoardCard {
  return compareRecency(a, b) <= 0 ? a : b;
}

interface CardGroup {
  /** Flattened render order: the group's root card first, then its
   * same-lane descendants (each preceded by its own parent), depth-first. */
  cards: BoardCard[];
  /** Group's sort key card — see `sortLane` doc comment for the policy. */
  key: BoardCard;
}

/** Depth-first-flattens `root` plus every same-lane descendant reachable
 * through `childrenByParent` (a card is a "same-lane descendant" only if its
 * `parent` chain resolves to `root` without ever leaving this lane — see
 * `sortLane`). Direct children are ordered by recency desc among themselves;
 * each child's own descendants (if any) are flattened immediately after it. */
function flattenGroup(
  root: BoardCard,
  childrenByParent: Map<string, BoardCard[]>
): CardGroup {
  const children = [...(childrenByParent.get(root.id) ?? [])].sort(compareRecency);
  const cards = [root];
  let key = root;
  for (const child of children) {
    const sub = flattenGroup(child, childrenByParent);
    cards.push(...sub.cards);
    key = mostRecent(key, sub.key);
  }
  return { cards, key };
}

/**
 * Sorts a single lane's cards by recency (most-recently-`updated` first)
 * while keeping epic groups intact.
 *
 * Epic grouping: a card whose `parent` is ALSO present in this same lane is
 * folded into its parent's group instead of being ranked as its own top-level
 * item — the group renders as [parent, ...same-lane children (recency desc)]
 * contiguously. A card whose parent is absent from this lane (different
 * lane, or no parent at all) is its own top-level item, ordered by its own
 * recency exactly like any other card — `groupIntoLanes`'s placement-by-
 * status rule is untouched; this only reorders WITHIN a lane.
 *
 * Group ranking policy: a group's sort key is the MOST RECENT `updated`
 * across the group's root card and all its same-lane descendants (not just
 * the root's own `updated`) — so an epic with a freshly-updated child bubbles
 * up with that activity, even if the epic card itself hasn't been touched.
 *
 * `order` (the drag-reorder field) intentionally no longer drives this sort —
 * see its doc comment in api/types.ts — but remains untouched for the drag
 * machinery (order.ts / dragPlan.ts).
 */
function sortLane(cards: BoardCard[]): BoardCard[] {
  const idsInLane = new Set(cards.map((c) => c.id));
  const childrenByParent = new Map<string, BoardCard[]>();
  const roots: BoardCard[] = [];

  for (const c of cards) {
    if (c.parent != null && idsInLane.has(c.parent)) {
      const siblings = childrenByParent.get(c.parent);
      if (siblings) siblings.push(c);
      else childrenByParent.set(c.parent, [c]);
    } else {
      roots.push(c);
    }
  }

  const groups = roots.map((root) => flattenGroup(root, childrenByParent));
  groups.sort((a, b) => compareRecency(a.key, b.key));
  return groups.flatMap((g) => g.cards);
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
