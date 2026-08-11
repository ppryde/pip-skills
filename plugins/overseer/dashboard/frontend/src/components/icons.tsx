import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

/**
 * Quest Board icon set (WF-028 chunk 1). Inline SVG, `currentColor` only —
 * no hex literals here (KB-007: styling lives in styles.css, not tsx).
 * Sized `1em` square by default so a consumer controls size via font-size,
 * or overrides `width`/`height` through the passed-through props.
 */

export function CoinIcon(props: IconProps) {
  return (
    <svg
      viewBox="0 0 16 16"
      width="1em"
      height="1em"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      aria-hidden="true"
      {...props}
    >
      <circle cx="8" cy="8" r="6.25" fill="currentColor" fillOpacity="0.25" />
      <circle cx="8" cy="8" r="6.25" />
      <path
        d="M8 5v6M6.25 6.5c0-.83.79-1.5 1.75-1.5s1.75.67 1.75 1.5c0 .83-.79 1.25-1.75 1.5-.96.25-1.75.67-1.75 1.5 0 .83.79 1.5 1.75 1.5s1.75-.67 1.75-1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

export interface StarIconProps extends IconProps {
  /** Filled (earned rarity pip) vs empty (unearned) — HANDOFF's rarity stars. */
  filled?: boolean;
}

export function StarIcon({ filled = true, ...rest }: StarIconProps) {
  return (
    <svg
      viewBox="0 0 16 16"
      width="1em"
      height="1em"
      fill={filled ? "currentColor" : "none"}
      stroke="currentColor"
      strokeWidth="1.25"
      aria-hidden="true"
      {...rest}
    >
      <path
        d="M8 1.5l1.9 3.85 4.25.62-3.08 3 .73 4.23L8 11.2l-3.8 2 .73-4.23-3.08-3 4.25-.62L8 1.5z"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function PadlockIcon(props: IconProps) {
  return (
    <svg
      viewBox="0 0 16 16"
      width="1em"
      height="1em"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      aria-hidden="true"
      {...props}
    >
      <rect x="3" y="7" width="10" height="7" rx="1.5" />
      <path d="M5.25 7V5a2.75 2.75 0 0 1 5.5 0v2" strokeLinecap="round" />
    </svg>
  );
}

/** Done-badge check-in-circle glyph (chunk 5). */
export function CheckIcon(props: IconProps) {
  return (
    <svg
      viewBox="0 0 16 16"
      width="1em"
      height="1em"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      aria-hidden="true"
      {...props}
    >
      <path d="M3.5 8.5l3 3 6-7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** Park/"Camp" glyph (WF-046 item 4) — a small tent, door-flap doubling as
 * the pause read: a card at rest pitches camp rather than marching on. */
export function TentIcon(props: IconProps) {
  return (
    <svg
      viewBox="0 0 16 16"
      width="1em"
      height="1em"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      aria-hidden="true"
      {...props}
    >
      <path d="M8 2 L14.25 13.5 H1.75 Z" strokeLinejoin="round" />
      <path d="M8 2 L6.25 13.5M8 2 L9.75 13.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** Block/"Barred" glyph (WF-046 item 4) — a shield with a bar across it,
 * echoing `PadlockIcon`'s stroke weight/viewBox for the same "held up"
 * read as the dependency lock badge. */
export function BarredShieldIcon(props: IconProps) {
  return (
    <svg
      viewBox="0 0 16 16"
      width="1em"
      height="1em"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      aria-hidden="true"
      {...props}
    >
      <path
        d="M8 1.75l5.25 1.75v4c0 3.5-2.25 5.5-5.25 6.75-3-1.25-5.25-3.25-5.25-6.75v-4L8 1.75z"
        strokeLinejoin="round"
      />
      <path d="M5 8h6" strokeLinecap="round" />
    </svg>
  );
}

/** Abandon/"Forsake" glyph (WF-046 item 4) — a small skull; the card's
 * quest is given up for dead, not merely paused. */
export function SkullIcon(props: IconProps) {
  return (
    <svg
      viewBox="0 0 16 16"
      width="1em"
      height="1em"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.3"
      aria-hidden="true"
      {...props}
    >
      <path
        d="M8 1.75c-2.76 0-5 2.06-5 4.85 0 1.66.8 2.9 1.75 3.7v1.7h1.35v-1.15h1.15v1.15h1.5v-1.15h1.15v1.15h1.35v-1.7c.95-.8 1.75-2.04 1.75-3.7 0-2.79-2.24-4.85-5-4.85z"
        strokeLinejoin="round"
      />
      <circle cx="5.9" cy="6.6" r="0.85" fill="currentColor" />
      <circle cx="10.1" cy="6.6" r="0.85" fill="currentColor" />
    </svg>
  );
}

/** Info/"lower-case i in a circle" glyph — `InfoTooltip`'s trigger. */
export function InfoIcon(props: IconProps) {
  return (
    <svg
      viewBox="0 0 16 16"
      width="1em"
      height="1em"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      aria-hidden="true"
      {...props}
    >
      <circle cx="8" cy="8" r="6.25" />
      <circle cx="8" cy="5" r="0.9" fill="currentColor" stroke="none" />
      <path d="M8 7.3v3.7" strokeLinecap="round" />
    </svg>
  );
}
