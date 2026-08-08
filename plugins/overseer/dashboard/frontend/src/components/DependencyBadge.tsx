import type { BoardCard } from "../api/types";
import { PadlockIcon } from "./icons";

export interface DependencyBadgeProps {
  card: Pick<BoardCard, "ready" | "depends_on">;
}

/**
 * - not ready AND has deps  -> amber "waiting on X, Y"
 * - no deps at all          -> nothing (ready is trivial without deps)
 * - ready AND has deps      -> green "ready"
 */
function DependencyBadge({ card }: DependencyBadgeProps) {
  const { ready, depends_on } = card;

  if (!ready && depends_on.length > 0) {
    return (
      <span
        className="dep-badge dep-badge--waiting"
        title={`Waiting on ${depends_on.join(", ")}`}
      >
        <PadlockIcon aria-hidden="true" />
        waiting on {depends_on.join(", ")}
      </span>
    );
  }

  if (depends_on.length === 0) {
    return null;
  }

  if (ready) {
    return <span className="dep-badge dep-badge--ready">ready</span>;
  }

  return null;
}

export default DependencyBadge;
