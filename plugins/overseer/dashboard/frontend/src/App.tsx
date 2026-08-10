import { useEffect, useMemo, useState } from "react";
import TopBar from "./components/TopBar";
import Board from "./components/Board";
import FilterBar from "./components/FilterBar";
import CardDetailDrawer from "./components/CardDetailDrawer";
import PartyOverlay from "./components/PartyOverlay";
import UnbegunHolding from "./components/UnbegunHolding";
import ClearDialog from "./components/ClearDialog";
import { useBoard } from "./board/useBoard";
import { useSessions } from "./board/useSessions";
import { useRepos } from "./board/useRepos";
import { useCardFilter } from "./board/useCardFilter";
import { buildParty } from "./board/party";
import { distinctBranches } from "./board/branches";
import { DEFAULT_FILTER, distinctLabels, visibleCardIds } from "./board/cardFilter";

/** localStorage key for the repo selector's persisted choice (WF-030). */
const ACTIVE_ROOT_KEY = "overseer.activeRoot";

function readStoredRoot(): string | null {
  try {
    return localStorage.getItem(ACTIVE_ROOT_KEY);
  } catch {
    // Storage disabled/unavailable (private browsing, etc.) — no persisted
    // choice, fall back to the launch-root default.
    return null;
  }
}

/** Order-insensitive equality for the filter's two label arrays — used only
 * to decide whether `filter` still equals `DEFAULT_FILTER` (gates the
 * FilterBar's Clear button). */
function sameLabelSet(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  const sorted = [...b].sort();
  return [...a].sort().every((label, i) => label === sorted[i]);
}

function writeStoredRoot(root: string): void {
  try {
    localStorage.setItem(ACTIVE_ROOT_KEY, root);
  } catch {
    // Best-effort only — a failed write just means the choice won't survive
    // a reload; the selector itself still works for this session.
  }
}

function App() {
  const { repos, reload: reloadRepos } = useRepos();
  // Seeded synchronously from localStorage so the very first board fetch
  // (useBoard's mount effect) already targets a persisted repo choice
  // rather than defaulting to the launch root and then re-fetching once
  // `/api/repos` resolves.
  const [activeRoot, setActiveRootState] = useState<string | null>(
    readStoredRoot
  );

  // Reconcile the selection against what's actually discoverable once
  // `/api/repos` resolves: a persisted root that no longer exists (repo
  // deleted/moved) falls back to the backend's own launch root rather than
  // sending every board fetch down a permanent 400.
  useEffect(() => {
    if (repos.length === 0) return;
    setActiveRootState((current) => {
      if (current && repos.some((r) => r.root === current)) return current;
      return repos.find((r) => r.current)?.root ?? current;
    });
  }, [repos]);

  function handleSelectRepo(root: string) {
    setActiveRootState(root);
    writeStoredRoot(root);
  }

  // WF-032 "unbegun repo" holding page: a repo `/api/repos` discovered
  // purely from live census sessions, never `overseer init`-ed, so it has
  // no board.db (`has_board: false`). `undefined` (repos not yet loaded, or
  // activeRoot not among them) deliberately falls through to `false` here —
  // the pre-repos-load default stays "fetch the board", matching prior
  // behaviour before this feature existed.
  const selectedRepo = repos.find((r) => r.root === activeRoot) ?? null;
  const isUnbegun = selectedRepo?.has_board === false;

  const {
    board,
    context,
    limits,
    loading,
    error,
    inFlight,
    mutate,
    refresh,
    setDragActive,
    lastRefreshedAt,
  } = useBoard(activeRoot, !isUnbegun);
  // Threaded through the SAME `activeRoot` choke point the board uses (WF-031)
  // — switching repos re-scopes the Party the same instant it re-scopes the
  // board, no separate state or client-side filtering needed. `!isUnbegun`
  // (task 10) mirrors `useBoard`'s own gate directly above: an unbegun root
  // 400s `/api/sessions` exactly like it 400s `/api/board`, so this fetch
  // (mount AND poll) must be hard-skipped for it too.
  const { sessions } = useSessions(activeRoot, !isUnbegun);
  // F3/WF-061: the card filter bar's state (search/labels/priority/
  // complexity) — App-owned like every other cross-cutting UI concern here
  // (party/branch/clear), persisted via localStorage inside the hook
  // itself. `useCardFilter()` returns a fresh object literal every render,
  // so destructure the pieces used below rather than depending on the
  // whole-object reference.
  const { filter, setQuery, setPriority, setComplexity, clear, cycleLabel } =
    useCardFilter();
  const [showArchive, setShowArchive] = useState(false);
  const [openCardId, setOpenCardId] = useState<string | null>(null);
  // HANDOFF §State Management assigns this App-level, alongside the
  // existing openCardId precedent — PartyOverlay renders as a sibling of
  // TopBar/main below, exactly like CardDetailDrawer, never as TopBar-local
  // state (Decisions).
  const [partyOpen, setPartyOpen] = useState(false);
  // WF-031 branch filter: session-local only (no localStorage, unlike the
  // repo selector) — `null` means "All", clearing every dim/spotlight.
  const [activeBranch, setActiveBranch] = useState<string | null>(null);
  // Task 7: App-owned ClearDialog open-state + post-clear success toast —
  // same App-level precedent as `partyOpen`/`openCardId` above (Decisions:
  // this state never lives on TopBar itself).
  const [clearOpen, setClearOpen] = useState(false);
  const [clearToast, setClearToast] = useState<string | null>(null);
  // WF-085b: mobile-only "Controls ▾" collapse state, lifted here from
  // TopBar so ONE toggle drives BOTH TopBar's own secondary-controls group
  // AND the separate <FilterBar/> below (previously TopBar-local state only
  // reached its own group, leaving FilterBar always visible on mobile —
  // see the mobile-v2 brief). Collapsed by default; desktop (>720px) always
  // shows both groups regardless of this flag (styles.css confines the
  // `[hidden]` override to the ≤720px media query, same pattern as the
  // pre-existing `#topbar-controls-group`).
  const [controlsOpen, setControlsOpen] = useState(false);

  // `board.project` is a loose/`unknown` shape per the frozen contract (see
  // api/types.ts) — the backend currently sends the repo root name as a
  // plain string. Fall back gracefully if that ever changes.
  const projectName =
    typeof board?.project === "string" ? board.project : "overseer";

  // Single shared join, computed once and handed to every consumer (TopBar's
  // questing pill, PartyColumn, PartyOverlay) — see Decisions: "consumers
  // render, never join".
  //
  // WF-045: forced empty for an unbegun repo. `useSessions` is hard-gated
  // off for it (see the `!isUnbegun` comment above `useSessions` below), but
  // that only SKIPS the next fetch — it doesn't clear whatever `sessions`
  // was left over from the PREVIOUSLY selected (begun) repo. Without this
  // guard, switching from a begun repo straight to an unbegun one (no
  // remount in between) left `party` built from that stale, previous-repo
  // session list, which the fleet pill's `onOpenParty` below would then
  // hand to `<PartyOverlay/>` as if it belonged to the current repo.
  const party = useMemo(
    () => (isUnbegun ? [] : buildParty(sessions, board?.cards ?? [])),
    [isUnbegun, sessions, board?.cards]
  );

  // Distinct-branch union across cards + sessions (WF-031) — feeds the
  // topbar's BranchFilter <select> options. Recomputed alongside `party`
  // whenever either source changes.
  const branches = useMemo(
    () => distinctBranches(board?.cards ?? [], sessions),
    [board?.cards, sessions]
  );

  // WF-042: the fleet's global default threshold — read once here and
  // threaded down to the TopBar's fleet-health line, Board's PartyColumn,
  // and PartyOverlay's hero cards, so every near-threshold cue agrees on
  // the exact same value `context` carries.
  const threshold = context?.threshold ?? null;

  // F3/WF-061: filter bar wiring. `allCards` is the single source both the
  // labels list and the visible-id set derive from — same "compute once,
  // hand to every consumer" precedent as `party`/`branches` above.
  const allCards = board?.cards ?? [];
  const labels = useMemo(() => distinctLabels(allCards), [allCards]);
  const visibleIds = useMemo(
    () => visibleCardIds(allCards, filter),
    [allCards, filter]
  );
  // Deep-equal against DEFAULT_FILTER (field-by-field; the two label arrays
  // compared order-insensitively) — only gates the FilterBar's Clear button,
  // so this only needs to be right, not fast.
  const isDefaultFilter =
    filter.query === DEFAULT_FILTER.query &&
    filter.priority === DEFAULT_FILTER.priority &&
    filter.complexity === DEFAULT_FILTER.complexity &&
    sameLabelSet(filter.includeLabels, DEFAULT_FILTER.includeLabels) &&
    sameLabelSet(filter.excludeLabels, DEFAULT_FILTER.excludeLabels);

  return (
    <div className="app-shell">
      <TopBar
        projectName={projectName}
        context={context}
        limits={limits}
        quarantinedCount={board?.quarantined.length ?? 0}
        showArchive={showArchive}
        onToggleArchive={() => setShowArchive((v) => !v)}
        onRefresh={() => void refresh()}
        refreshing={loading}
        mutate={mutate}
        inFlight={inFlight}
        cards={board?.cards ?? []}
        labelColors={board?.label_colors}
        party={party}
        lastRefreshedAt={lastRefreshedAt}
        // WF-045: an unbegun repo has nothing real to show in the Party
        // overlay (see the `party` guard above) — refuse to open it at all
        // rather than popping an empty/confusing sheet on click.
        onOpenParty={() => {
          if (!isUnbegun) setPartyOpen(true);
        }}
        repos={repos}
        activeRoot={activeRoot}
        onSelectRepo={handleSelectRepo}
        branches={branches}
        activeBranch={activeBranch}
        onSelectBranch={setActiveBranch}
        // Task 10: an unbegun repo never populates `party` (sessions are
        // hard-gated off above), so source the questing pill from the SAME
        // `live_sessions` count `<UnbegunHolding/>` already shows below —
        // otherwise the pill would contradict the holding page with a false
        // "0 questing".
        questingCountOverride={
          isUnbegun ? (selectedRepo?.live_sessions ?? 0) : undefined
        }
        // Task 7: only offer the destructive clear action once a repo is
        // actually selected — `undefined` (rather than a no-op closure)
        // means TopBar renders no Clear control at all until then.
        onClear={selectedRepo ? () => setClearOpen(true) : undefined}
        // WF-085b: App-owned collapse state (see comment above) — TopBar
        // still renders the "Controls ▾" button/group, it just no longer
        // owns whether they're open.
        controlsOpen={controlsOpen}
        onToggleControls={() => setControlsOpen((open) => !open)}
      />
      {/* F3/WF-061: only shown once a real board exists — an unbegun repo
          (holding page) or a still-loading/errored board has nothing for it
          to filter, so it renders exactly alongside <Board/> below. `board`
          alone isn't enough: useBoard() never clears its last-good `board`
          state when `enabled` flips false (WF-032), so a stale board can
          outlive a switch to an unbegun repo — the same `!isUnbegun` guard
          gating <Board/> in `.board-region` below must gate this too. */}
      {!isUnbegun && board && (
        <FilterBar
          filter={filter}
          labels={labels}
          visibleCount={visibleIds.size}
          totalCount={allCards.length}
          isDefault={isDefaultFilter}
          onQuery={setQuery}
          onCycleLabel={cycleLabel}
          onPriority={setPriority}
          onComplexity={setComplexity}
          onClear={clear}
          colorRegistry={board.label_colors}
          // WF-085b: folds FilterBar under the SAME "Controls ▾" toggle as
          // TopBar's own secondary-controls group on mobile — see the
          // `controlsOpen` state comment in App.tsx above.
          controlsOpen={controlsOpen}
        />
      )}
      <main className="board-region">
        {isUnbegun && selectedRepo ? (
          <UnbegunHolding
            repo={selectedRepo}
            liveSessions={selectedRepo.live_sessions}
          />
        ) : (
          <>
            {loading && !board && (
              <p className="board-placeholder">Loading board…</p>
            )}
            {error && <p className="board-error">{error}</p>}
            {board && (
              <Board
                board={board}
                showArchive={showArchive}
                mutate={mutate}
                inFlight={inFlight}
                onOpenCard={setOpenCardId}
                setDragActive={setDragActive}
                party={party}
                activeBranch={activeBranch}
                threshold={threshold}
                visibleIds={visibleIds}
              />
            )}
          </>
        )}
      </main>
      <CardDetailDrawer
        cardId={openCardId}
        onClose={() => setOpenCardId(null)}
        mutate={mutate}
        inFlight={inFlight}
        allCardIds={board?.cards.map((c) => c.id) ?? []}
        cardTitles={Object.fromEntries((board?.cards ?? []).map((c) => [c.id, c.title]))}
        party={party}
        colorRegistry={board?.label_colors}
      />
      {partyOpen && (
        <PartyOverlay
          party={party}
          onClose={() => setPartyOpen(false)}
          activeBranch={activeBranch}
          threshold={threshold}
        />
      )}
      {clearOpen && selectedRepo && (
        <ClearDialog
          repoLabel={selectedRepo.label}
          repoRoot={selectedRepo.root}
          cardCount={board?.cards.length ?? 0}
          onClose={() => setClearOpen(false)}
          onCleared={(res) => {
            setClearToast(
              res.noop
                ? `Nothing to clear for ${res.label}.`
                : `Cleared ${res.label}. Recovery snapshot: ${
                    res.backup_path ?? "(none)"
                  } — restore with \`overseer restore\`.`
            );
            // Task 7: a clear can change has_board/live_sessions (repos) and
            // always changes the board's own cards/sprints — refresh both so
            // the dashboard reflects reality rather than a stale pre-clear
            // snapshot.
            void reloadRepos();
            void refresh();
          }}
        />
      )}
      {clearToast && (
        <div className="board-toast board-toast--success" role="status">
          {clearToast}
          <button
            type="button"
            className="board-toast__dismiss"
            onClick={() => setClearToast(null)}
          >
            dismiss
          </button>
        </div>
      )}
    </div>
  );
}

export default App;
