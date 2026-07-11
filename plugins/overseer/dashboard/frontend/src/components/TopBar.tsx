import type { Context, Limits } from "../api/types";

export interface TopBarProps {
  projectName: string;
  context: Context | null;
  limits: Limits;
  quarantinedCount: number;
  showArchive: boolean;
  onToggleArchive: () => void;
  onRefresh: () => void;
  refreshing: boolean;
}

function formatPct(value: number | undefined): string {
  return value === undefined ? "—" : `${value}%`;
}

/**
 * `context.model`/`context.pr` and top-level `limits` are census-derived
 * extras — OPTIONAL per the frozen contract. Each renders nothing when
 * absent so the bar degrades gracefully without the census integration.
 */
function TopBar({
  projectName,
  context,
  limits,
  quarantinedCount,
  showArchive,
  onToggleArchive,
  onRefresh,
  refreshing,
}: TopBarProps) {
  const pct = context?.pct ?? null;
  const threshold = context?.threshold ?? null;

  return (
    <header className="topbar">
      <h1>{projectName}</h1>

      <div className="topbar__ctx" title="as of last refresh">
        <span className="topbar__ctx-label">ctx</span>
        <span className="topbar__ctx-value">
          {pct === null ? "— unknown" : `${pct}%`}
        </span>
        {threshold !== null && (
          <span className="topbar__threshold">threshold {threshold}%</span>
        )}
      </div>

      {context?.model && <span className="topbar__pill">{context.model}</span>}
      {context?.pr && (
        <span className="topbar__pill">
          PR{context.pr.number !== undefined ? ` #${context.pr.number}` : ""}
          {context.pr.review_state ? ` · ${context.pr.review_state}` : ""}
        </span>
      )}
      {limits?.five_hour?.used_percentage !== undefined && (
        <span className="topbar__pill">
          5h {formatPct(limits.five_hour.used_percentage)}
        </span>
      )}
      {limits?.seven_day?.used_percentage !== undefined && (
        <span className="topbar__pill">
          7d {formatPct(limits.seven_day.used_percentage)}
        </span>
      )}

      <button
        type="button"
        className="topbar__refresh"
        onClick={onRefresh}
        disabled={refreshing}
      >
        {refreshing ? "Refreshing…" : "Refresh"}
      </button>

      <label className="topbar__archive-toggle">
        <input
          type="checkbox"
          checked={showArchive}
          onChange={onToggleArchive}
        />
        Archive
      </label>

      {quarantinedCount > 0 && (
        <span className="topbar__quarantine-banner">
          {quarantinedCount} quarantined — see archive/corrupt
        </span>
      )}
    </header>
  );
}

export default TopBar;
