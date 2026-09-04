/**
 * One session in detail — the Chronicle's counterpart to CardDetailDrawer,
 * and it reuses that drawer's shell classes (`.drawer-overlay`,
 * `.card-drawer`) so the two sheets read as one family. Page-local state
 * (ChroniclePage owns `openId`); Escape and the backdrop close it.
 */
import { useEffect } from "react";
import { useChronicleSession } from "../../board/chronicle/useChronicle";
import {
  formatActive,
  formatBytes,
  formatDuration,
  formatTokens,
  formatWhen,
  repoLabel,
  sessionName,
  shortModel,
} from "../../board/chronicle/format";
import { BarList, LineChart } from "./ChronicleCharts";
import StatTile from "./StatTile";

export interface SessionDrawerProps {
  sessionId: string | null;
  onClose: () => void;
}

export default function SessionDrawer({ sessionId, onClose }: SessionDrawerProps) {
  const { detail, loading, error } = useChronicleSession(sessionId);

  useEffect(() => {
    if (sessionId === null) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [sessionId, onClose]);

  if (sessionId === null) return null;

  const contextSeries = detail?.turn_series.map((t) => t.context_tokens) ?? [];
  // Compactions are timestamps; place each marker at the first turn at or
  // after it so the hairline lands where the context actually dropped.
  const markers =
    detail?.compactions_at
      .map((ts) => detail.turn_series.findIndex((t) => (t.ts ?? 0) >= ts))
      .filter((i) => i >= 0) ?? [];

  return (
    <div className="drawer-overlay" data-testid="chronicle-drawer-overlay" onClick={onClose}>
      <aside
        className="card-drawer chr-drawer"
        role="dialog"
        aria-label={detail ? `${sessionName(detail)} session` : "Session details"}
        onClick={(e) => e.stopPropagation()}
      >
        <button type="button" className="card-drawer__close" onClick={onClose} aria-label="Close">
          ×
        </button>
        {loading && !detail && <p className="card-drawer__status">Loading…</p>}
        {error && <p className="card-drawer__status card-drawer__status--error">{error}</p>}
        {detail && (
          <>
            <header className="chr-drawer__header">
              <p className="chr-drawer__eyebrow">
                <span className="chr-mono">{detail.session_id}</span>
                {detail.live && <span className="chr-live" title="Active in the last 15 minutes">live</span>}
              </p>
              <h2 className="chr-drawer__title">{sessionName(detail)}</h2>
              <p className="chr-drawer__facts">
                <span>{repoLabel(detail.repo_root)}</span>
                {detail.git_branch && <span className="chr-mono">{detail.git_branch}</span>}
                {detail.models.map((m) => (
                  <span key={m} className="chr-chip">
                    {shortModel(m)}
                  </span>
                ))}
              </p>
              <p className="chr-drawer__facts chr-drawer__facts--muted">
                <span>started {formatWhen(detail.started_at)}</span>
                <span>last {formatWhen(detail.last_activity_at)}</span>
                {detail.end_reason && <span>ended: {detail.end_reason}</span>}
                {detail.version && <span>cc {detail.version}</span>}
              </p>
            </header>

            <div className="chr-tiles chr-tiles--drawer">
              <StatTile label="Turns" value={String(detail.turns)} />
              <StatTile label="Prompts" value={String(detail.prompts)} />
              <StatTile label="Tool calls" value={String(detail.tool_calls)} />
              <StatTile label="Peak context" value={formatTokens(detail.peak_context_tokens)} />
              <StatTile label="Output tokens" value={formatTokens(detail.output_tokens)} />
              <StatTile
                label="Context processed"
                value={formatTokens(detail.context_tokens)}
                note="input + cache, summed over turns"
              />
              <StatTile label="Span" value={formatDuration(detail.duration_s)} />
              <StatTile label="Active" value={formatActive(detail.active_ms)} />
              <StatTile label="Transcript" value={formatBytes(detail.transcript_bytes)} />
              <StatTile label="Compactions" value={String(detail.compactions)} />
            </div>

            <section className="chr-panel">
              <h3 className="chr-panel__title">Context per turn</h3>
              <p className="chr-panel__sub">
                Tokens in the window on each API call{markers.length > 0 ? "; hairlines mark compactions" : ""}.
              </p>
              <LineChart
                values={contextSeries}
                format={formatTokens}
                title="Context tokens per turn"
                markers={markers}
              />
            </section>

            <section className="chr-panel">
              <h3 className="chr-panel__title">Tools</h3>
              <BarList
                rows={detail.tools.slice(0, 12).map((t) => ({ label: t.tool_name, value: t.calls }))}
                format={(n) => String(n)}
                title="Tool calls in this session"
              />
            </section>

            {detail.subagents.length > 0 && (
              <section className="chr-panel">
                <h3 className="chr-panel__title">Subagents</h3>
                <table className="chr-table chr-table--compact">
                  <thead>
                    <tr>
                      <th scope="col">Agent</th>
                      <th scope="col" className="chr-num">Turns</th>
                      <th scope="col" className="chr-num">Context</th>
                      <th scope="col" className="chr-num">Output</th>
                      <th scope="col" className="chr-num">Tools</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.subagents.map((a) => (
                      <tr key={a.agent_id}>
                        <td className="chr-mono">{a.agent_id.replace(/^a/, "").split("-").slice(0, -1).join("-") || a.agent_id}</td>
                        <td className="chr-num">{a.turns}</td>
                        <td className="chr-num">{formatTokens(a.context_tokens)}</td>
                        <td className="chr-num">{formatTokens(a.output_tokens)}</td>
                        <td className="chr-num">{a.tool_calls}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            )}
          </>
        )}
      </aside>
    </div>
  );
}
