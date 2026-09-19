import type { AccountEntry } from "../api/types";
import { planLabel } from "../board/chronicle/plan";
// WF-097 follow-up precedent (see RepoSelector/BranchFilter): the eyebrow
// label and the `<select>` itself route through the design-library
// primitives.
import { Label, Select } from "../ui";

const ALL_VALUE = "";

export interface AccountSelectorProps {
  accounts: AccountEntry[];
  activeAccount: string | null;
  onSelect: (account: string | null) => void;
}

/** An account's `<option>` label: its plan (tidied via `planLabel`) beside
 * its short uuid when a live login names one, else the short uuid alone —
 * `<option>` can't host markup, so both fold into one text run, mirroring
 * `RepoSelector`'s `optionLabel` for an unbegun repo's agent-count hint. */
function optionLabel(a: AccountEntry): string {
  const plan = planLabel(a.plan);
  return plan ? `${plan} · ${a.short_uuid}` : a.short_uuid;
}

/**
 * Account switcher (WF-116) — a `<select>` styled as a topbar chip,
 * mirroring `RepoSelector`/`BranchFilter`'s exact shape/conventions.
 *
 * Renders nothing with fewer than two accounts: a single-account machine
 * has nothing to switch between, and there is always an implicit "every
 * account" state even before this control exists — one real choice plus
 * "All" is still nothing to choose. Always exposes an "All accounts" option
 * that clears the filter (`null`).
 */
function AccountSelector({ accounts, activeAccount, onSelect }: AccountSelectorProps) {
  if (accounts.length < 2) return null;

  const selected =
    activeAccount && accounts.some((a) => a.account_uuid === activeAccount)
      ? activeAccount
      : ALL_VALUE;

  return (
    <label className="topbar__account-select">
      <Label className="topbar__account-select-label">account</Label>
      <Select
        aria-label="Account"
        value={selected}
        onChange={(e) =>
          onSelect(e.target.value === ALL_VALUE ? null : e.target.value)
        }
      >
        <option value={ALL_VALUE}>All accounts</option>
        {accounts.map((a) => (
          <option key={a.account_uuid} value={a.account_uuid}>
            {optionLabel(a)}
          </option>
        ))}
      </Select>
    </label>
  );
}

export default AccountSelector;
