import { useState } from "react";
import type { BoardCard, Context, Limits, RepoEntry } from "../api/types";
import type { UseBoardResult } from "../board/useBoard";
import type { PartyMember } from "../board/party";
import { goldTotal } from "../board/goldTotal";
import { vanquishedStats } from "../board/vanquished";
import { formatTokens } from "../board/formatTokens";
import { fleetSummary } from "../board/fleet";
import { distinctLabels } from "../board/cardFilter";
import { CoinIcon, CheckIcon } from "./icons";
import ThresholdControl from "./ThresholdControl";
import RepoSelector from "./RepoSelector";
import BranchFilter from "./BranchFilter";
import NewCardDialog from "./NewCardDialog";
import LabelSettingsDialog from "./LabelSettingsDialog";

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
  /** Task 7: opens the destructive clear-data dialog (`ClearDialog`,
   * App-owned) for the currently selected repo. Optional and rendered only
   * when set — App.tsx passes `undefined` while no repo is selected (no
   * `selectedRepo`), so there is never a Clear control with nothing to
   * target. */
  onClear?: () => void;
  /** WF-085b: mobile-only "Controls ▾" collapse state — App-owned (lifted
   * out of TopBar) so the ONE toggle can drive both TopBar's own
   * `#topbar-controls-group` AND the separate `<FilterBar/>` App renders as
   * a sibling below it. TopBar still renders the button and wraps its own
   * group with `hidden={!controlsOpen}` — it just no longer holds the
   * `useState` itself. */
  controlsOpen: boolean;
  /** Flips `controlsOpen` in App.tsx. */
  onToggleControls: () => void;
  /** F10 editable colour registry (WF-067) — board payload's `label_colors`,
   * threaded straight through to `LabelSettingsDialog` when it's open.
   * Optional (defaults to `{}`, same "undefined indistinguishable from
   * empty" contract as `LabelChips`/`LabelEditor`'s own `colorRegistry`
   * prop) so every existing call site keeps compiling unchanged. */
  labelColors?: Record<string, string>;
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
  onClear,
  labelColors,
  controlsOpen,
  onToggleControls,
}: TopBarProps) {
  // Task 10: "＋ New card" — TopBar owns this dialog's open state directly
  // (unlike the Clear control, which is App-owned since App also needs to
  // know when to show its post-clear toast). NewCardDialog is handed
  // TopBar's own `mutate` prop straight through, so the create routes
  // through the same single mutation entrypoint as every other control.
  const [newCardOpen, setNewCardOpen] = useState(false);
  // F10 (WF-067): the label-colors settings dialog — same TopBar-owned
  // open-state pattern as NewCardDialog above (no App-level prop needed).
  const [labelSettingsOpen, setLabelSettingsOpen] = useState(false);
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
    <>
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

        {/* Mobile row layout: the topbar is one wrapping flex row and every
            child below is a direct flex item of it — desktop relies on
            natural DOM order (unchanged), mobile re-sequences everything
            with `order` inside the `@media (max-width:720px)` block in
            styles.css. Real width-based wrapping alone isn't reliable
            across phone widths (e.g. repo+branch together could still be
            narrow enough to share a line with the rest pills on a wider
            phone), so these three zero-height spacers force hard row
            boundaries regardless of width — `aria-hidden` (not real
            content), `display:none` outside the mobile block so desktop
            never sees them at all. Their DOM position here is arbitrary
            (CSS `order` places them, not sibling adjacency) — grouped
            together right after identity to keep this diff small. */}
        <span className="topbar__row-break topbar__row-break--r2" aria-hidden="true" />
        <span className="topbar__row-break topbar__row-break--r3" aria-hidden="true" />
        <span className="topbar__row-break topbar__row-break--r4" aria-hidden="true" />

        <RepoSelector repos={repos} activeRoot={activeRoot} onSelect={onSelectRepo} />
        <button
          type="button"
          className="topbar__new-card"
          onClick={() => setNewCardOpen(true)}
        >
          ＋ New card
        </button>
        <BranchFilter
          branches={branches}
          activeBranch={activeBranch}
          onSelect={onSelectBranch}
        />

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

        {/* WF-085/085b: mobile-only "Controls ▾" toggle — collapses the
            secondary-controls group below AND the separate <FilterBar/>
            App.tsx renders as its own sibling, behind one tap on a ≤720px
            viewport (styles.css hides this button entirely above that
            breakpoint, so desktop never shows it). `aria-expanded` +
            `aria-controls` wire it to BOTH regions it drives — a
            space-separated id list is valid per WAI-ARIA. `controlsOpen`/
            `onToggleControls` are now App-owned (lifted out of TopBar) so
            the same flag reaches FilterBar too. */}
        <button
          type="button"
          className="topbar__controls-toggle"
          aria-expanded={controlsOpen}
          aria-controls="topbar-controls-group filter-bar"
          onClick={onToggleControls}
        >
          Controls {controlsOpen ? "▴" : "▾"}
        </button>

        {/* WF-085: the secondary-controls group — threshold, Clear…,
            Labels…, Refresh, Abandoned toggle. `hidden` is driven by
            `controlsOpen` (default collapsed), but styles.css only lets
            that attribute actually hide anything inside the ≤720px media
            query — above it `.topbar__controls-group` is unconditionally
            `display: contents`, so desktop renders every control exactly
            as before, unaffected by this flag. */}
        <div
          id="topbar-controls-group"
          className="topbar__controls-group"
          hidden={!controlsOpen}
        >
          {onClear && (
            <button
              type="button"
              className="topbar-clear danger"
              onClick={onClear}
              title="Clear this repo's data"
            >
              Clear…
            </button>
          )}
          <button
            type="button"
            // Task 10: shares the "＋ New card" control's Role-A button paint
            // (non-destructive positive action, same wobble shape) — see
            // `.topbar__new-card` in styles.css, reused here rather than
            // duplicated.
            className="topbar__new-card topbar__labels-settings"
            onClick={() => setLabelSettingsOpen(true)}
            title="Edit label colors"
          >
            Labels…
          </button>

          <div className="topbar__threshold">
            <ThresholdControl value={threshold} mutate={mutate} inFlight={inFlight} />
          </div>

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
            Abandoned
          </label>
        </div>

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
          {/* Mobile-only (styles.css): the full "N questing · top ctx N% ·
              N near threshold" line can be wider than R4's remaining row
              space next to the gold/vanquished pills — wrapping it in its
              own span gives ellipsis-truncation a real box to clip (a bare
              text run inside a flex container becomes an anonymous flex
              item CSS can't target), so the pill's OWN height stays a
              single line/matches its neighbours instead of growing to fit
              a wrapped second line. Desktop is untouched (no width cap
              there), so the full line still always shows in full. */}
          <span className="topbar__fleet-label">
            {questingCount} questing
            {fleet.topCtx !== null && <> · top ctx {fleet.topCtx}%</>}
            {fleet.nearThreshold > 0 && (
              <> · {fleet.nearThreshold} near threshold</>
            )}
          </span>
        </button>
      </header>
      {/* Task 10: NewCardDialog is a sibling of `<header>`, not nested
          inside it — same "modal is App/TopBar state, rendered outside the
          layout element it was opened from" precedent as ClearDialog. */}
      <NewCardDialog
        open={newCardOpen}
        onClose={() => setNewCardOpen(false)}
        mutate={mutate}
      />
      {/* F10 (WF-067): same "modal is TopBar state, rendered as a sibling
          of <header>" precedent as NewCardDialog above. `distinctLabels`
          (board/cardFilter) is recomputed from `cards` on every render —
          same source FilterBar's own label list uses (App.tsx), just
          computed here instead of threaded down as a prop. */}
      <LabelSettingsDialog
        open={labelSettingsOpen}
        onClose={() => setLabelSettingsOpen(false)}
        labels={distinctLabels(cards)}
        colors={labelColors ?? {}}
        mutate={mutate}
      />
    </>
  );
}

export default TopBar;
