import { useMemo, useState } from "react";
import TopBar from "./components/TopBar";
import Board from "./components/Board";
import CardDetailDrawer from "./components/CardDetailDrawer";
import PartyOverlay from "./components/PartyOverlay";
import { useBoard } from "./board/useBoard";
import { useSessions } from "./board/useSessions";
import { buildParty } from "./board/party";

function App() {
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
  } = useBoard();
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
      />
      {partyOpen && (
        <PartyOverlay party={party} onClose={() => setPartyOpen(false)} />
      )}
    </div>
  );
}

export default App;
