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
import journalIcon from "../assets/ui-icons/journal.png";
import treasureMapIcon from "../assets/ui-icons/treasure-map.png";

export interface TopBarProps {
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
  /** WF-086: which page the app is showing — the board or the Epic Atlas.
   * App-owned, session-local state, threaded straight through like
   * `activeBranch`. Required — App.tsx has owned and passed this since
   * its own chunk landed; the standalone-compile rationale for making it
   * optional expired the moment that wiring existed. */
  view: "board" | "atlas";
  onSelectView: (view: "board" | "atlas") => void;
}

function formatPct(value: number): string {
  // Round to a whole percent — census `used_percentage` arrives as a float
  // that can carry FP noise (e.g. 28.000000000000004); ctx% is already int,
  // so Math.round is a no-op there.
  return `${Math.round(value)}%`;
}

function formatUpdated(lastRefreshedAt: Date): string {
  const hh = String(lastRefreshedAt.getHours()).padStart(2, "0");
  const mm = String(lastRefreshedAt.getMinutes()).padStart(2, "0");
  return `updated ${hh}:${mm}`;
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
 * Parchment sticky bar (HANDOFF §Board "Top bar"): the Board|Atlas view-toggle
 * circles + branded title + a small last-updated time, then
 * Refresh/Archive/threshold-default/fleet-health, then the
 * two remaining guild pills (gold, vanquished). The old Sessions dropdown
 * toggle is gone, and the old dedicated questing pill is folded into the
 * fleet-health line below (same live-count source, no duplicate readout,
 * still opens the Party overlay on click).
 */
function TopBar({
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
  view,
  onSelectView,
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
        {/* WF-086 (moved): the Board|Atlas toggle is a small stack of two
            overlapping "guild coins" to the LEFT of the wordmark. The active
            view's coin sits in front; tapping the coin behind slides it forward
            and swaps the view (`.topbar__view-toggle*` in styles.css). Both are
            always-visible (never behind the mobile "Controls ▾" collapse) and
            self-labelled via `aria-label`/`title`. A two-coin stack only reads
            for two views — fine while Board|Atlas are the only pages. The
            last-refreshed time is no longer here: it moved to a small label
            beside the Refresh control below. */}
        <div className="topbar__identity">
          <div className="topbar__view-toggle" role="group" aria-label="View">
            <button
              type="button"
              className="topbar__view-toggle-btn"
              aria-pressed={view === "board"}
              aria-label="Board"
              title="Board"
              onClick={() => onSelectView("board")}
            >
              {/* rpg-icons pack "journal" — the guild's belted quest-ledger */}
              <img src={journalIcon} alt="" className="topbar__view-toggle-icon" />
            </button>
            <button
              type="button"
              className="topbar__view-toggle-btn"
              aria-pressed={view === "atlas"}
              aria-label="Atlas"
              title="Atlas"
              onClick={() => onSelectView("atlas")}
            >
              {/* rpg-icons pack "treasure map" — dashed trail and all */}
              <img src={treasureMapIcon} alt="" className="topbar__view-toggle-icon" />
            </button>
          </div>
          <h1>Adventurers&rsquo; Guild Board</h1>
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

        {/* WF-085: the secondary-controls group — Last Orders (threshold),
            Labels…, Refresh, Abandoned toggle, Clear… (WF-090: Labels…
            grouped with the action buttons, Clear… kept rightmost).
            `hidden` is driven by `controlsOpen` (default collapsed), but
            styles.css only lets that attribute actually hide anything
            inside the ≤720px media query — above it
            `.topbar__controls-group` is unconditionally `display: contents`,
            so desktop renders every control exactly as before, unaffected
            by this flag. */}
        <div
          id="topbar-controls-group"
          className="topbar__controls-group"
          hidden={!controlsOpen}
        >
          <div className="topbar__threshold">
            <ThresholdControl value={threshold} mutate={mutate} inFlight={inFlight} />
          </div>

          {/* WF-090 follow-up: Labels…/Refresh/Abandoned/Clear… wrapped in
              their own atomic flex unit — desktop is natural-wrap (no
              `order` above 720px), and `.topbar__refresh`'s pre-existing
              `margin-left: auto` (hugs the right edge of WHATEVER line it
              lands on) means the exact wrap point between these four and
              everything before them (repo/branch/rest-pills/Last Orders)
              shifts with viewport width and even live content width (gold
              total digit count, timestamp, etc) — moving Labels… next to
              Refresh in DOM order alone still let it get stranded on the
              upper line at some widths (verified: reproducible at 1500px,
              NOT at 1180px, same content). Wrapping all four in one
              `.topbar__controls-actions` box makes them wrap TOGETHER as a
              single flex item of `.topbar` — Labels… can never again land
              on a different line than Refresh/Abandoned/Clear…, regardless
              of width. `display: contents` on this wrapper inside the
              ≤720px block (styles.css) fully un-wraps it back to individual
              flex items of `.topbar__controls-group` on mobile, where the
              existing per-child `order` resets (below) still apply
              untouched. */}
          <div className="topbar__controls-actions">
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

            <button
              type="button"
              className="topbar__refresh"
              onClick={onRefresh}
              disabled={refreshing}
            >
              {refreshing ? "Refreshing…" : "Refresh"}
            </button>

            {/* Last-refreshed time — a small label beside Refresh (moved out of
                the header). Omitted until the first successful load. */}
            {lastRefreshedAt !== null && (
              <span className="topbar__updated">{formatUpdated(lastRefreshedAt)}</span>
            )}

            <label className="topbar__archive-toggle">
              <input
                type="checkbox"
                checked={showArchive}
                onChange={onToggleArchive}
              />
              Abandoned
            </label>

            {/* WF-090: moved to the END of this group (was first) — Clear is
                the one destructive action here, so it now sits rightmost,
                separated from the constructive controls (Labels…/Refresh/
                Abandoned) rather than leading them. Mobile's `flex-wrap`
                row needed a small styles.css fix alongside it: "Labels…"
                reuses `.topbar__new-card`'s class, which carries an
                `order: 40` meant for that button's OTHER life in the outer
                topbar row — inside THIS group's own flex context that
                leaked order was sorting Labels… after everything else, so
                `.topbar-clear`/`.topbar__new-card` both get an explicit
                reset scoped to `.topbar__controls-group` (see styles.css)
                rather than relying on DOM order alone. */}
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
          </div>
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
