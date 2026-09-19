/**
 * Account discovery for the account selector (WF-116). Mirrors `useRepos`
 * exactly: one fetch on mount, no polling — the set of accounts a machine
 * knows about changes rarely (a login, or a new chronicle history), and a
 * stale list for the lifetime of a session is an acceptable trade.
 *
 * Swallows a failed fetch silently (leaving the last good list — `[]` on
 * the very first failure), same as `useRepos`, so an `/api/accounts`
 * hiccup never surfaces as a visible board error.
 */
import { useEffect, useRef, useState } from "react";
import { getAccounts } from "../api/client";
import type { AccountEntry } from "../api/types";

export interface UseAccountsResult {
  accounts: AccountEntry[];
}

export function useAccounts(): UseAccountsResult {
  const [accounts, setAccounts] = useState<AccountEntry[]>([]);
  const isMountedRef = useRef(true);

  useEffect(() => {
    isMountedRef.current = true;
    void (async () => {
      try {
        const res = await getAccounts();
        if (isMountedRef.current) setAccounts(res.accounts);
      } catch {
        // Silently swallow — leave existing state (empty on first failure).
      }
    })();

    return () => {
      isMountedRef.current = false;
    };
  }, []);

  return { accounts };
}
