import { useState } from "react";
import TopBar from "./components/TopBar";
import Board from "./components/Board";
import CardDetailDrawer from "./components/CardDetailDrawer";
import { useBoard } from "./board/useBoard";

function App() {
  const { board, context, limits, loading, error, inFlight, mutate, refresh } =
    useBoard();
  const [showArchive, setShowArchive] = useState(false);
  const [openCardId, setOpenCardId] = useState<string | null>(null);

  // `board.project` is a loose/`unknown` shape per the frozen contract (see
  // api/types.ts) — the backend currently sends the repo root name as a
  // plain string. Fall back gracefully if that ever changes.
  const projectName =
    typeof board?.project === "string" ? board.project : "overseer";

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
          />
        )}
      </main>
      <CardDetailDrawer
        cardId={openCardId}
        onClose={() => setOpenCardId(null)}
      />
    </div>
  );
}

export default App;
