import { useEffect, useMemo, useState } from "react";
import TopBar from "./components/TopBar";
import Board from "./components/Board";
import CardDetailDrawer from "./components/CardDetailDrawer";
import PartyOverlay from "./components/PartyOverlay";
import { useBoard } from "./board/useBoard";
import { useSessions } from "./board/useSessions";
import { useRepos } from "./board/useRepos";
import { buildParty } from "./board/party";

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
  } = useBoard(activeRoot);
  const { sessions } = useSessions();
  const [showArchive, setShowArchive] = useState(false);
  const [openCardId, setOpenCardId] = useState<string | null>(null);
  // HANDOFF §State Management assigns this App-level, alongside the
  // existing openCardId precedent — PartyOverlay renders as a sibling of
  // TopBar/main below, exactly like CardDetailDrawer, never as TopBar-local
  // state (Decisions).
  const [partyOpen, setPartyOpen] = useState(false);

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
      />
      <main className="board-region">
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
          />
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
        <PartyOverlay party={party} onClose={() => setPartyOpen(false)} />
      )}
    </div>
  );
}

export default App;
