import { park, unpark, move } from "../api/client";
import type { Status } from "../api/types";
import type { UseBoardResult } from "../board/useBoard";

export interface StatusMenuProps {
  cardId: string;
  status: Status;
  mutate: UseBoardResult["mutate"];
  inFlight: boolean;
  /** Called after a mutation settles — the drawer wires this to its
   * counter-guarded `getCard` refetch (see wf005-c6-brief.md). Not called
   * when block is aborted for lack of a reason (no mutation happened). */
  onMutated?: () => void;
}

/**
 * park/unpark, done, abandon, block-with-reason/unblock. Every mutating
 * action routes through `useBoard().mutate` — this component never calls the
 * api client + setState itself (see wf005-context.md "Single mutation
 * entrypoint"). Mirrors the `/move` dispatch table exactly: park/unpark use
 * their own endpoints; done/abandon/block/unblock go through `move`.
 *
 * Block REQUIRES a non-empty reason (prompted via `window.prompt`) — an
 * empty or cancelled prompt sends NO call at all (`mutate` is never invoked).
 */
function StatusMenu({
  cardId,
  status,
  mutate,
  inFlight,
  onMutated,
}: StatusMenuProps) {
  async function handlePark() {
    await mutate(() => park(cardId));
    onMutated?.();
  }

  async function handleUnpark() {
    await mutate(() => unpark(cardId));
    onMutated?.();
  }

  async function handleDone() {
    await mutate(() => move(cardId, { status: "done" }));
    onMutated?.();
  }

  async function handleAbandon() {
    await mutate(() => move(cardId, { status: "abandoned" }));
    onMutated?.();
  }

  async function handleBlock() {
    const raw = window.prompt("Reason for blocking:");
    const reason = raw?.trim();
    if (!reason) return; // empty or cancelled — send NOTHING.
    await mutate(() => move(cardId, { status: "blocked", reason }));
    onMutated?.();
  }

  async function handleUnblock() {
    await mutate(() => move(cardId, { status: "planned" }));
    onMutated?.();
  }

  return (
    <div className="status-menu">
      {status === "parked" ? (
        <button type="button" onClick={() => void handleUnpark()} disabled={inFlight}>
          Unpark
        </button>
      ) : (
        <button type="button" onClick={() => void handlePark()} disabled={inFlight}>
          Park
        </button>
      )}

      {status === "blocked" ? (
        <button type="button" onClick={() => void handleUnblock()} disabled={inFlight}>
          Unblock
        </button>
      ) : (
        <button type="button" onClick={() => void handleBlock()} disabled={inFlight}>
          Block…
        </button>
      )}

      <button type="button" onClick={() => void handleDone()} disabled={inFlight}>
        Done
      </button>
      <button type="button" onClick={() => void handleAbandon()} disabled={inFlight}>
        Abandon
      </button>
    </div>
  );
}

export default StatusMenu;
