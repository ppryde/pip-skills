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
 */
import { useEffect, useRef, useState } from "react";
import { getRepos } from "../api/client";
import type { RepoEntry } from "../api/types";

export interface UseReposResult {
  repos: RepoEntry[];
}

export function useRepos(): UseReposResult {
  const [repos, setRepos] = useState<RepoEntry[]>([]);
  const isMountedRef = useRef(true);

  useEffect(() => {
    isMountedRef.current = true;

    void (async () => {
      try {
        const res = await getRepos();
        if (isMountedRef.current) {
          setRepos(res.repos);
        }
      } catch {
        // Silently swallow — leave existing state (empty on first failure).
      }
    })();

    return () => {
      isMountedRef.current = false;
    };
  }, []);

  return { repos };
}
