/**
 * Repo discovery for the repo selector (WF-030). Fetches `/api/repos` once
 * on mount — unlike `useSessions`/`useBoard` there's no polling: the set of
 * discoverable boards changes rarely (a new repo starts using overseer),
 * and every board mutation already re-fetches the board itself, so a stale
 * repo list for the lifetime of a session is an acceptable trade — a
 * refresh of the page picks up any new board.
 *
 * Mirrors `useSessions`'s shape: swallow a failed fetch silently (leaving
 * the last good list — `[]` on the very first failure), so a `repos`
 * hiccup never surfaces as a visible board error.
 *
 * `reload()` (task 7) is the one imperative exception to the "fetch once"
 * rule above: a destructive clear can change `has_board`/`live_sessions`
 * for the cleared repo, so the caller (App.tsx, after `ClearDialog`'s
 * `onCleared`) needs a way to re-fetch on demand rather than waiting for a
 * full page reload. Same fetch body, same silent-swallow-on-error
 * behaviour as the mount effect — deliberately not exposed as a
 * loading/error pair since nothing here has ever surfaced one.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { getRepos } from "../api/client";
import type { RepoEntry } from "../api/types";

export interface UseReposResult {
  repos: RepoEntry[];
  reload: () => Promise<void>;
}

export function useRepos(): UseReposResult {
  const [repos, setRepos] = useState<RepoEntry[]>([]);
  const isMountedRef = useRef(true);

  const load = useCallback(async () => {
    try {
      const res = await getRepos();
      if (isMountedRef.current) {
        setRepos(res.repos);
      }
    } catch {
      // Silently swallow — leave existing state (empty on first failure).
    }
  }, []);

  useEffect(() => {
    isMountedRef.current = true;
    void load();

    return () => {
      isMountedRef.current = false;
    };
  }, [load]);

  return { repos, reload: load };
}
