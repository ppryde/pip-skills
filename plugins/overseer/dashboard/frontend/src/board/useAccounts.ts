/**
 * Account discovery for the account selector (WF-116). Mirrors `useRepos`
 * exactly: one fetch on mount, no polling — the set of accounts a machine
 * knows about changes rarely (a login, or a new chronicle history), and a
 * stale list for the lifetime of a session is an acceptable trade.
 *
 * Swallows a failed fetch silently (leaving the last good list — `[]` on
 * the very first failure), same as `useRepos`, so an `/api/accounts`
 * hiccup never surfaces as a visible board error.
 *
 * `loaded` is the one thing `useRepos` doesn't need and this does: App.tsx's
 * reconcile effect must clear a stale persisted `activeAccount` once the
 * REAL list turns out not to contain it — including the genuinely-empty
 * case (no chronicle history, no oauth logins at all). `accounts.length ===
 * 0` can't distinguish "haven't heard back yet" from "heard back, there are
 * none" — collapsing the two left a stale persisted uuid filtering every
 * session/chronicle read forever, with `AccountSelector` itself hidden
 * (fewer than two accounts) and so no way to clear it from the UI. `loaded`
 * flips true only on a SUCCESSFUL fetch (never on a failure — a hiccup must
 * not be read as "we now know there are no accounts") and never flips back,
 * same one-way shape as `useRepos`'s list itself.
 */
import { useEffect, useRef, useState } from "react";
import { getAccounts } from "../api/client";
import type { AccountEntry } from "../api/types";

export interface UseAccountsResult {
  accounts: AccountEntry[];
  loaded: boolean;
}

export function useAccounts(): UseAccountsResult {
  const [accounts, setAccounts] = useState<AccountEntry[]>([]);
  const [loaded, setLoaded] = useState(false);
  const isMountedRef = useRef(true);

  useEffect(() => {
    isMountedRef.current = true;
    void (async () => {
      try {
        const res = await getAccounts();
        if (isMountedRef.current) {
          setAccounts(res.accounts);
          setLoaded(true);
        }
      } catch {
        // Silently swallow — leave existing state (empty on first failure)
        // and `loaded` unset, per the doc comment above.
      }
    })();

    return () => {
      isMountedRef.current = false;
    };
  }, []);

  return { accounts, loaded };
}
