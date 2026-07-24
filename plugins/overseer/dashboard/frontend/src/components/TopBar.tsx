import type { BoardCard, Context, Limits } from "../api/types";
import type { UseBoardResult } from "../board/useBoard";
import type { PartyMember } from "../board/party";
import { goldTotal } from "../board/goldTotal";
import { vanquishedStats } from "../board/vanquished";
import { formatTokens } from "../board/formatTokens";
import { CoinIcon, CheckIcon } from "./icons";
import ThresholdControl from "./ThresholdControl";

export interface TopBarProps {
  projectName: string;
  context: Context | null;
  limits: Limits;
  quarantinedCount: number;
  showArchive: boolean;
  onToggleArchive: () => void;
  onRefresh: () => void;
  refreshing: boolean;
  mutate: UseBoardResult["mutate"];
  inFlight: boolean;
  /** All board cards — feeds the gold-total and vanquished pills. */
  cards: BoardCard[];
  /** The shared session<->card join (App.tsx) — feeds the questing pill's
   * live count. */
  party: PartyMember[];
  /** From useBoard — feeds the parchment subtitle's timestamp. */
  lastRefreshedAt: Date | null;
  /** Opens the Party overlay (App.tsx owns partyOpen — HANDOFF §State
   * Management). */
  onOpenParty: () => void;
}

function formatPct(value: number): string {
  return `${value}%`;
}

// Subtitle copy MUST NOT contain the substring "as of last refresh" — the
// existing .topbar__ctx-note span hardcodes that exact text, and an RTL
// getByText(/as of last refresh/i) query throws on multiple matches rather
// than picking one (see TopBar.test.tsx).
function formatSubtitle(projectName: string, lastRefreshedAt: Date | null): string {
  if (lastRefreshedAt === null) return projectName;
  const hh = String(lastRefreshedAt.getHours()).padStart(2, "0");
  const mm = String(lastRefreshedAt.getMinutes()).padStart(2, "0");
  return `${projectName} · updated ${hh}:${mm}`;
}

/**
 * `context.model`/`context.pr` and top-level `limits` are census-derived
 * extras — OPTIONAL per the frozen contract. Each renders nothing when
 * absent so the bar degrades gracefully without the census integration.
 *
 * Parchment sticky bar (HANDOFF §Board "Top bar"): crest + branded title +
 * subtitle, then Refresh/Archive/Threshold/ctx (markup preserved from the
 * pre-theme bar, CSS-only restyle), then the three guild pills. The old
 * Sessions dropdown toggle is gone — the questing pill is its structural
 * replacement (Decisions), opening the Party overlay instead.
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
  mutate,
  inFlight,
  cards,
  party,
  lastRefreshedAt,
  onOpenParty,
}: TopBarProps) {
  const pct = context?.pct ?? null;
  const threshold = context?.threshold ?? null;
  const gold = goldTotal(cards);
  const { done, total } = vanquishedStats(cards);
  // "N questing" = live party members only — a stale session isn't
  // currently out on a quest, it's just a ghost still shown in the Party
  // column/overlay (Decisions: honest data, no invented capacity).
  const questingCount = party.filter((m) => !m.session.stale).length;

  return (
    <header className="topbar">
      <div className="topbar__identity">
        <span className="topbar__crest" aria-hidden="true" />
        <div className="topbar__titles">
          <h1>Adventurers&rsquo; Guild Board</h1>
          <p className="topbar__subtitle">
            {formatSubtitle(projectName, lastRefreshedAt)}
          </p>
        </div>
      </div>

      <div className="topbar__ctx">
        <span className="topbar__ctx-label">ctx</span>
        <span className="topbar__ctx-value">
          {pct === null ? "— unknown" : `${pct}%`}
        </span>
        <span className="topbar__ctx-note">as of last refresh</span>
        <ThresholdControl value={threshold} mutate={mutate} inFlight={inFlight} />
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

      <span className="topbar__gold-pill" title={`${gold} tokens total`}>
        <CoinIcon aria-hidden="true" />
        {formatTokens(gold)}
      </span>

      <span className="topbar__vanquished-pill">
        <CheckIcon aria-hidden="true" />
        {done} / {total} vanquished
      </span>

      <button
        type="button"
        className="topbar__questing-pill"
        onClick={onOpenParty}
      >
        {questingCount} questing
      </button>
    </header>
  );
}

export default TopBar;
