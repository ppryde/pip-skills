import type { RepoEntry } from "../api/types";
// WF-097 follow-up: the eyebrow label and the `<select>` itself now route
// through the design-library primitives (`src/ui/`) — see the call site
// below for which bespoke classes stay (layout/transparent-background
// overrides only) and which were fully absorbed into `.qb-select`.
import { Label, Select } from "../ui";

export interface RepoSelectorProps {
  repos: RepoEntry[];
  activeRoot: string | null;
  onSelect: (root: string) => void;
  /** An "All repos" choice ahead of the list, for pages whose data is
   * account-wide (the Chronicle). When `selected`, the select shows it in
   * place of `activeRoot` — the board's root is untouched underneath, so
   * switching back to the board page lands where it was. Choosing a real
   * repo calls `onSelect` as usual AND `allOption.onSelect(false)`. */
  allOption?: { selected: boolean; onSelect: (all: boolean) => void };
}

/** The `<option>` value standing for "every repo" — no real root can start
 * with a space, so it can never collide with one. */
export const ALL_REPOS_VALUE = " all";

/**
 * An "unbegun" repo (WF-032) has live census sessions but no board.db yet
 * (`has_board: false`) — `<option>` can't host markup, so the live-agent
 * count hint is appended straight into the label text (e.g. "⚔ 6") rather
 * than as a separate child element.
 */
function optionLabel(r: RepoEntry): string {
  return r.has_board === false ? `${r.label} · ⚔ ${r.live_sessions}` : r.label;
}

/**
 * Repo switcher (WF-030) — a `<select>` styled as a topbar chip so it fits
 * the existing crest-row/chip-shelf responsive layout for free: it wraps
 * into the mobile chip shelf exactly like the ctx block and pills around
 * it, no bespoke breakpoint rules needed. Sized to the touch-target layer's
 * ~44px minimum on coarse pointers (styles.css).
 *
 * Renders nothing when no boards are discoverable (a fresh install with no
 * board.db yet, or a failed `/api/repos` fetch) — never crashes on an empty
 * list. Still renders for a single discovered repo (one `<option>`) so
 * "which repo am I looking at" stays visible even before a second exists.
 *
 * Unbegun entries (`has_board: false` — WF-032) render with a distinct
 * class and an appended agent-count hint (`optionLabel` above) but remain
 * fully selectable `<option>`s: choosing one is what routes App.tsx to the
 * `<UnbegunHolding/>` empty state instead of `<Board/>`.
 */
function RepoSelector({ repos, activeRoot, onSelect, allOption }: RepoSelectorProps) {
  if (repos.length === 0) return null;

  // Prefer the caller's selection if it's still a known root (survives a
  // repos refresh); else the backend's own launch root; else just the
  // first entry — always SOME valid, renderable value for `<select>`.
  const known = activeRoot && repos.some((r) => r.root === activeRoot);
  const selectedRoot = known
    ? (activeRoot as string)
    : repos.find((r) => r.current)?.root ?? repos[0].root;
  const selected = allOption?.selected ? ALL_REPOS_VALUE : selectedRoot;

  return (
    <label className="topbar__repo-select">
      <Label className="topbar__repo-select-label">repo</Label>
      <Select
        aria-label="Repo"
        value={selected}
        onChange={(e) => {
          if (e.target.value === ALL_REPOS_VALUE) {
            allOption?.onSelect(true);
            return;
          }
          allOption?.onSelect(false);
          onSelect(e.target.value);
        }}
      >
        {allOption && (
          <option value={ALL_REPOS_VALUE} className="repo-option repo-option--all">
            All repos
          </option>
        )}
        {repos.map((r) => (
          <option
            key={r.root}
            value={r.root}
            className={
              r.has_board === false ? "repo-option repo-option--unbegun" : "repo-option"
            }
            title={
              r.has_board !== false
                ? undefined
                : r.live_sessions > 0
                  ? `Quest not yet begun — ${r.live_sessions} adventurer(s) present, no Guild Board raised`
                  // Chronicled but boardless: the old copy promised adventurers
                  // that are not there. These repos are in the list because the
                  // Chronicle can be scoped to them, not because anyone is in
                  // them right now.
                  : "No Guild Board raised — chronicled deeds only"
            }
          >
            {optionLabel(r)}
          </option>
        ))}
      </Select>
    </label>
  );
}

export default RepoSelector;
