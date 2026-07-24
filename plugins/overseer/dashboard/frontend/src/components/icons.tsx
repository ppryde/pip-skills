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
