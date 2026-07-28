import type { BoardCard, Context, Limits, RepoEntry } from "../api/types";
import type { UseBoardResult } from "../board/useBoard";
import type { PartyMember } from "../board/party";
import { goldTotal } from "../board/goldTotal";
import { vanquishedStats } from "../board/vanquished";
import { formatTokens } from "../board/formatTokens";
import { fleetSummary } from "../board/fleet";
import { CoinIcon, CheckIcon } from "./icons";
import ThresholdControl from "./ThresholdControl";
import RepoSelector from "./RepoSelector";
import BranchFilter from "./BranchFilter";

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
  /** The shared session<->card join (App.tsx) — feeds the fleet-health
   * pill's live questing count, top ctx%, and near-threshold count
   * (`fleetSummary`, WF-042). */
  party: PartyMember[];
  /** From useBoard — feeds the parchment subtitle's timestamp. */
  lastRefreshedAt: Date | null;
  /** Opens the Party overlay (App.tsx owns partyOpen — HANDOFF §State
   * Management). */
  onOpenParty: () => void;
  /** WF-030 repo selector — every discoverable board (`useRepos`), the
   * currently-selected root (App.tsx state, null = launch root default),
   * and the handler that commits a new selection. */
  repos: RepoEntry[];
  activeRoot: string | null;
  onSelectRepo: (root: string) => void;
  /** WF-031 branch filter — the distinct-branch union (`distinctBranches`),
   * the session-local active selection, and its setter. `null` = "All". */
  branches: string[];
  activeBranch: string | null;
  onSelectBranch: (branch: string | null) => void;
  /** Task 10: for an "unbegun" repo (WF-032, `has_board: false`) `useSessions`
   * is hard-gated off (see App.tsx), so `party` is never populated for it —
   * computing the questing pill from `party` would show a contradictory "0
   * questing" next to `<UnbegunHolding/>`'s own "N adventurers already roam
   * these lands" (sourced from `repo.live_sessions`). When set, this
   * OVERRIDES the party-derived count so both readouts agree; `undefined`
   * (every other repo) keeps the normal live-party-member count below. */
  questingCountOverride?: number;
}

function formatPct(value: number): string {
  // Round to a whole percent — census `used_percentage` arrives as a float
  // that can carry FP noise (e.g. 28.000000000000004); ctx% is already int,
  // so Math.round is a no-op there.
  return `${Math.round(value)}%`;
}

function formatSubtitle(projectName: string, lastRefreshedAt: Date | null): string {
  if (lastRefreshedAt === null) return projectName;
  const hh = String(lastRefreshedAt.getHours()).padStart(2, "0");
  const mm = String(lastRefreshedAt.getMinutes()).padStart(2, "0");
  return `${projectName} · updated ${hh}:${mm}`;
}

/**
 * Top-level `limits` is a census-derived extra — OPTIONAL per the frozen
 * contract. Renders nothing when absent so the bar degrades gracefully
 * without the census integration.
 *
 * WF-042: `context.model`/`context.pr`/the single `ctx NN%` value are GONE
 * from this bar — those were the *launching* session's facts, arbitrary in
 * a multi-agent board (see the WF-042 spec's Problem statement). They now
 * live per-agent on the Party's hero cards. What replaces them here is a
 * fleet-health line (`fleetSummary()` over every live party session) plus
 * the threshold control, reframed as the fleet's global DEFAULT (per-agent
 * override is a deferred follow-up). `context.threshold` itself is still
 * read from here — it's the one board/account-level fact this bar keeps.
 *
 * Parchment sticky bar (HANDOFF §Board "Top bar"): crest + branded title +
 * subtitle, then Refresh/Archive/threshold-default/fleet-health, then the
 * two remaining guild pills (gold, vanquished). The old Sessions dropdown
 * toggle is gone, and the old dedicated questing pill is folded into the
 * fleet-health line below (same live-count source, no duplicate readout,
 * still opens the Party overlay on click).
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
  repos,
  activeRoot,
  onSelectRepo,
  branches,
  activeBranch,
  onSelectBranch,
  questingCountOverride,
}: TopBarProps) {
  const threshold = context?.threshold ?? null;
  const gold = goldTotal(cards);
  const { done, total } = vanquishedStats(cards);
  // WF-042: fleet-health line replaces the old questing-only pill — same
  // live-session source (`fleetSummary` drops stale sessions itself, see
  // its doc comment), now paired with the fleet's top ctx% and
  // near-threshold count.
  const fleet = fleetSummary(
    party.map((m) => m.session),
    threshold
  );
  // "N questing" = live party members only — a stale session isn't
  // currently out on a quest, it's just a ghost still shown in the Party
  // column/overlay (Decisions: honest data, no invented capacity).
  // `questingCountOverride` (task 10) wins when set — see its doc comment.
  const questingCount = questingCountOverride ?? fleet.questing;

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

      <RepoSelector repos={repos} activeRoot={activeRoot} onSelect={onSelectRepo} />
      <BranchFilter
        branches={branches}
        activeBranch={activeBranch}
        onSelect={onSelectBranch}
      />

      <div className="topbar__threshold">
        <ThresholdControl value={threshold} mutate={mutate} inFlight={inFlight} />
      </div>

      {limits?.five_hour?.used_percentage !== undefined && (
        <span className="topbar__pill" title="5h window">
          ⛺ Short Rest {formatPct(limits.five_hour.used_percentage)}
        </span>
      )}
      {limits?.seven_day?.used_percentage !== undefined && (
        <span className="topbar__pill" title="7d window">
          ⛺ Long Rest {formatPct(limits.seven_day.used_percentage)}
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

      {/* WF-042 fleet-health line — replaces the old dedicated questing
          pill (Decisions: single live-count source, folded in rather than
          duplicated). `topCtx`/`nearThreshold` segments are omitted
          gracefully when there's no pct data to report — never a
          "top ctx null%" or a noisy "0 near threshold". */}
      <button
        type="button"
        className="topbar__fleet-pill"
        onClick={onOpenParty}
      >
        <span className="topbar__fleet-icon" aria-hidden="true">
          ⚔
        </span>
        {questingCount} questing
        {fleet.topCtx !== null && <> · top ctx {fleet.topCtx}%</>}
        {fleet.nearThreshold > 0 && (
          <> · {fleet.nearThreshold} near threshold</>
        )}
      </button>
    </header>
  );
}

export default TopBar;
