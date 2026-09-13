/**
 * The mark of the service a row came from.
 *
 * Inline SVG, not image assets: these are a dozen paths, they must take the
 * parchment theme's sizing, and the page is already code-split — pulling in
 * four PNGs to draw four glyphs would cost more than it saves.
 *
 * Decorative by default (`aria-hidden`): every icon sits beside the source
 * name in the same badge, so announcing it twice would only pad the row for
 * a screen-reader user. Pass `label` where the icon stands alone.
 */
export interface SourceIconProps {
  source: string;
  size?: number;
  /** Set only when the icon is NOT accompanied by its own visible text. */
  label?: string;
}

/** Slack's pinwheel, simplified to four rounded bars in the brand's four
 * colours — recognisable at 14px, where the true mark's eight shapes turn
 * to mush. */
function SlackMark({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" focusable="false">
      <rect x="9.6" y="1.5" width="4.8" height="12.2" rx="2.4" fill="#36C5F0" />
      <rect x="1.5" y="9.6" width="12.2" height="4.8" rx="2.4" fill="#2EB67D" />
      <rect x="9.6" y="10.3" width="4.8" height="12.2" rx="2.4" fill="#ECB22E" />
      <rect x="10.3" y="9.6" width="12.2" height="4.8" rx="2.4" fill="#E01E5A" />
    </svg>
  );
}

/** Linear's angled mark: the corner-to-corner strokes of its rounded square. */
function LinearMark({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" focusable="false">
      <rect width="24" height="24" rx="5" fill="#5E6AD2" />
      <g stroke="#fff" strokeWidth="1.7" strokeLinecap="round">
        <path d="M5 13.5 10.5 19" />
        <path d="M5 9 15 19" />
        <path d="M5.5 5.5 18.5 18.5" />
      </g>
    </svg>
  );
}

/** A plain envelope. Mail has no one vendor here — the adapter may be IMAP
 * against any provider — so a generic mark is the honest one. */
function MailMark({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" focusable="false">
      <rect x="2" y="4.5" width="20" height="15" rx="2.5"
            stroke="currentColor" strokeWidth="1.8" />
      <path d="M3 6.5 12 13l9-6.5" stroke="currentColor" strokeWidth="1.8"
            strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** Derived items are not FROM a service — the almoner computed them by
 * joining two. A pair of linked rings says "this came from the join". */
function DerivedMark({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" focusable="false">
      <circle cx="9" cy="12" r="5.2" stroke="currentColor" strokeWidth="1.8" />
      <circle cx="15" cy="12" r="5.2" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  );
}

/** An unconfigured or unknown source type still gets a mark, so the badge
 * never collapses to a different height than its neighbours. */
function UnknownMark({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" focusable="false">
      <circle cx="12" cy="12" r="8.5" stroke="currentColor" strokeWidth="1.8"
              strokeDasharray="3 2.5" />
    </svg>
  );
}

const MARKS: Record<string, (props: { size: number }) => JSX.Element> = {
  slack: SlackMark,
  linear: LinearMark,
  mail: MailMark,
  almoner: DerivedMark,
};

export default function SourceIcon({ source, size = 14, label }: SourceIconProps) {
  const Mark = MARKS[source] ?? UnknownMark;
  return (
    <span
      className="almoner__source-icon"
      data-source={source in MARKS ? source : "unknown"}
      aria-hidden={label ? undefined : true}
      role={label ? "img" : undefined}
      aria-label={label}
    >
      <Mark size={size} />
    </span>
  );
}
