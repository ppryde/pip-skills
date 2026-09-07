/**
 * Which repo the Chronicle may be scoped to (WF-108).
 *
 * The backend's chronicle routes validate a requested root against the union
 * of BOARD roots and the roots chronicle itself has sessions for. Naming a
 * root outside that union is a 400, so the page must pin such a repo to
 * "All repos" rather than fetch and fail.
 *
 * Before WF-108 the test was simply `has_board`, which made a repo Claude Code
 * had worked in for months — but that no board was ever raised for — visible
 * only under "All repos", despite being the largest in the store.
 */
import type { RepoEntry } from "../../api/types";

export type ChronicleScope = "repo" | "all";

/** Whether `repo` can be named on the chronicle routes. `null` means no
 * selection — the server falls back to its own launch root, which is always
 * nameable, so that scopes normally. */
export function isChronicleScopable(repo: RepoEntry | null): boolean {
  if (!repo) return true;
  // `?? has_board` is what a backend from before WF-108 implies: without the
  // flag, a boardless root is exactly what the chronicle routes refused.
  return repo.chronicled ?? repo.has_board;
}

export function chronicleScopeFor(repo: RepoEntry | null, allRepos: boolean): ChronicleScope {
  return allRepos || !isChronicleScopable(repo) ? "all" : "repo";
}
