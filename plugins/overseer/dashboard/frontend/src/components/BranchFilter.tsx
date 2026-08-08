const ALL_VALUE = "";

export interface BranchFilterProps {
  branches: string[];
  activeBranch: string | null;
  onSelect: (branch: string | null) => void;
}

/**
 * Branch filter (WF-031) — a `<select>` styled as a topbar chip, mirroring
 * `RepoSelector`'s exact shape/conventions: renders nothing when there are
 * no distinct branches to filter by (a fresh board with no branch-carrying
 * cards/sessions yet), always exposes an "All" option that clears the
 * filter (`null`), and falls back to "All" rather than a dangling `<select>`
 * value if `activeBranch` names a branch that's since dropped out of the
 * distinct set. Session-local only — App.tsx owns `activeBranch` state,
 * nothing persists across a reload (unlike the repo selector's
 * localStorage choice).
 */
function BranchFilter({ branches, activeBranch, onSelect }: BranchFilterProps) {
  if (branches.length === 0) return null;

  const selected =
    activeBranch && branches.includes(activeBranch) ? activeBranch : ALL_VALUE;

  return (
    <label className="topbar__branch-select">
      <span className="topbar__branch-select-label">⑃ branch</span>
      <select
        aria-label="Branch"
        value={selected}
        onChange={(e) =>
          onSelect(e.target.value === ALL_VALUE ? null : e.target.value)
        }
      >
        <option value={ALL_VALUE}>All</option>
        {branches.map((branch) => (
          <option key={branch} value={branch}>
            {branch}
          </option>
        ))}
      </select>
    </label>
  );
}

export default BranchFilter;
