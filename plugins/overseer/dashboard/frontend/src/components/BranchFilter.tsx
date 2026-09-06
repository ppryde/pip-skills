// WF-097 follow-up: the eyebrow label and the `<select>` itself now route
// through the design-library primitives (`src/ui/`) — same treatment as
// RepoSelector.tsx, see its own call site comment for the rationale.
import { Label, Select } from "../ui";

const ALL_VALUE = "";

export interface BranchFilterProps {
  branches: string[];
  activeBranch: string | null;
  onSelect: (branch: string | null) => void;
  /** Stay rendered (with just "All") while `branches` is empty. For a page
   * whose branch list arrives with its data — the Chronicle — so the
   * control does not blink out and back in on every fetch. The board keeps
   * the default: no branch-carrying cards or sessions, no control. */
  keepWhenEmpty?: boolean;
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
function BranchFilter({ branches, activeBranch, onSelect, keepWhenEmpty = false }: BranchFilterProps) {
  if (branches.length === 0 && !keepWhenEmpty) return null;

  const selected =
    activeBranch && branches.includes(activeBranch) ? activeBranch : ALL_VALUE;

  return (
    <label className="topbar__branch-select">
      <Label className="topbar__branch-select-label">⑃ branch</Label>
      <Select
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
      </Select>
    </label>
  );
}

export default BranchFilter;
