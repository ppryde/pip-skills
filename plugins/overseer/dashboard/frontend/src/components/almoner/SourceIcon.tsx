/**
 * The mark of the service a row came from.
 *
 * Brand marks are inline SVG: Slack's pinwheel and Linear's angled square are
 * a dozen paths each, they must take the parchment theme's sizing, and the
 * page is already code-split — shipping PNGs to draw them would cost more
 * than it saves.
 *
 * MAIL is the exception, and deliberately so. It has no vendor to be faithful
 * to — the adapter may be IMAP against any provider — so it is the one mark
 * free to wear the house style instead of a logo, and it does: the same
 * sealed letter the rest of the dashboard's icons are drawn in. A sealed
 * letter also says the thing the page is about, which an envelope outline
 * does not: something arrived and has not been opened.
 *
 * Decorative by default (`aria-hidden`): every icon sits beside the source
 * name in the same badge, so announcing it twice would only pad the row for
 * a screen-reader user. Pass `label` where the icon stands alone.
 */
import sealedLetter from "../../assets/ui-icons/sealed-letter.png";
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

/** The house sealed letter — see the note at the top on why mail, alone of
 * the sources, is drawn rather than branded. `alt=""` because the wrapper
 * below owns whatever this icon announces. */
function MailMark({ size }: { size: number }) {
  return <img src={sealedLetter} width={size} height={size} alt="" draggable={false} />;
}

/** Notion's mark: the ruled page and the angled stroke of its N, at the one
 * weight that survives 14px. Monochrome on purpose — it is the brand's own
 * treatment, and it keeps the badge legible on parchment and on ink alike. */
function NotionMark({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" focusable="false">
      <rect x="2.6" y="2.6" width="18.8" height="18.8" rx="3.2"
            stroke="currentColor" strokeWidth="1.8" />
      <g stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
        <path d="M8.4 16.4V8.1" />
        <path d="M8.4 8.1 15.6 16.4" />
        <path d="M15.6 16.4V8.1" />
      </g>
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
  notion: NotionMark,
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
