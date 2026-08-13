import { createElement, forwardRef } from "react";
import type { HTMLAttributes } from "react";

/** Elements `<Label>` knows how to render as — `span` (default, the plain
 * eyebrow/field-label case) or `h3` (CardDetailDrawer's section headings,
 * WF-097 follow-up below). Kept a closed union rather than a fully generic
 * `ElementType` prop: this component has exactly one reason to change tag
 * (real heading semantics for a11y), not an open-ended polymorphic-component
 * need, so the narrower type is the thinner change. */
export type LabelElement = "span" | "h3";

export type LabelProps = HTMLAttributes<HTMLElement> & {
  /** Render as this element instead of the default `<span>` — same
   * `.qb-label` look, different tag/semantics. `<h3>` is for a real
   * heading that must still read as the small uppercase eyebrow. */
  as?: LabelElement;
};

/**
 * Design-library Label (v1) — a thin typed wrapper around the shared
 * `.qb-label` uppercase eyebrow/field-label recipe (styles.css "Design
 * library" section, factored from `.topbar__repo-select-label` /
 * `.filter-bar__eyebrow`). Forwards every native prop untouched;
 * `className` composes with `.qb-label` rather than replacing it.
 *
 * WF-097 follow-up (card-drawer label standardisation): gained the `as`
 * prop so CardDetailDrawer's `.card-drawer__section-heading` `<h3>`s can
 * route through this SAME component — `.qb-label`'s look with real heading
 * semantics preserved, rather than either dropping the heading tag or
 * hand-duplicating the recipe's values onto a separate CSS rule.
 *
 * Built with `createElement` rather than JSX for the dynamic tag: JSX's
 * `<Component ref={ref} .../>` can't type-check a `ref` typed as the
 * union `HTMLElement` against per-element ref types (`LegacyRef<
 * HTMLHeadingElement>` for `h3` vs. `HTMLSpanElement` for `span`) — the two
 * possible elements this ever renders share the whole `HTMLAttributes`
 * surface used here, so the loosened typing costs nothing in practice.
 */
const Label = forwardRef<HTMLElement, LabelProps>(function Label(
  { className, as = "span", ...rest },
  ref
) {
  const classes = ["qb-label", className].filter(Boolean).join(" ");
  return createElement(as, { ref, className: classes, ...rest });
});

export default Label;
