import { useEffect, useMemo, useState } from "react";
import TopBar from "./components/TopBar";
import Board from "./components/Board";
import CardDetailDrawer from "./components/CardDetailDrawer";
import PartyOverlay from "./components/PartyOverlay";
import UnbegunHolding from "./components/UnbegunHolding";
import { useBoard } from "./board/useBoard";
import { useSessions } from "./board/useSessions";
import { useRepos } from "./board/useRepos";
import { buildParty } from "./board/party";
import { distinctBranches } from "./board/branches";

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

function writeStoredRoot(root: string): void {
  try {
    localStorage.setItem(ACTIVE_ROOT_KEY, root);
  } catch {
    // Best-effort only — a failed write just means the choice won't survive
    // a reload; the selector itself still works for this session.
  }
}

function App() {
  const { repos } = useRepos();
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
  // board, no separate state or client-side filtering needed.
  const { sessions } = useSessions(activeRoot);
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

  // `board.project` is a loose/`unknown` shape per the frozen contract (see
  // api/types.ts) — the backend currently sends the repo root name as a
  // plain string. Fall back gracefully if that ever changes.
  const projectName =
    typeof board?.project === "string" ? board.project : "overseer";

  // Single shared join, computed once and handed to every consumer (TopBar's
  // questing pill, PartyColumn, PartyOverlay) — see Decisions: "consumers
  // render, never join".
  const party = useMemo(
    () => buildParty(sessions, board?.cards ?? []),
    [sessions, board?.cards]
  );

  // Distinct-branch union across cards + sessions (WF-031) — feeds the
  // topbar's BranchFilter <select> options. Recomputed alongside `party`
  // whenever either source changes.
  const branches = useMemo(
    () => distinctBranches(board?.cards ?? [], sessions),
    [board?.cards, sessions]
  );

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
        party={party}
        lastRefreshedAt={lastRefreshedAt}
        onOpenParty={() => setPartyOpen(true)}
        repos={repos}
        activeRoot={activeRoot}
        onSelectRepo={handleSelectRepo}
        branches={branches}
        activeBranch={activeBranch}
        onSelectBranch={setActiveBranch}
      />
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
        party={party}
      />
      {partyOpen && (
        <PartyOverlay
          party={party}
          onClose={() => setPartyOpen(false)}
          activeBranch={activeBranch}
        />
      )}
    </div>
  );
}

export default App;
