/**
 * Mobile icon-nav (WF-085): one transparent RPG icon per lane. Icons are
 * `import`ed (not referenced by string path) so Vite fingerprints/bundles
 * them into `dist/assets` like any other build asset — see
 * `src/assets/lane-icons/*.png` (compressed to ~64px, a few KB each; the
 * raw ~150KB/file originals must never ship).
 *
 * The icon KEY is deliberately the same string as the lane accent key
 * already used for `.lane__header--<key>` / `.card-tile--accent-<key>`
 * (see board/layout.ts + Lane.tsx's `accentKey`) — one lane, one accent
 * string, reused for colour AND icon lookup. `laneIconKey` is the single
 * place that derives it from a `Lane`, so the icon-nav and the lane header
 * can never disagree about which lane a colour/icon belongs to.
 */
import type { Lane } from "./layout";
import { STAGE_LABELS, STAGES } from "./layout";
import type { BoardCard, Stage } from "../api/types";

import backlog from "../assets/lane-icons/backlog.png";
import bootstrap from "../assets/lane-icons/bootstrap.png";
import planning from "../assets/lane-icons/planning.png";
import planReview from "../assets/lane-icons/plan-review.png";
import implementation from "../assets/lane-icons/implementation.png";
import implReview from "../assets/lane-icons/impl-review.png";
import verification from "../assets/lane-icons/verification.png";
import awaitingMerge from "../assets/lane-icons/awaiting-merge.png";
import done from "../assets/lane-icons/done.png";
import parked from "../assets/lane-icons/parked.png";
import abandoned from "../assets/lane-icons/abandoned.png";
import inProgress from "../assets/lane-icons/in-progress.png";

const ICONS: Record<string, string> = {
  backlog,
  bootstrap,
  planning,
  "plan-review": planReview,
  implementation,
  "impl-review": implReview,
  verification,
  "awaiting-merge": awaitingMerge,
  done,
  parked,
  abandoned,
  "in-progress": inProgress,
};

/** Derives a lane's icon/accent key from its `kind`/`stage` — mirrors
 * Lane.tsx's `accentKey`. `archive` (labelled "Abandoned") maps to
 * `abandoned`; every `stage` lane's key IS its `Stage` string already
 * (STAGES in layout.ts lists exactly the 7 stage icon keys below).
 * `in-progress` (WF-085 mobile collapse — `collapseStagesForMobile`'s
 * synthetic lane) is its own key, mapped to the drawn-shortsword icon. */
export function laneIconKey(lane: Lane): string {
  if (lane.kind === "archive") return "abandoned";
  if (lane.kind === "stage") return lane.stage!;
  return lane.kind; // "backlog" | "parked" | "done" | "in-progress"
}

/** Returns the imported/bundled icon URL for a given icon key (one of the
 * 11 values `laneIconKey` can produce). Falls back to the backlog icon for
 * an unrecognised key rather than rendering a broken `<img>` — should never
 * happen in practice since `laneIconKey` only ever emits a known key. */
export function laneIcon(key: string): string {
  return ICONS[key] ?? backlog;
}

/** Part B (WF-085 in-progress lane, mobile card stage icon): a card's own
 * `Stage` maps to the SAME icon its `stage:<S>` lane would use on desktop
 * (a `Stage` string IS already one of `ICONS`' keys — see `laneIconKey`'s
 * `kind === "stage"` branch) — one lookup table, never two icons drifting
 * for the same stage. */
export function stageIcon(stage: Stage): string {
  return laneIcon(stage);
}

/** A card's icon key, mirroring layout.ts::groupIntoLanes bucketing exactly
 * so a card and the lane it sits in never resolve different icons. Returns
 * the SPECIFIC stage key for active staged cards (e.g. "implementation" ->
 * axe), never the synthetic "in-progress" collapse key. */
export function cardIconKey(card: BoardCard): string {
  if (card.status === "planned" || (card.status === "blocked" && card.stage == null))
    return "backlog";
  if (
    card.stage != null &&
    (card.status === "in-flight" || card.status === "blocked") &&
    (STAGES as string[]).includes(card.stage)
  )
    return card.stage;
  if (card.status === "parked") return "parked";
  if (card.status === "done") return "done";
  if (card.status === "abandoned") return "abandoned";
  return "backlog"; // defensive fallback, matches groupIntoLanes
}

/** Human label for any of the 11 icon keys — stage keys reuse STAGE_LABELS,
 * bucket keys get their lane label. */
const BUCKET_LABELS: Record<string, string> = {
  backlog: "Backlog",
  parked: "Parked",
  done: "Done",
  abandoned: "Abandoned",
  "in-progress": "In Progress",
};
export function iconKeyLabel(key: string): string {
  return (STAGE_LABELS as Record<string, string>)[key] ?? BUCKET_LABELS[key] ?? key;
}
