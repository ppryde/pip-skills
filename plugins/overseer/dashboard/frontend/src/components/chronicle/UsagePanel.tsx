import { formatTokens } from "../../board/chronicle/format";
import { BarList } from "./ChronicleCharts";

interface UsagePanelProps {
  title: string;
  /** One line naming what is counted — including any deliberate overlap. */
  subtitle: string;
  rows: { label: string; value: number; detail?: string }[];
  hue?: string;
  /** Shown instead of an empty chart. An unbackfilled store has no plugin
   * rows, and a bare zero there reads as "you use no plugins" — which is a
   * different claim from "we have not looked yet". */
  emptyHint?: string;
}

/** A ranked breakdown of tool usage — MCP servers, or plugins. Presentational
 * only, so the Chronicle page and the session drawer render the same shape
 * from their own payloads. */
export default function UsagePanel({
  title,
  subtitle,
  rows,
  hue = "--chr-tools",
  emptyHint,
}: UsagePanelProps) {
  return (
    <section className="chr-panel" style={{ ["--chr-hue" as string]: `var(${hue})` }}>
      <h3 className="chr-panel__title">{title}</h3>
      <p className="chr-panel__sub">{subtitle}</p>
      {rows.length === 0 && emptyHint ? (
        <p className="chr-chart__empty">{emptyHint}</p>
      ) : (
        <BarList rows={rows} format={formatTokens} title={title} hue={hue} />
      )}
    </section>
  );
}
