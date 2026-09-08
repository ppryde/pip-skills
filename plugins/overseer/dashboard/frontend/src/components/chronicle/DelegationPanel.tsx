import { formatTokens } from "../../board/chronicle/format";
import type { ChronicleDelegation } from "../../api/types";

interface DelegationPanelProps {
  delegation?: ChronicleDelegation;
}

interface Share {
  label: string;
  part: number;
  whole: number;
  detail: string;
}

/**
 * What subagents DO against what they PRODUCE — three shares of the same
 * population, so they can be read against each other.
 *
 * Deliberately three bars of one measure rather than a donut per row: the
 * point is the GAP between them (most of the turns, little of the prose),
 * and three donuts would make that comparison a memory exercise.
 *
 * Counted from `agent_id`, which every turn and tool call carries, so this
 * covers the whole store — unlike attribution, which only lands where
 * something was in scope.
 */
export default function DelegationPanel({ delegation }: DelegationPanelProps) {
  if (!delegation || delegation.turns === 0) {
    return (
      <section className="chr-panel" style={{ ["--chr-hue" as string]: "var(--chr-turns)" }}>
        <h3 className="chr-panel__title">Delegation</h3>
        <p className="chr-chart__empty">No turns in this window.</p>
      </section>
    );
  }

  const shares: Share[] = [
    {
      label: "Turns",
      part: delegation.subagent_turns,
      whole: delegation.turns,
      detail: `${formatTokens(delegation.subagent_turns)} of ${formatTokens(delegation.turns)}`,
    },
    {
      label: "Tool calls",
      part: delegation.subagent_tool_calls,
      whole: delegation.tool_calls,
      detail: `${formatTokens(delegation.subagent_tool_calls)} of ${formatTokens(delegation.tool_calls)}`,
    },
    {
      label: "Output tokens",
      part: delegation.subagent_output_tokens,
      whole: delegation.output_tokens,
      detail: `${formatTokens(delegation.subagent_output_tokens)} of ${formatTokens(delegation.output_tokens)}`,
    },
  ];

  return (
    <section className="chr-panel" style={{ ["--chr-hue" as string]: "var(--chr-turns)" }}>
      <h3 className="chr-panel__title">Delegation</h3>
      <p className="chr-panel__sub">How much of the work ran inside subagents.</p>
      <div className="chr-shares" role="list" aria-label="Delegation">
        {shares.map((s) => {
          const pct = s.whole > 0 ? (s.part / s.whole) * 100 : 0;
          return (
            <div className="chr-shares__row" role="listitem" key={s.label} title={s.detail}>
              <span className="chr-shares__label">{s.label}</span>
              <span className="chr-shares__track" aria-hidden="true">
                <span className="chr-shares__fill" style={{ width: `${Math.max(0, pct)}%` }} />
              </span>
              <span className="chr-shares__value" aria-label={`${s.label}: ${Math.round(pct)}% delegated, ${s.detail}`}>
                {Math.round(pct)}%
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}
