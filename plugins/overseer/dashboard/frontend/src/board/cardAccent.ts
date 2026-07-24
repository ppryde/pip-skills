/**
 * Single-card accent classification (WF-030 chunk 1) — the drawer's header
 * banner pill needs the SAME accent key/label a card would get from its
 * lane, but the drawer only ever has one card in hand, not the whole board.
 * Duplicates `layout.ts`'s ~10-line status/stage classification rather than
 * refactoring `groupIntoLanes` — that function is load-bearing for drag/
 * drop and out of scope this late in the epic (Decisions: blast-radius
 * minimisation over DRY).
 *
 * Mirrors Lane.tsx's accentKey convention exactly, including the archive->
 * "parked" mapping (11 lanes, 10 --qb-col-* accent groups — Archive reuses
 * the taupe/Parked group, adjudicated in WF-028).
 */
import type { BoardCard, Stage } from "../api/types";
import { STAGES, STAGE_LABELS } from "./layout";

export type CardForAccent = Pick<BoardCard, "status" | "stage">;

/** Which lane this card's own status/stage would place it in — mirrors
 * `groupIntoLanes`'s per-card branching (layout.ts) without the collection
 * bookkeeping. */
function laneKindForCard(
  card: CardForAccent
): "backlog" | "stage" | "parked" | "done" | "archive" {
  if (
    card.status === "planned" ||
    (card.status === "blocked" && card.stage == null)
  ) {
    return "backlog";
  }
  if (
    card.stage != null &&
    (card.status === "in-flight" || card.status === "blocked") &&
    STAGES.includes(card.stage)
  ) {
    return "stage";
  }
  if (card.status === "parked") return "parked";
  if (card.status === "done") return "done";
  if (card.status === "abandoned") return "archive";
  // Defensive fallback, mirrors layout.ts: an in-flight/blocked card without
  // a valid stage violates the frozen contract, but lands in Backlog rather
  // than silently dropping any accent classification.
  return "backlog";
}

/** The guild accent key for a single card — same value Lane.tsx computes
 * for the lane that card would land in. */
export function accentKeyForCard(card: CardForAccent): string {
  const kind = laneKindForCard(card);
  if (kind === "archive") return "parked";
  if (kind === "stage") return card.stage as Stage;
  return kind;
}

/** The banner label for a single card — same text the lane header would
 * show. Archive is the one place key and label diverge (key "parked",
 * label "Archive" — the lane's own name, not its borrowed accent group's). */
export function bannerLabelForCard(card: CardForAccent): string {
  const kind = laneKindForCard(card);
  switch (kind) {
    case "backlog":
      return "Backlog";
    case "parked":
      return "Parked";
    case "done":
      return "Done";
    case "archive":
      return "Archive";
    case "stage":
      return STAGE_LABELS[card.stage as Stage];
  }
}
