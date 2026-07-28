import type { RepoEntry } from "../api/types";

export interface RepoSelectorProps {
  repos: RepoEntry[];
  activeRoot: string | null;
  onSelect: (root: string) => void;
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
 */
function RepoSelector({ repos, activeRoot, onSelect }: RepoSelectorProps) {
  if (repos.length === 0) return null;

  // Prefer the caller's selection if it's still a known root (survives a
  // repos refresh); else the backend's own launch root; else just the
  // first entry — always SOME valid, renderable value for `<select>`.
  const known = activeRoot && repos.some((r) => r.root === activeRoot);
  const selected = known
    ? (activeRoot as string)
    : repos.find((r) => r.current)?.root ?? repos[0].root;

  return (
    <label className="topbar__repo-select">
      <span className="topbar__repo-select-label">repo</span>
      <select
        aria-label="Repo"
        value={selected}
        onChange={(e) => onSelect(e.target.value)}
      >
        {repos.map((r) => (
          <option key={r.root} value={r.root}>
            {r.label}
          </option>
        ))}
      </select>
    </label>
  );
}

export default RepoSelector;
