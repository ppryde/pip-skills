/**
 * Board state container.
 *
 * `mutate()` is the SINGLE entrypoint every mutation (drag in C4, drawer
 * controls in C5/C6) must route through — see wf005-context.md "Global
 * constraints": no control may call the api client + setState directly.
 * It owns a monotonic request counter + in-flight lock so that out-of-order
 * responses (a slow earlier request resolving after a faster later one) are
 * dropped rather than clobbering fresher state.
 *
 * This chunk (C3) performs no mutations itself — it only builds this
 * scaffold for later chunks to call.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { getBoard, setActiveRoot } from "../api/client";
import type { Board, BoardResponse, Context, Limits } from "../api/types";
import { MAX_RETRIES, backoffSeconds, classifyFailure, isRetryable } from "./retry";
import type { FailureKind } from "./retry";
import { useVisibleInterval } from "./useDocumentVisible";

/** Background poll cadence — paused while a drag or mutation is in flight. */
const POLL_INTERVAL_MS = 5000;

/** Everything the Waylaid banner needs to say what is actually happening,
 * rather than the old single "there was an error" string that could only be
 * narrated as "we'll keep trying forever". */
export interface FetchFailure {
  /** The raw failure, verbatim — still shown, never paraphrased away. */
  message: string;
  kind: FailureKind;
  /** Automatic retries spent so far; 0 while the first failure is fresh. */
  retries: number;
  /** Seconds until the next automatic attempt, or null when there will not
   * be one — the budget is spent, or the failure was never retryable. */
  retryInSeconds: number | null;
}

export interface UseBoardResult {
  board: Board | null;
  context: Context | null;
  limits: Limits;
  loading: boolean;
  error: string | null;
  /** The same failure with its classification and retry budget attached.
   * `error` is kept alongside it (same message) because several consumers
   * only ever needed the string. */
  failure: FetchFailure | null;
  inFlight: boolean;
  refresh: () => Promise<void>;
  /** Abandon an in-flight load and stop the automatic retries. Leaves the
   * last good board on screen; nothing resumes until `refresh()` is called
   * or the selected repo changes. */
  cancel: () => void;
  /** `opts.rethrow` (Task 10 fix-up): DEFAULT false — swallows a rejection
   *  from `fn()` into `error` (the global banner) exactly as before, never
   *  rejects the returned promise. `rethrow: true` is opt-in for callers
   *  that show their OWN inline error (e.g. NewCardDialog): on rejection it
   *  skips `setError` (avoids double-surfacing the same failure in both an
   *  inline message and the global banner) and rethrows so the caller's own
   *  `catch` fires. The in-flight lock still clears unconditionally in
   *  `finally` either way, and the success path (`applyResponse`) is
   *  unchanged by this option. */
  mutate: (
    fn: () => Promise<BoardResponse>,
    opts?: { rethrow?: boolean }
  ) => Promise<void>;
  /** Board wires this from dnd-kit's onDragStart/onDragEnd/onDragCancel so
   *  the poll loop pauses for the duration of a drag. Ref-backed (not
   *  state) so the setInterval tick always reads the latest value without
   *  needing to be re-created every render. */
  setDragActive: (active: boolean) => void;
  /** WF-029: when the last successful `applyResponse` landed (manual load,
   *  refresh, silent poll, or mutate — any of them count as "fresh data").
   *  Feeds TopBar's subtitle timestamp; null until the first load resolves. */
  lastRefreshedAt: Date | null;
}

/**
 * `root` (WF-030 repo selector) is the currently-selected repo's root path,
 * or `null` to use the dashboard's own launch root (the pre-selector
 * default). Passing it here — rather than threading it through every
 * mutate() call site across the tree — keeps the repo selection a single
 * App-level concern: `setActiveRoot` is called synchronously at the START
 * of the SAME effect that fires the mount/root-change fetch, so by the time
 * that fetch's `getBoard()` call builds its URL, `api/client`'s module-level
 * root is already correct — no cross-effect race.
 *
 * `enabled` (WF-032 "unbegun repo" holding page) gates BOTH the mount/
 * root-change fetch and the background poll — App.tsx passes `false` when
 * the selected repo is `has_board: false` (App renders `<UnbegunHolding/>`
 * instead of `<Board/>` for exactly that case). A `has_board: false` root
 * 400s the backend's `/api/board`, so this must be a hard gate on the
 * fetch itself, not just on what gets rendered.
 */
export function useBoard(
  root: string | null = null,
  enabled: boolean = true
): UseBoardResult {
  const [board, setBoard] = useState<Board | null>(null);
  const [context, setContext] = useState<Context | null>(null);
  const [limits, setLimits] = useState<Limits>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [inFlight, setInFlight] = useState(false);
  const [lastRefreshedAt, setLastRefreshedAt] = useState<Date | null>(null);
  const [failure, setFailure] = useState<FetchFailure | null>(null);

  // Monotonic counter: each request gets an issued id; a response is only
  // applied if its id is still the latest issued when it resolves.
  const requestIdRef = useRef(0);

  // Mirrors of `inFlight` / drag state for the setInterval poll tick, which
  // closes over refs (not state) so it always sees the current value without
  // needing the effect that owns the interval to re-run every render.
  const inFlightRef = useRef(false);
  const dragActiveRef = useRef(false);
  // Mirrors `enabled` for the poll tick, same rationale as the other refs
  // above — the interval effect below only depends on `load` (stable), so a
  // toggle of `enabled` alone must still be visible to an already-running
  // interval without tearing it down and recreating it.
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;
  // The root the previous effect run served — see the root-change effect.
  const prevRootRef = useRef<string | null>(null);
  // Poll gate for MANUAL loads (mount fetch / refresh). A poll tick fired
  // while a manual load is in flight would bump the shared epoch and mark
  // the manual response stale — polling must never interfere with a manual
  // request the user is watching, so ticks skip while this is set.
  const loadingRef = useRef(false);

  // --- retry machinery ------------------------------------------------------
  // Aborts the manual load in flight, so Cancel can actually stop a request
  // that is hanging rather than merely hiding the banner over it.
  const abortRef = useRef<AbortController | null>(null);
  // The pending backoff timer, so Cancel (and a repo switch) can cut a
  // scheduled retry that has not fired yet.
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Automatic retries spent on the CURRENT run of failures; reset by any
  // success and by any manual `refresh()`, so pressing "Send a rider"
  // genuinely starts the budget over rather than inheriting an exhausted one.
  const retriesRef = useRef(0);
  // Mirrors `failure` for the poll tick. A silent poll against a server that
  // is down (or a token that is refused) is exactly the doomed traffic this
  // work exists to stop, so ticks skip while a failure stands.
  const failureRef = useRef<FetchFailure | null>(null);
  failureRef.current = failure;
  // Set by Cancel. Unlike `failure` this survives dismissing the banner:
  // nothing automatic resumes until the person asks (`refresh`) or the
  // selected repo changes.
  const suspendedRef = useRef(false);
  // `load` calls itself through this — a `useCallback` cannot name itself,
  // and threading the schedule through an effect would decouple the retry
  // from the failure that earned it.
  const loadRef = useRef<((opts?: { silent?: boolean }) => Promise<void>) | null>(null);

  const clearRetryTimer = useCallback(() => {
    if (retryTimerRef.current !== null) {
      clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }
  }, []);

  const setDragActive = useCallback((active: boolean) => {
    dragActiveRef.current = active;
  }, []);

  const applyResponse = useCallback((res: BoardResponse) => {
    setBoard(res.board);
    setContext(res.context);
    setLimits(res.limits);
    setLastRefreshedAt(new Date());
    // Anything that lands successfully ends the failure run — including a
    // silent poll, so a server that comes back on its own clears the banner
    // without the person having to press anything.
    retriesRef.current = 0;
    setFailure(null);
    setError(null);
  }, []);

  // `silent` is for the background poll: it still goes through the SAME
  // epoch/staleness guard (`requestIdRef`) and `applyResponse` as a manual
  // refresh, but it must never flip `loading` (that drives the TopBar
  // "Refreshing…" button) or `error` (that renders a visible banner in
  // App.tsx) — a poll tick is invisible unless it succeeds, in which case
  // the board just quietly updates. A rejected poll leaves the last good
  // board on screen and surfaces nothing.
  const load = useCallback(
    async (opts?: { silent?: boolean }) => {
      const silent = opts?.silent ?? false;
      const id = ++requestIdRef.current;
      const controller = silent ? null : new AbortController();
      if (!silent) {
        clearRetryTimer();
        abortRef.current = controller;
        loadingRef.current = true;
        setLoading(true);
        setError(null);
      }
      try {
        const res = await getBoard(controller ? { signal: controller.signal } : undefined);
        // Only APPLYING the response is epoch-guarded — a newer
        // load/refresh/mutate wins the data race.
        if (id === requestIdRef.current) applyResponse(res);
      } catch (e) {
        // A manual load OWNS the error flag unconditionally: even if a
        // newer request bumped the epoch mid-flight (mutation racing a
        // refresh), the user asked for this refresh and its failure must
        // surface. Silent polls swallow instead — no error state, no
        // console noise; the last good board stays put.
        if (!silent) {
          const kind = classifyFailure(e);
          // Cancel is not a failure. It leaves the last good board on
          // screen and says nothing — the person already knows, they did it.
          if (kind === "aborted") {
            setError(null);
            setFailure(null);
          } else {
            const message = e instanceof Error ? e.message : String(e);
            setError(message);
            // Retry only what a retry could plausibly fix, and only while
            // the budget lasts. A refused token (`auth`) or a rejected
            // request (`rejected`) is settled on the first answer: riding
            // out again can only be refused identically, so those land here
            // with `retryInSeconds: null` and the banner says so instead of
            // counting down to nothing.
            const spent = retriesRef.current;
            if (isRetryable(kind) && spent < MAX_RETRIES) {
              const wait = backoffSeconds(spent + 1);
              retriesRef.current = spent + 1;
              setFailure({ message, kind, retries: spent + 1, retryInSeconds: wait });
              retryTimerRef.current = setTimeout(() => {
                retryTimerRef.current = null;
                void loadRef.current?.();
              }, wait * 1000);
            } else {
              setFailure({ message, kind, retries: spent, retryInSeconds: null });
            }
          }
        }
      } finally {
        // Likewise unconditional for `loading`: gating this on the epoch
        // strands loading=true (a permanently disabled "Refreshing…"
        // button) whenever anything bumps the shared counter mid-flight —
        // same rationale as mutate()'s unconditional inFlight clear below.
        if (!silent) {
          if (abortRef.current === controller) abortRef.current = null;
          loadingRef.current = false;
          setLoading(false);
        }
      }
    },
    [applyResponse, clearRetryTimer]
  );
  loadRef.current = load;

  /** Cancel: stop the request in flight AND the schedule behind it. The
   * banner goes, the last good board stays, and nothing automatic resumes
   * until `refresh()` or a repo change — otherwise the 5s poll would simply
   * take over the hammering the person just asked to stop. */
  const cancel = useCallback(() => {
    clearRetryTimer();
    abortRef.current?.abort();
    abortRef.current = null;
    suspendedRef.current = true;
    retriesRef.current = 0;
    loadingRef.current = false;
    setLoading(false);
    setError(null);
    setFailure(null);
  }, [clearRetryTimer]);

  // Re-fires on mount AND whenever the selected repo root (or `enabled`)
  // changes — setting the module-level active root FIRST (synchronously,
  // before `load()`) so this fetch (and every one after it, until the next
  // change) targets the newly-selected repo. `enabled: false` is a hard
  // skip: no `setActiveRoot`, no `load()` — an unbegun root must never
  // reach `getBoard()` (see the doc comment on `useBoard` above).
  // WF-047: a root change DROPS the board and context in hand first — they
  // are the previously-selected repo's, and until the new fetch lands a
  // consumer reading `board?.cards` must see nothing (App shows its
  // "Loading board…" line), never the old repo's cards under the new
  // header. That covers the unbegun case for free: no fetch follows, so
  // nothing replaces the emptiness. `limits` (the account's rate windows)
  // are not per repo and stay. Any response still in flight for the old
  // root is retired by bumping the epoch. `null` is "the launch root, not
  // yet named": App's reconcile turns it into that repo's explicit path once
  // `/api/repos` answers, and that is the SAME board, not a switch — so a
  // change away from `null` keeps what is loaded (no second loading flash
  // on every page open).
  useEffect(() => {
    const switched = prevRootRef.current !== null && prevRootRef.current !== root;
    prevRootRef.current = root;
    if (switched || !enabled) {
      requestIdRef.current += 1;
      setBoard(null);
      setContext(null);
      setError(null);
      // A different repo is a different question — the previous one's
      // failure, its spent retry budget and any Cancel suspension all belong
      // to a board that is no longer on screen.
      clearRetryTimer();
      abortRef.current?.abort();
      abortRef.current = null;
      retriesRef.current = 0;
      suspendedRef.current = false;
      setFailure(null);
    }
    if (!enabled) return;
    setActiveRoot(root);
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [root, enabled]);

  // A scheduled retry must not outlive the component — an unmount mid-backoff
  // would otherwise fire a load into a torn-down hook.
  useEffect(() => () => {
    clearRetryTimer();
    abortRef.current?.abort();
  }, [clearRetryTimer]);

  /** "Send a rider": a fresh start, not a continuation. Resets the retry
   * budget and lifts a Cancel suspension, so the automatic machinery is
   * always something the person can hand-crank back into life. */
  const refresh = useCallback(async () => {
    clearRetryTimer();
    retriesRef.current = 0;
    suspendedRef.current = false;
    await load();
  }, [load, clearRetryTimer]);

  const mutate = useCallback(
    async (fn: () => Promise<BoardResponse>, opts?: { rethrow?: boolean }) => {
      const rethrow = opts?.rethrow ?? false;
      const id = ++requestIdRef.current;
      inFlightRef.current = true;
      setInFlight(true);
      try {
        const res = await fn();
        // Apply only if still the latest issued request (drop stale/out-of-order).
        if (id === requestIdRef.current) {
          applyResponse(res);
          setError(null);
        }
      } catch (e) {
        if (rethrow) {
          // Caller owns error display (e.g. an inline dialog message) —
          // don't ALSO set the global banner for the same failure.
          throw e;
        }
        if (id === requestIdRef.current) {
          setError(e instanceof Error ? e.message : String(e));
        }
      } finally {
        // Clear the lock UNCONDITIONALLY. `requestIdRef` is shared with
        // load()/refresh(), which bump it without touching `inFlight`; gating
        // the clear on `id === requestIdRef.current` would strand the lock
        // (and disable drags forever) whenever a refresh races an in-flight
        // mutation. Staleness only governs whether we APPLY the response.
        inFlightRef.current = false;
        setInFlight(false);
      }
    },
    [applyResponse]
  );

  // Background poll: every 5s while the tab is in the foreground, silently
  // refresh unless a mutation, a drag, or a MANUAL load is in flight (a tick
  // during a manual load would bump the shared epoch and stale-out the
  // response the user is waiting on). All gates are read from refs at tick
  // time so the interval itself never needs to be torn down/recreated when
  // they toggle. A hidden tab polls nothing and catches up once on return
  // (`useVisibleInterval` fires immediately when the page is shown).
  useVisibleInterval(
    () => {
      if (
        !enabledRef.current ||
        inFlightRef.current ||
        dragActiveRef.current ||
        loadingRef.current ||
        // A failure is already being handled on its own backoff schedule (or
        // has been declared terminal). Polling through it was the other half
        // of "retries for ages": twelve doomed silent requests a minute, on
        // top of the visible ones, none of which could surface anything.
        failureRef.current !== null ||
        // Cancel means stop. The poll must not quietly take over.
        suspendedRef.current
      )
        return;
      void load({ silent: true });
    },
    POLL_INTERVAL_MS,
    true,
    { immediate: "on-return" } // mount and root changes already load above
  );

  return {
    board,
    context,
    limits,
    loading,
    error,
    failure,
    inFlight,
    refresh,
    cancel,
    mutate,
    setDragActive,
    lastRefreshedAt,
  };
}
