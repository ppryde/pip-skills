import { laneIcon } from "../board/laneIcons";

export interface LaneIconNavLane {
  /** The lane's OWN key (`Lane.key` from board/layout.ts, e.g.
   * "stage:implementation") — round-trips straight back through `onJump`
   * and doubles as the `data-lane-key` Board.tsx scrolls to, so nav and
   * swipe-track never disagree about which pane an icon points at. */
  key: string;
  label: string;
  count: number;
  /** The icon/accent key (`laneIconKey(lane)`, e.g. "implementation") —
   * shared with `.lane__header--<accent>` / `.card-tile--accent-<accent>`
   * so the active pill's colour matches that lane's own banner. */
  accent: string;
}

export interface LaneIconNavProps {
  lanes: LaneIconNavLane[];
  activeKey: string;
  onJump: (key: string) => void;
}

/**
 * Mobile-only (≤720px, gated in styles.css) horizontal strip: one
 * hand-drawn wobble box (RPG icon + card count) per lane, evenly spaced
 * across the strip — including empty lanes, for completeness/even spacing.
 * An empty lane (`count === 0`) has no swipe pane to jump to (Board.tsx
 * reverted `.lane--empty` to a non-snapping sliver — see styles.css), so
 * its box renders `disabled`, faded, and with no `onJump` wired up: it's
 * there to show the lane exists and is empty, not to be tapped. Every
 * non-empty box stays a real tap target — full-strength icon, transparent/
 * parchment wobble box with an ink outline, accent-filled + lifted when
 * active (synced by Board.tsx from scroll position, or set directly on
 * tap).
 */
function LaneIconNav({ lanes, activeKey, onJump }: LaneIconNavProps) {
  return (
    <nav className="lane-icon-nav" aria-label="Lane navigator">
      {lanes.map((lane) => {
        const isActive = lane.key === activeKey;
        const isEmpty = lane.count === 0;
        const className = [
          "lane-icon-nav__item",
          `lane-icon-nav__item--${lane.accent}`,
          isActive ? "lane-icon-nav__item--active" : "",
          isEmpty ? "lane-icon-nav__item--empty" : "",
        ]
          .filter(Boolean)
          .join(" ");

        return (
          <button
            key={lane.key}
            type="button"
            className={className}
            aria-label={
              isEmpty
                ? `${lane.label}, ${lane.count} cards, empty`
                : `${lane.label}, ${lane.count} cards`
            }
            aria-current={isActive ? "true" : undefined}
            disabled={isEmpty}
            onClick={isEmpty ? undefined : () => onJump(lane.key)}
          >
            <img className="lane-icon-nav__icon" src={laneIcon(lane.accent)} alt="" />
            <span className="lane-icon-nav__count">{lane.count}</span>
          </button>
        );
      })}
    </nav>
  );
}

export default LaneIconNav;
