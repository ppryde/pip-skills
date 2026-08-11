/**
 * Doodle boss face for a campaign trail's end (Epic Atlas, WF-086) — same
 * face family as the Boss Ledger exploration. Purely presentational:
 * geometry ported from the design reference's `beastFace()` (`docs/design/
 * epic-atlas/Epic Atlas — Campaign Trails.html`), with `hue`/`horns`/`slain`
 * as the only inputs. The outline colour is `var(--qb-beast-ink)` rather
 * than the reference's literal `#2c2015` — that token is declared in
 * `styles.css` by a later chunk; this component only ever references it.
 */

export interface BeastFaceProps {
  /** Fill for the ellipse (and horns, when present) — the epic's accent
   * hue, darker while alive, the epic's own accent fill once slain. */
  hue: string;
  horns: boolean;
  /** True once the epic is done — swaps dot-eyes/grumpy-mouth-and-teeth
   * for X-eyes/smile. */
  slain: boolean;
}

function BeastFace({ hue, horns, slain }: BeastFaceProps) {
  return (
    <svg
      className="beast-face"
      viewBox="0 0 50 50"
      width="48"
      height="48"
      aria-hidden="true"
    >
      {horns ? (
        <>
          <path
            className="beast-face__horn"
            d="M12 12 q-5 -7 -2 -10 q5 2 7 8 Z"
            fill={hue}
            stroke="var(--qb-beast-ink)"
            strokeWidth="1.6"
          />
          <path
            className="beast-face__horn"
            d="M38 12 q5 -7 2 -10 q-5 2 -7 8 Z"
            fill={hue}
            stroke="var(--qb-beast-ink)"
            strokeWidth="1.6"
          />
        </>
      ) : (
        <path
          className="beast-face__brow"
          d="M14 10 q3 -6 8 -5 M36 10 q-3 -6 -8 -5"
          stroke="var(--qb-beast-ink)"
          strokeWidth="1.8"
          fill="none"
          strokeLinecap="round"
        />
      )}

      <ellipse
        cx="25"
        cy="25"
        rx="16.5"
        ry="15.5"
        fill={hue}
        stroke="var(--qb-beast-ink)"
        strokeWidth="2"
        transform="rotate(-3 25 25)"
      />

      {slain ? (
        <>
          <path
            className="beast-face__eye beast-face__eye--x"
            d="M17 20 l5 5 M22 20 l-5 5"
            stroke="#f6ead2"
            strokeWidth="2.4"
            strokeLinecap="round"
          />
          <path
            className="beast-face__eye beast-face__eye--x"
            d="M28 20 l5 5 M33 20 l-5 5"
            stroke="#f6ead2"
            strokeWidth="2.4"
            strokeLinecap="round"
          />
        </>
      ) : (
        <>
          <circle className="beast-face__eye beast-face__eye--dot" cx="19" cy="22" r="2.6" fill="#f6ead2" />
          <circle className="beast-face__eye beast-face__eye--dot" cx="31" cy="22" r="2.6" fill="#f6ead2" />
        </>
      )}

      {slain ? (
        <path
          className="beast-face__mouth beast-face__mouth--smile"
          d="M19 33 q6 -4 12 0"
          stroke="#f6ead2"
          strokeWidth="2.2"
          fill="none"
          strokeLinecap="round"
        />
      ) : (
        <>
          <path
            className="beast-face__mouth beast-face__mouth--grumpy"
            d="M19 32 q6 4 12 0"
            stroke="#f6ead2"
            strokeWidth="2.2"
            fill="none"
            strokeLinecap="round"
          />
          <path
            className="beast-face__tooth"
            d="M22 33.5 l0 3"
            stroke="#f6ead2"
            strokeWidth="2"
            strokeLinecap="round"
          />
          <path
            className="beast-face__tooth"
            d="M28 33.5 l0 3"
            stroke="#f6ead2"
            strokeWidth="2"
            strokeLinecap="round"
          />
        </>
      )}
    </svg>
  );
}

export default BeastFace;
