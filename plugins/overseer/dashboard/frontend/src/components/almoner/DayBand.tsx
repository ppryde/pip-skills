import type { DayBand as BandGeometry } from "../../board/almoner/band";
import { LANES } from "../../board/almoner/band";

/**
 * The day band — when things arrived, as a picture.
 *
 * The one element on the page that leaves the parchment. An instrument wants
 * a dark face, and this is an instrument: it is the page's single bold move,
 * which is why everything around it stays quiet.
 *
 * Deliberately NOT interactive yet. Sitting above a table it will invite
 * clicking, and the honest version scrubs the list below — but a control that
 * looks live and does nothing is worse than one that plainly does not, so
 * until that lands the blips are marked decorative.
 */
export interface DayBandProps {
  band: BandGeometry | null;
  /** The day this band covers, e.g. "Today · Saturday 13 September". */
  label: string;
}

/** How far a lane lifts a blip off the axis. The band is 58px tall, so four
 * lanes at 12px sit clear of both the axis and the top. */
const LANE_STEP_PX = 12;
const LANE_BASE_PX = 8;

export default function DayBand({ band, label }: DayBandProps) {
  // No band rather than an empty axis: a chart with nothing on it reads as
  // broken, not as a quiet day.
  if (band === null) return null;

  return (
    <div className="alm-band">
      <div className="alm-band__head">
        <span className="alm-band__day">{label}</span>
        <span className="alm-band__span">
          {band.hours[0]?.label} – {band.hours[band.hours.length - 1]?.label}
        </span>
      </div>

      <div className="alm-band__axis" aria-hidden="true">
        {band.hours.map((hour) => (
          <span key={hour.ms} className="alm-band__hour" style={{ left: `${hour.leftPct}%` }} />
        ))}
        {band.blips.map((blip) => (
          <span
            key={blip.id}
            className={`alm-band__blip alm-band__blip--${blip.source}${blip.open ? " is-open" : ""}`}
            style={{
              left: `${blip.leftPct}%`,
              bottom: `${LANE_BASE_PX + Math.min(blip.lane, LANES - 1) * LANE_STEP_PX}px`,
            }}
          />
        ))}
        {band.hours.map((hour, index) =>
          // Every other tick is labelled — a label per hour collides at the
          // widths this band actually gets.
          index % 2 === 0 ? (
            <span key={`l${hour.ms}`} className="alm-band__hourlab" style={{ left: `${hour.leftPct}%` }}>
              {hour.label}
            </span>
          ) : null
        )}
      </div>

      {/* The axis is `aria-hidden`; this is what a screen reader gets instead,
          because a scatter of positioned dots is meaningless read aloud. */}
      <p className="sr-only">
        {band.blips.length} arrivals between {band.hours[0]?.label} and{" "}
        {band.hours[band.hours.length - 1]?.label}, of which{" "}
        {band.blips.filter((blip) => blip.open).length} still need you.
      </p>

      <div className="alm-band__key">
        <span className="alm-band__k"><i className="alm-band__blip--slack" /> Slack</span>
        <span className="alm-band__k"><i className="alm-band__blip--linear" /> Linear</span>
        <span className="alm-band__k"><i className="alm-band__blip--almoner" /> derived</span>
        <span className="alm-band__k alm-band__k--end">ring = still needs you</span>
      </div>
    </div>
  );
}
