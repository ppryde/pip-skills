import { formatTokens, formatUsd } from "../../board/chronicle/format";
import type { ChronicleAttribution } from "../../api/types";
import { BarList } from "./ChronicleCharts";

interface CostAttributionPanelProps {
  attribution?: ChronicleAttribution;
}

/**
 * Where the money went, from the attribution Claude Code stamps on each turn.
 *
 * Plugins and subagent types are shown in ONE ranked list because they are
 * both answers to "what was this turn doing", and a reader wants them ranked
 * against each other — is superpowers costing me more than my Explore agents?
 * Two lists would hide that.
 *
 * The unattributed remainder is a row of its own rather than an omission: it
 * is the majority of the spend, and a panel that showed only the attributed
 * slice would read as the whole bill.
 */
export default function CostAttributionPanel({ attribution }: CostAttributionPanelProps) {
  const total = (attribution?.cost_usd ?? 0) + (attribution?.unattributed_cost_usd ?? 0);
  const rows = [
    ...(attribution?.agents ?? []).map((a) => ({
      label: `${a.name} · agent`,
      detail: `${formatTokens(a.turns)} turns · ${formatTokens(a.context_tokens)} context`,
      value: a.cost_usd ?? 0,
    })),
    ...(attribution?.plugins ?? []).map((p) => ({
      label: `${p.name} · plugin`,
      detail: `${formatTokens(p.turns)} turns · ${formatTokens(p.context_tokens)} context`,
      value: p.cost_usd ?? 0,
    })),
  ]
    .filter((r) => r.value > 0)
    .sort((a, b) => b.value - a.value)
    .slice(0, 12);

  const unattributed = attribution?.unattributed_cost_usd ?? 0;
  if (unattributed > 0) {
    rows.push({
      label: "unattributed",
      detail: "turns with nothing in scope — most turns, correctly",
      value: unattributed,
    });
  }

  return (
    <section className="chr-panel" style={{ ["--chr-hue" as string]: "var(--chr-cost)" }}>
      <h3 className="chr-panel__title">Cost attribution</h3>
      <p className="chr-panel__sub">
        {total > 0
          ? `${formatUsd(total)} at list prices. Plugins and subagents ranked together — a turn is `
            + `counted once even when both apply.`
          : "What each plugin and subagent type cost, at list prices."}
      </p>
      {rows.length === 0 ? (
        <p className="chr-chart__empty">
          No attribution recorded. Historical sessions need a `chronicle sync --full` to backfill.
        </p>
      ) : (
        <BarList rows={rows} format={formatUsd} title="Cost attribution" hue="--chr-cost" />
      )}
    </section>
  );
}
