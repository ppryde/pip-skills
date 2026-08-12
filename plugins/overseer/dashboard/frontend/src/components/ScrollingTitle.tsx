import { useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";

export interface ScrollingTitleProps {
  text: string;
  /** Classes for the outer element — e.g. the card's own title class, so the
   * font/colour styling is unchanged. */
  className?: string;
}

/**
 * A single-line title that MARQUEE-scrolls its text back and forth when it's
 * too wide to fit, instead of ellipsising it (mobile condensed rail cards).
 *
 * Measures the inner span's `scrollWidth` against the clipping outer's
 * `clientWidth`; on overflow it exposes the overflow distance (`--marquee-dist`)
 * + a paced duration (`--marquee-dur`) as CSS vars and flags `--marquee`, and
 * styles.css does the animation. The nowrap/clip/animation are all gated to
 * mobile in CSS, so on desktop (where the title wraps to multiple lines) there
 * is no overflow, `dist` stays 0, and nothing scrolls.
 */
function ScrollingTitle({ text, className }: ScrollingTitleProps) {
  const outerRef = useRef<HTMLDivElement>(null);
  const innerRef = useRef<HTMLSpanElement>(null);
  const [dist, setDist] = useState(0);

  useLayoutEffect(() => {
    const outer = outerRef.current;
    const inner = innerRef.current;
    if (!outer || !inner) return;
    const measure = () => {
      const overflow = inner.scrollWidth - outer.clientWidth;
      // Small slop so a 1-2px sub-pixel overshoot doesn't trigger a marquee.
      setDist(overflow > 2 ? overflow : 0);
    };
    measure();
    // jsdom (component tests) has no ResizeObserver — the one-shot measure
    // above is enough there; bail rather than crash.
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(outer);
    return () => ro.disconnect();
  }, [text]);

  const style: CSSProperties | undefined =
    dist > 0
      ? ({
          ["--marquee-dist" as string]: `${dist}px`,
          // ~55px/s of travel plus fixed end-pauses, so long titles don't whip
          // past too fast and short ones don't crawl.
          ["--marquee-dur" as string]: `${Math.round(dist / 55 + 4)}s`,
        } as CSSProperties)
      : undefined;

  return (
    <div
      ref={outerRef}
      className={
        "marquee-title" +
        (dist > 0 ? " marquee-title--marquee" : "") +
        (className ? ` ${className}` : "")
      }
      style={style}
    >
      <span ref={innerRef} className="marquee-title__inner">
        {text}
      </span>
    </div>
  );
}

export default ScrollingTitle;
