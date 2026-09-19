import { useState, type CSSProperties } from "react";
import type { AccountEntry, BoardCard, Context, Limits, RepoEntry } from "../api/types";
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
import AccountSelector from "./AccountSelector";
import NewCardDialog from "./NewCardDialog";
import LabelSettingsDialog from "./LabelSettingsDialog";
// WF-097 follow-up: routes this bar's Role-A buttons + the plain rest/
// updated pills through the design-library primitives (`src/ui/`) — see
// each call site below for which bespoke class stays (layout-only) and
// which was fully absorbed into `.qb-btn`/`.qb-chip`. The view-toggle
// "coins" and the gold/vanquished/fleet pills are DELIBERATELY left as
// bespoke markup: the coins are a wholly different circular/stacked shape
// (not a Role-A button), and the three guild pills share one combined CSS
// selector with (fleet-pill only) real button semantics — splitting two of
// the three onto `<Chip>` while leaving fleet-pill native would fragment
// that shared rule for no visual gain (see styles.css's own comment on
// `.topbar__gold-pill, .topbar__vanquished-pill, .topbar__fleet-pill`).
import { Button, Chip, Label } from "../ui";
import journalIcon from "../assets/ui-icons/journal.png";
import treasureMapIcon from "../assets/ui-icons/treasure-map.png";
import skullIcon from "../assets/ui-icons/skull.png";
import scrollIcon from "../assets/ui-icons/scroll.png";
import scryIcon from "../assets/ui-icons/scry.png";
import settingsIcon from "../assets/ui-icons/settings.png";

/** The dashboard's pages, each a coin in the view switcher. Chronicle (the
 * optional session-telemetry page) and Almoner (the optional inflow-triage
 * page) each get a coin only when their plugin is installed beside this
 * dashboard. */
export type View = "board" | "atlas" | "chronicle" | "almoner";

/** What the guild bar calls the page you are on.
 *
 * The wordmark used to be the literal string "Adventurers' Guild Board" on
 * every page, which left the Chronicle and the Almoner unnamed anywhere on
 * screen — the Chronicle has no heading of its own at all, so it was a page
 * you could only identify by what it happened to be showing. The board keeps
 * the guild wordmark because on the board that IS the name. */
const VIEW_TITLES: Record<View, string> = {
  board: "Adventurers\u2019 Guild Board",
  atlas: "Epic Atlas",
  chronicle: "Chronicle",
  almoner: "Almoner",
};

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
  /** WF-116 account selector — every account this machine knows about
   * (`useAccounts`), the persisted active selection (App.tsx state, `null`
   * = "All accounts"), and the handler that commits a new one. Shown on the
   * board and Chronicle only (hidden on Atlas/Almoner, which have no
   * sessions of their own to scope) and only once there is more than one
   * account to choose between (`AccountSelector` itself hides below two). */
  accounts: AccountEntry[];
  activeAccount: string | null;
  onSelectAccount: (account: string | null) => void;
  /** Task 7: opens the destructive clear-data dialog (`ClearDialog`,
   * App-owned) for the currently selected repo. Optional and rendered only
   * when set — App.tsx passes `undefined` while no repo is selected (no
   * `selectedRepo`), so there is never a Clear control with nothing to
   * target. */
  onClear?: () => void;
  /** App-owned "Controls ▾" collapse state, driving ONLY TopBar's own
   * `#topbar-controls-group` now — it used to also fold the separate
   * `<FilterBar/>` under the same flag, but that's split into its own
   * independent `filtersOpen`/`onToggleFilters` pair below (the "Filters ▾"
   * button, left of "Controls ▾"). TopBar still renders the button and
   * wraps its own group with `hidden={!controlsOpen}` — it just doesn't
   * hold the `useState` itself. */
  controlsOpen: boolean;
  /** Flips `controlsOpen` in App.tsx. */
  onToggleControls: () => void;
  /** App-owned "Filters ▾" collapse state — drives the separate
   * `<FilterBar/>` App.tsx renders as a sibling below this bar
   * (`hidden={!filtersOpen}` on its root). Independent of `controlsOpen`;
   * TopBar only renders the toggle button itself. */
  filtersOpen: boolean;
  /** Flips `filtersOpen` in App.tsx. */
  onToggleFilters: () => void;
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
  view: View;
  onSelectView: (view: View) => void;
  /** Whether `/api/chronicle/status` reported the plugin installed — gates
   * the Chronicle coin entirely (absent plugin, absent coin). */
  chronicleAvailable?: boolean;
  /** The Chronicle's Sync action (App-owned, `useChronicleSync`). On the
   * Chronicle page it takes the ＋ New card control's place in the toggle
   * cluster — the page has no cards to add, and Sync is its one action. */
  onChronicleSync?: () => void;
  chronicleSyncing?: boolean;
  /** On the Chronicle page the repo selector gains an "All repos" choice,
   * since that page's data is account-wide. App-owned; see RepoSelector. */
  chronicleAllRepos?: { selected: boolean; onSelect: (all: boolean) => void };
  /** Whether `/api/almoner/status` reported the plugin installed — gates
   * the Almoner coin entirely (absent plugin, absent coin). */
  almonerAvailable?: boolean;
  /** WF-091: the Epic Atlas toolbar folded into the Controls group — single
   * toggle buttons rendered ONLY when `view === "atlas"` (retired
   * standalone `<AtlasToolbar>`, which sat between the topbar and the
   * chart). App.tsx owns both as lifted state (was EpicAtlas-local),
   * same "App owns cross-cutting UI state" precedent as `activeBranch`/
   * `controlsOpen`. */
  /** Quest name-tags on the trail — default true (shown). */
  showNames: boolean;
  onToggleNames: (next: boolean) => void;
  /** Vanquished (done) epics — default true (HIDDEN; the prop name is the
   * negative-sense "hide" flag, matching EpicAtlas's original local state
   * name so the lifted prop reads the same at both ends). */
  hideVanquished: boolean;
  onToggleVanquished: (next: boolean) => void;
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
  accounts,
  activeAccount,
  onSelectAccount,
  questingCountOverride,
  onClear,
  labelColors,
  controlsOpen,
  onToggleControls,
  filtersOpen,
  onToggleFilters,
  view,
  onSelectView,
  showNames,
  onToggleNames,
  hideVanquished,
  onToggleVanquished,
  chronicleAvailable = false,
  onChronicleSync,
  chronicleSyncing = false,
  chronicleAllRepos,
  almonerAvailable = false,
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
  // Live sessions census flags `idle` — present, but their activity counters
  // haven't moved for 10 minutes. Shown as a suffix rather than deducted from
  // the questing count: they ARE still out there, just not swinging. Suppressed
  // under `questingCountOverride`, whose count comes from a different source
  // (an unbegun repo's own live-session tally) and has no idle split to report.
  const idleCount = questingCountOverride === undefined ? fleet.idle : 0;

  // One coin per page, spread in an overlapping row; each coin selects its
  // own view (the pressed coin is inert — it already is the page). This
  // replaces the old two-coin "click either to swap" toggle, which only
  // ever encoded two views. rpg-icons pack art: journal (the guild's belted
  // quest-ledger), treasure map (dashed trail and all), sealed letter (the
  // session ledger).
  const coins: { view: View; label: string; title: string; icon: string }[] = [
    { view: "board", label: "Board", title: "Board", icon: journalIcon },
    { view: "atlas", label: "Atlas", title: "Atlas", icon: treasureMapIcon },
    ...(chronicleAvailable
      ? [{ view: "chronicle" as View, label: "Chronicle", title: "The Chronicle — session token usage and shape", icon: scrollIcon }]
      : []),
    ...(almonerAvailable
      ? [{ view: "almoner" as View, label: "Almoner", title: "The Almoner — what is asking for your attention, gathered and triaged", icon: scryIcon }]
      : []),
  ];
  // The Chronicle has no cards or board provisions: on that page the
  // Controls group and ＋ New card give way and Sync takes the ＋ slot. The
  // repo and branch selectors stay and drive the Chronicle's scope directly
  // (App feeds them that page's branch list and an "All repos" choice).
  // The pressed coin always sits leftmost (slot 0); the rest keep their
  // source order behind it. Slots drive position through a CSS custom
  // property rather than DOM order, so each coin stays the same element and
  // slides to its new place instead of being remounted there.
  const activeIndex = Math.max(0, coins.findIndex((c) => c.view === view));
  const slotOf = (i: number) => (i === activeIndex ? 0 : i < activeIndex ? i + 1 : i);
  // Every view change sets the whole row spinning while it rearranges.
  // Alternating between two identical keyframe names restarts the animation
  // even when a second change lands mid-spin; `null` until the first change,
  // so the coins sit still on load. Adjusted during render (React's "state
  // from a changed prop" pattern), not in an effect, to skip a stale frame.
  const [spunView, setSpunView] = useState(view);
  const [spins, setSpins] = useState(0);
  if (view !== spunView) {
    setSpunView(view);
    setSpins((n) => n + 1);
  }
  const spin = spins === 0 ? undefined : spins % 2 ? "a" : "b";
  const onChronicle = view === "chronicle";
  // The Almoner likewise has no cards: it suppresses the board-only
  // controls, but unlike the Chronicle it owns its own Gather action on the
  // page itself and needs no slot in this cluster.
  const onAlmoner = view === "almoner";
  /** Pages with no cards of their own — the board-only controls give way. */
  const boardless = onChronicle || onAlmoner;

  return (
    <>
      <header className="topbar">
        {/* WF-086 (moved): the view switcher is a row of overlapping "guild
            coins" to the LEFT of the wordmark, the active view's coin in front
            (`.topbar__view-toggle*` in styles.css). Always-visible (never
            behind the mobile "Controls ▾" collapse) and self-labelled via
            `aria-label`/`title`. The last-refreshed time is no longer here: it
            moved to a small label beside Refresh below. */}
        <div className="topbar__identity">
          <div
            className="topbar__view-toggle"
            role="group"
            aria-label="View"
            data-count={coins.length}
            data-spin={spin}
            style={{ "--coin-count": coins.length } as CSSProperties}
          >
            {coins.map((c, i) => (
              <button
                key={c.view}
                type="button"
                className="topbar__view-toggle-btn"
                data-slot={slotOf(i)}
                style={{ "--slot": slotOf(i) } as CSSProperties}
                aria-pressed={view === c.view}
                aria-label={c.label}
                title={c.title}
                onClick={() => onSelectView(c.view)}
              >
                <img src={c.icon} alt="" className="topbar__view-toggle-icon" />
              </button>
            ))}
          </div>
          <h1>{VIEW_TITLES[view]}</h1>
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

        <RepoSelector
          repos={repos}
          activeRoot={activeRoot}
          onSelect={onSelectRepo}
          allOption={onChronicle ? chronicleAllRepos : undefined}
        />
        <BranchFilter
          branches={branches}
          activeBranch={activeBranch}
          onSelect={onSelectBranch}
          keepWhenEmpty={onChronicle}
        />
        {/* WF-116: board + Chronicle only — Atlas/Almoner have no sessions
            of their own for an account to scope. */}
        {view !== "atlas" && !onAlmoner && (
          <AccountSelector
            accounts={accounts}
            activeAccount={activeAccount}
            onSelect={onSelectAccount}
          />
        )}

        {limits?.five_hour?.used_percentage !== undefined && (
          <Chip className="topbar__pill" title="5h window">
            ⛺ Short Rest {formatPct(limits.five_hour.used_percentage)}
          </Chip>
        )}
        {limits?.seven_day?.used_percentage !== undefined && (
          <Chip className="topbar__pill" title="7d window">
            ⛺ Long Rest {formatPct(limits.seven_day.used_percentage)}
          </Chip>
        )}
        {/* Task 5: last-refreshed moved out of the Controls group and
            grouped here as its own note-badge pill, right beside the two
            rest pills (same `.topbar__pill` treatment — now literally
            `.qb-chip` under the hood, WF-097 follow-up). Omitted entirely
            until the first successful load, same as before the move. */}
        {lastRefreshedAt !== null && (
          <Chip className="topbar__pill" title="last refreshed">
            {formatUpdated(lastRefreshedAt)}
          </Chip>
        )}

        {/* Filters ▾ / Controls ▾ / ＋ — three independent controls grouped
            as one cluster. Filters and Controls used to be ONE shared
            "Controls ▾" toggle driving both TopBar's own group AND the
            separate <FilterBar/>; they're now two independent toggles, each
            wired to just its own region via `aria-controls`. `hidden={
            !filtersOpen}`/`hidden={!controlsOpen}` take effect on every
            viewport now, not just ≤720px (see styles.css) — both default
            open so the board looks unchanged on load, but either can be
            collapsed on any screen size. */}
        <div className="topbar__toggle-cluster">
          {!onAlmoner && (
            // The Chronicle still gets this: <ChronicleFilterBar/> reuses
            // the very same `#filter-bar` id App.tsx renders FilterBar at on
            // the board, so `boardless` alone is the wrong guard here — it
            // would hide this on the Chronicle too, where the control it
            // names still exists. The Almoner is the one page with no filter
            // bar of any kind, so `aria-controls="filter-bar"` would point at
            // an element that is never in the DOM.
            <Button
              className="topbar__controls-toggle"
              aria-expanded={filtersOpen}
              aria-controls="filter-bar"
              onClick={onToggleFilters}
            >
              Filters {filtersOpen ? "▴" : "▾"}
            </Button>
          )}
          {!boardless && (
            <Button
              className="topbar__controls-toggle"
              aria-expanded={controlsOpen}
              aria-controls="topbar-controls-group"
              onClick={onToggleControls}
            >
              {/* rpg-icons pack "settings" gear — decorative only (`alt=""`),
                  so the button's accessible name stays plain "Controls" (task
                  C: no equivalent funnel/filter asset exists for the
                  "Filters ▾" button beside this one, so that stays text-only). */}
              <img src={settingsIcon} alt="" className="topbar__toggle-icon" />
              Controls {controlsOpen ? "▴" : "▾"}
            </Button>
          )}
          {onChronicle ? (
            /* The Chronicle's one action, in the slot ＋ New card holds on the
               other pages. Gold primary: it is the page's call to action, and
               the blank-chronicle prompt points at it by name. */
            <Button
              variant="primary"
              className="topbar__sync"
              onClick={onChronicleSync}
              disabled={chronicleSyncing || !onChronicleSync}
              title="Read every session transcript on this machine into the chronicle"
            >
              {chronicleSyncing ? "Syncing…" : "Sync"}
            </Button>
          ) : onAlmoner ? null : (
            /* "＋ New card" is icon-only — `aria-label`/`title` keep it
               accessible/resolvable by name exactly as the old "＋ New card"
               text button was; opens the same NewCardDialog unchanged.
               variant="neutral" (not "primary"): despite being a create
               action, `.topbar__new-card`'s own chrome paints it with the
               same PLAIN Role-A face as Refresh, not the gold `.qb-btn--
               primary` fill — keeping it neutral here preserves that
               existing look exactly (WF-097 follow-up). */
            <Button
              variant="neutral"
              className="topbar__new-card topbar__new-card--icon"
              onClick={() => setNewCardOpen(true)}
              aria-label="New card"
              title="New card"
            >
              ＋
            </Button>
          )}
        </div>

        {/* WF-085 (Task 2/3): the secondary-controls group — Last Orders
            (threshold), Labels…, Refresh, Abandoned toggle, Clear… (WF-090:
            Labels… grouped with the action buttons, Clear… kept rightmost).
            `hidden` is driven by `controlsOpen`, defaulting OPEN (the board
            looks unchanged on load); the Controls ▾ button above collapses
            it on every viewport now — desktop is no longer exempt (see
            `.topbar__controls-group[hidden]` in styles.css). */}
        <div
          id="topbar-controls-group"
          className="topbar__controls-group"
          hidden={!controlsOpen || boardless}
        >
          {/* Task 4: a small dotted-line header opening the group — same
              "quiet caption above a dashed rule" idea as FilterBar's own
              "Scry" eyebrow, just recast as a divider+title here. Routes
              through `<Label/>` (design-library eyebrow migration) same as
              that "Scry" eyebrow already does — `.topbar__controls-eyebrow`
              only carries its own 0.06em letter-spacing override now,
              cancelling `.qb-label`'s 0.04em default (declared later in
              styles.css, so it wins), same pattern RepoSelector/BranchFilter/
              FilterBar's own eyebrows already follow. */}
          <div className="topbar__controls-header">
            <Label className="topbar__controls-eyebrow">Provisions</Label>
          </div>
          <div className="topbar__threshold">
            <ThresholdControl value={threshold} mutate={mutate} inFlight={inFlight} />
          </div>

          {/* WF-091: Epic Atlas's toggles, folded into the Controls
              group and shown ONLY on the Atlas page — retired the standalone
              `<AtlasToolbar>` that used to sit between the topbar and the
              chart (three segmented two-button toggles + a static
              "weighed by complexity" label). Each control here is now a
              SINGLE toggle button whose own label carries the current
              state, rather than a pair of always-both-visible tab buttons —
              `aria-pressed` still marks which state is active for screen
              readers. The static complexity-weight label is dropped
              entirely (informational only; the ★ weight still appears in
              every marker tooltip — EpicAtlas.tsx). */}
          {view === "atlas" && (
            <div className="topbar__atlas-controls">
              <Button
                className="topbar__atlas-control"
                aria-pressed={showNames}
                onClick={() => onToggleNames(!showNames)}
                title="Toggle quest name-tags on the trail"
              >
                {/* rpg-icons pack "sealed letter" — a scroll of quest names */}
                <img src={scrollIcon} alt="" className="topbar__atlas-control-icon" />
                {showNames ? "Quest names: On" : "Quest names: Off"}
              </Button>
              <Button
                className="topbar__atlas-control"
                aria-pressed={!hideVanquished}
                onClick={() => onToggleVanquished(!hideVanquished)}
                title="Toggle vanquished (done) epics"
              >
                {/* rpg-icons pack "skull-crossbones" — the vanquished mark */}
                <img src={skullIcon} alt="" className="topbar__atlas-control-icon" />
                {hideVanquished ? "Vanquished: Hidden" : "Vanquished: Shown"}
              </Button>
            </div>
          )}

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
            <Button
              variant="neutral"
              // Task 10: shares the "＋ New card" control's Role-A button paint
              // (non-destructive positive action, same wobble shape) — see
              // `.topbar__new-card` in styles.css, reused here rather than
              // duplicated.
              className="topbar__new-card topbar__labels-settings"
              onClick={() => setLabelSettingsOpen(true)}
              title="Edit label colors"
            >
              Labels…
            </Button>

            <Button
              className="topbar__refresh"
              onClick={onRefresh}
              disabled={refreshing}
            >
              {refreshing ? "Refreshing…" : "Refresh"}
            </Button>

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
                Abandoned) rather than leading them. `.topbar-clear` gets an
                explicit `order: 1` reset scoped to `.topbar__controls-group`
                on mobile (see styles.css) rather than relying on DOM order
                alone. */}
            {onClear && (
              <Button
                className="topbar-clear danger"
                onClick={onClear}
                title="Clear this repo's data"
              >
                Clear…
              </Button>
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
            {idleCount > 0 && <> ({idleCount} idle)</>}
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
