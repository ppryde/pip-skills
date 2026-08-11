export type TrailOrientation = "across" | "down";

export interface AtlasToolbarProps {
  showNames: boolean;
  onToggleNames: (next: boolean) => void;
  hideVanquished: boolean;
  onToggleVanquished: (next: boolean) => void;
  orientation: TrailOrientation;
  onToggleOrientation: (next: TrailOrientation) => void;
}

/**
 * Epic Atlas toolbar (WF-086 v2, between the topbar and the chart) — three
 * segmented toggles plus a static label, per HANDOFF's "Toolbar" section:
 *
 * 1. A static "weighed by complexity" label — no toggle, complexity is the
 *    decided weight source (estimates rejected for erratic 10x spreads).
 * 2. Quest-names: hides the todo name-tags only (default ON) — tooltips
 *    and the AT HAND pennant are unaffected either way.
 * 3. Vanquished epics: hide (default) filters done epics out; shown, they
 *    sort last (EpicAtlas owns the actual sort/filter — this component
 *    only reports the toggle's state).
 * 4. Mobile trail orientation ("Across"/"Down") — SHIPPED IN PRODUCTION,
 *    effective only at <=720px (desktop always renders across; the CSS
 *    gate lives in styles.css, not here).
 *
 * Each toggle is a Role-B `role="tab"` segmented control (matches the
 * retired TODAY-era `.weight-toggle` pattern) — `aria-pressed` marks the
 * active side, and both buttons in a pair always render so a screen reader
 * user can discover the untaken option.
 */
function AtlasToolbar({
  showNames,
  onToggleNames,
  hideVanquished,
  onToggleVanquished,
  orientation,
  onToggleOrientation,
}: AtlasToolbarProps) {
  return (
    <div className="atlas-toolbar">
      <span className="atlas-toolbar__label">Trail segments weighed by complexity ★</span>

      <div className="atlas-toolbar__toggle" role="tablist" aria-label="Name the quests on the ahead trail">
        <button
          type="button"
          className="atlas-toolbar__toggle-btn"
          role="tab"
          aria-pressed={showNames}
          onClick={() => onToggleNames(true)}
        >
          ⚑ Name the quests
        </button>
        <button
          type="button"
          className="atlas-toolbar__toggle-btn"
          role="tab"
          aria-pressed={!showNames}
          onClick={() => onToggleNames(false)}
        >
          🤫 Hush
        </button>
      </div>

      <div className="atlas-toolbar__toggle" role="tablist" aria-label="Show or hide vanquished epics">
        <button
          type="button"
          className="atlas-toolbar__toggle-btn"
          role="tab"
          aria-pressed={!hideVanquished}
          onClick={() => onToggleVanquished(false)}
        >
          🏆 Show
        </button>
        <button
          type="button"
          className="atlas-toolbar__toggle-btn"
          role="tab"
          aria-pressed={hideVanquished}
          onClick={() => onToggleVanquished(true)}
        >
          🙈 Hide
        </button>
      </div>

      <div
        className="atlas-toolbar__toggle atlas-toolbar__toggle--orientation"
        role="tablist"
        aria-label="Trail orientation on mobile (only effective at 720px or narrower)"
      >
        <button
          type="button"
          className="atlas-toolbar__toggle-btn"
          role="tab"
          aria-pressed={orientation === "across"}
          onClick={() => onToggleOrientation("across")}
        >
          ⟶ Across
        </button>
        <button
          type="button"
          className="atlas-toolbar__toggle-btn"
          role="tab"
          aria-pressed={orientation === "down"}
          onClick={() => onToggleOrientation("down")}
        >
          ⟱ Down
        </button>
      </div>
    </div>
  );
}

export default AtlasToolbar;
