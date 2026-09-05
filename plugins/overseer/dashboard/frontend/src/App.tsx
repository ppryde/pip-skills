import { useEffect, useMemo, useState } from "react";
import TopBar from "./components/TopBar";
import type { View } from "./components/TopBar";
import ChroniclePage from "./components/chronicle/ChroniclePage";
import ChronicleFilterBar from "./components/chronicle/ChronicleFilterBar";
import Waylaid from "./components/Waylaid";

/** useBoard's poll cadence, for the fetch-failure banner's countdown. */
const BOARD_RETRY_SECONDS = 5;
import type { ChronicleQuery } from "./api/types";

type ChronicleScope = NonNullable<ChronicleQuery["scope"]>;
import { useChronicle, useChronicleStatus, useChronicleSync } from "./board/chronicle/useChronicle";
import Board from "./components/Board";
import EpicAtlas from "./components/EpicAtlas";
import FilterBar from "./components/FilterBar";
import CardDetailDrawer from "./components/CardDetailDrawer";
import PartyOverlay from "./components/PartyOverlay";
import UnbegunHolding from "./components/UnbegunHolding";
import ClearDialog from "./components/ClearDialog";
import DesignLibrary from "./ui/DesignLibrary";
import { useBoard } from "./board/useBoard";
import { useSessions } from "./board/useSessions";
import { useRepos } from "./board/useRepos";
import { useCardFilter } from "./board/useCardFilter";
import { useIconKeyGlow } from "./board/useIconKeyGlow";
import { buildParty } from "./board/party";
import { distinctBranches, orderBranchesByActivity } from "./board/branches";
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
/** The page a URL hash names, or null for anything that isn't one of ours
 * (the bare URL, `#design`, a stray anchor). Chronicle is accepted here
 * even before its plugin status is known — the guard effect in App falls
 * back to the board once status says the page isn't offered. */
function viewFromHash(hash: string): View | null {
  const name = hash.replace(/^#/, "");
  return name === "board" || name === "atlas" || name === "chronicle" ? name : null;
}

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
  // Task 6: 60s post-change glow (live, frontend-only) — observes
  // `board.cards` across polls/mutations and glows any card whose
  // `cardIconKey` changed within the last 60s. `board?.cards ?? []` mirrors
  // the `allCards` fallback below.
  const glowingIds = useIconKeyGlow(board?.cards ?? []);
  // F3/WF-061: the card filter bar's state (search/labels/priority/
  // complexity) — App-owned like every other cross-cutting UI concern here
  // (party/branch/clear), persisted via localStorage inside the hook
  // itself. `useCardFilter()` returns a fresh object literal every render,
  // so destructure the pieces used below rather than depending on the
  // whole-object reference.
  const { filter, setQuery, setPriority, setComplexity, setEpicsOnly, clear, cycleLabel } =
    useCardFilter();
  // WF-0XX item 6: the Abandoned lane is opt-OUT now, not opt-in — it used
  // to default hidden (`false`) so a fresh load never showed it, but that
  // made the lane (and its nav icon) invisible unless a user discovered the
  // Controls-group checkbox first. Defaulting `true` shows it (empty →
  // faded "0" icon via the existing empty-lane treatment when there's
  // nothing abandoned) on both viewports; the checkbox still toggles it off.
  const [showArchive, setShowArchive] = useState(true);
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
  // Task 2/3: "Controls ▾" and "Filters ▾" are now two INDEPENDENT collapse
  // toggles (previously one shared `controlsOpen` drove both TopBar's own
  // secondary-controls group AND the separate <FilterBar/> below it — see
  // git history for that WF-085b arrangement). Follow-up: both now default
  // CLOSED (was: both OPEN so the board looked unchanged on load) — the
  // board opens tidier, with Filters ▾/Controls ▾ revealing each region on
  // demand. `hidden={!controlsOpen}`/`hidden={!filtersOpen}` take effect on
  // every viewport, not just ≤720px (styles.css), so either button can
  // collapse/reveal its own region anywhere.
  const [controlsOpen, setControlsOpen] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  // The current page, mirrored into the URL hash (`#atlas`, `#chronicle`;
  // the board is the bare URL) so a reload or a shared link lands on the
  // same page — the one piece of view state that survives a refresh. Same
  // no-router hash idiom as the `#design` showcase below, which keeps its
  // own hash and takes over the whole app when set. `replaceState` rather
  // than assigning `location.hash`, so clicking between coins never piles
  // up history entries; a hand-edited hash or Back/Forward still lands via
  // `hashchange`.
  const [view, setView] = useState<View>(() => viewFromHash(window.location.hash) ?? "board");
  useEffect(() => {
    if (window.location.hash === "#design") return;
    const wanted = view === "board" ? "" : `#${view}`;
    if (window.location.hash === wanted) return;
    window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}${wanted}`);
  }, [view]);
  useEffect(() => {
    function onHashChange() {
      const next = viewFromHash(window.location.hash);
      if (next !== null) setView(next);
      else if (window.location.hash === "") setView("board");
    }
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);
  // Chronicle (optional sibling plugin): one status read on mount decides
  // whether the page is offered at all. `null` = not yet known.
  const chronicleStatus = useChronicleStatus();
  const chronicleAvailable = chronicleStatus?.installed === true;
  useEffect(() => {
    // Defensive: a stale `#chronicle`-ish selection can't outlive the
    // plugin's absence — fall back to the board once status is known.
    if (view === "chronicle" && chronicleStatus !== null && !chronicleAvailable) {
      setView("board");
    }
  }, [view, chronicleStatus, chronicleAvailable]);
  // The Chronicle's filters and its Sync action are App-owned for the same
  // reason the Atlas toggles are (WF-091): the controls render in the top
  // bar / filter region while the data renders in the page, so both need
  // the same values. The top bar's own repo and branch selectors drive the
  // Chronicle's scope directly on that page — the repo selector gains an
  // "All repos" choice there (`chronicleAllRepos`, separate from
  // `activeRoot` so the board's root survives a visit), and the branch
  // selector reuses `activeBranch`, offered the branches chronicle actually
  // saw in the window rather than the board's card branches. Only the time
  // window has a control of its own (`<ChronicleFilterBar/>`). Session-
  // local, no localStorage. The fetch is gated on the view so the board
  // never pays for chronicle polling. An unbegun repo's root is refused on
  // every scoped read, so its scope is pinned to "all" regardless.
  const [chronicleDays, setChronicleDays] = useState<number | undefined>(30);
  const [chronicleAllRepos, setChronicleAllRepos] = useState(false);
  // The Chronicle's branch is its OWN state, not the board's `activeBranch`:
  // its list spans every repo, and a branch chosen there would otherwise dim
  // the board's cards on return with no visible filter to clear (the
  // board's selector shows "All" for a branch its own list lacks).
  const [chronicleBranch, setChronicleBranch] = useState<string | null>(null);
  const chronicleScope: ChronicleScope = chronicleAllRepos || isUnbegun ? "all" : "repo";
  const chronicle = useChronicle(
    activeRoot,
    { days: chronicleDays, scope: chronicleScope, branch: chronicleBranch },
    view === "chronicle"
  );
  // Chronicle is pull only (no hooks, by design) — while the page shows, the
  // dashboard is what keeps its store current: a quiet sync on open and
  // every minute after.
  const chronicleSync = useChronicleSync(chronicle.refresh, view === "chronicle");
  // Branches chronicle saw in this window. Taken from the UNFILTERED session
  // list only: once a branch filter is on, the fetched sessions all carry
  // that one branch and the list would collapse to it, leaving no way to
  // hop to another without clearing first. So the pool is refreshed while
  // no branch is chosen and held while one is (a repo or window change made
  // mid-filter shows the previous pool until the branch is cleared — the
  // "All" option is always there to do that). The active branch is always
  // listed, so the selector never shows a filter it cannot name.
  // Ordered by each branch's newest session activity, most recent first —
  // the same recency order the board's list and the repo selector use.
  const [chronicleBranchPool, setChronicleBranchPool] = useState<string[]>([]);
  useEffect(() => {
    if (chronicleBranch !== null) return;
    const activity = new Map<string, number>();
    for (const s of chronicle.sessions) {
      if (!s.git_branch) continue;
      const ts = s.last_activity_at ?? s.started_at ?? 0;
      activity.set(s.git_branch, Math.max(activity.get(s.git_branch) ?? 0, ts));
    }
    setChronicleBranchPool(orderBranchesByActivity(activity));
  }, [chronicle.sessions, chronicleBranch]);
  const chronicleBranches = useMemo(
    () =>
      chronicleBranch && !chronicleBranchPool.includes(chronicleBranch)
        ? [...chronicleBranchPool, chronicleBranch]
        : chronicleBranchPool,
    [chronicleBranchPool, chronicleBranch]
  );
  // WF-091: the Epic Atlas toolbar's toggles, lifted here from
  // EpicAtlas-local state — the controls that drive them now live in
  // TopBar's Controls group (shown only on `view === "atlas"`), so both
  // TopBar and EpicAtlas need the same App-owned values. Session-local, same
  // precedent as `view`/`activeBranch` (no localStorage persistence).
  const [showNames, setShowNames] = useState(true);
  const [hideVanquished, setHideVanquished] = useState(true);

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
    filter.epicsOnly === DEFAULT_FILTER.epicsOnly &&
    sameLabelSet(filter.includeLabels, DEFAULT_FILTER.includeLabels) &&
    sameLabelSet(filter.excludeLabels, DEFAULT_FILTER.excludeLabels);

  // v1 design library showcase (`src/ui/DesignLibrary.tsx`) — reachable at
  // the `#design` hash rather than a real route, so no router dependency is
  // needed: read the hash once at mount, then re-derive it on every
  // `hashchange` (covers both a user editing the URL bar and browser Back/
  // Forward). This is a diagnostic/reference page, not a normal app view —
  // it deliberately swaps out the ENTIRE board below rather than living
  // alongside `view` ("board" | "atlas").
  const [showDesignLibrary, setShowDesignLibrary] = useState(
    () => window.location.hash === "#design"
  );
  useEffect(() => {
    function handleHashChange() {
      setShowDesignLibrary(window.location.hash === "#design");
    }
    window.addEventListener("hashchange", handleHashChange);
    return () => window.removeEventListener("hashchange", handleHashChange);
  }, []);

  if (showDesignLibrary) {
    return <DesignLibrary />;
  }

  return (
    <div className="app-shell">
      <TopBar
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
        branches={view === "chronicle" ? chronicleBranches : branches}
        activeBranch={view === "chronicle" ? chronicleBranch : activeBranch}
        onSelectBranch={view === "chronicle" ? setChronicleBranch : setActiveBranch}
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
        // App-owned collapse state (see comment above) — TopBar still
        // renders the "Controls ▾"/"Filters ▾" buttons/groups, it just
        // doesn't own whether they're open.
        controlsOpen={controlsOpen}
        onToggleControls={() => setControlsOpen((open) => !open)}
        filtersOpen={filtersOpen}
        onToggleFilters={() => setFiltersOpen((open) => !open)}
        view={view}
        onSelectView={setView}
        showNames={showNames}
        onToggleNames={setShowNames}
        hideVanquished={hideVanquished}
        onToggleVanquished={setHideVanquished}
        chronicleAvailable={chronicleAvailable}
        onChronicleSync={() => void chronicleSync.sync()}
        chronicleSyncing={chronicleSync.syncing}
        chronicleAllRepos={{ selected: chronicleScope === "all", onSelect: setChronicleAllRepos }}
      />
      {/* The Chronicle's filters take the board FilterBar's slot (same id,
          same "Filters ▾" collapse) — exactly one of the two renders. */}
      {view === "chronicle" && (
        <ChronicleFilterBar
          days={chronicleDays}
          onDays={setChronicleDays}
          syncNote={chronicleSync.note}
          filtersOpen={filtersOpen}
        />
      )}
      {/* F3/WF-061: only shown once a real board exists — an unbegun repo
          (holding page) or a still-loading/errored board has nothing for it
          to filter, so it renders exactly alongside <Board/> below. `board`
          alone isn't enough: useBoard() never clears its last-good `board`
          state when `enabled` flips false (WF-032), so a stale board can
          outlive a switch to an unbegun repo — the same `!isUnbegun` guard
          gating <Board/> in `.board-region` below must gate this too.
          WF-086: also gated on `view === "board"` — the Atlas is an
          explicit non-goal for card filtering (chunk-6 handoff), so
          FilterBar is omitted ENTIRELY on the Atlas rather than rendered
          hidden-but-inert. */}
      {!isUnbegun && board && view === "board" && (
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
          onEpicsOnly={setEpicsOnly}
          onClear={clear}
          colorRegistry={board.label_colors}
          // Its own independent "Filters ▾" toggle now (Task 2) — see the
          // `filtersOpen` state comment in App.tsx above.
          filtersOpen={filtersOpen}
        />
      )}
      <main className="board-region">
        {/* The Chronicle is account-wide data, so unlike Board/Atlas it is
            reachable for an unbegun repo too — the page just locks its
            scope to "All repos" since a boardless root can't be named. */}
        {view === "chronicle" ? (
          <ChroniclePage
            summary={chronicle.summary}
            sessions={chronicle.sessions}
            loading={chronicle.loading}
            error={chronicle.error}
            onRetry={() => void chronicle.refresh()}
          />
        ) : isUnbegun && selectedRepo ? (
          <UnbegunHolding
            repo={selectedRepo}
            liveSessions={selectedRepo.live_sessions}
          />
        ) : (
          <>
            {loading && !board && (
              <p className="board-placeholder">Loading board…</p>
            )}
            {error && (
              <Waylaid error={error} retryEverySeconds={BOARD_RETRY_SECONDS} onRetry={() => void refresh()} />
            )}
            {board && view === "board" && (
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
                glowingIds={glowingIds}
              />
            )}
            {/* WF-086: same <main class="board-region"> the board renders
                in — a sibling page, not a re-theme, per the HANDOFF's
                framing. CardDetailDrawer below stays the ONE shared drawer
                for both views (App.tsx owns `openCardId` regardless of
                which page opened it). */}
            {board && view === "atlas" && (
              <EpicAtlas
                board={board}
                onOpenCard={setOpenCardId}
                showNames={showNames}
                hideVanquished={hideVanquished}
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
