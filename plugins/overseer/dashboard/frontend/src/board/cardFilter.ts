import type { BoardCard } from "../api/types";

export interface FilterState {
  query: string;
  includeLabels: string[];
  excludeLabels: string[];
  priority: string | null;
  complexity: string | null;
  /** When true, only epic cards are shown (still subject to the other
   * facets/search). A hard gate — no parent/child expansion. */
  epicsOnly: boolean;
}

export const DEFAULT_FILTER: FilterState = {
  query: "",
  includeLabels: [],
  excludeLabels: ["future"],
  priority: null,
  complexity: null,
  epicsOnly: false,
};
// Frozen so nobody can mutate the shared instance in place (e.g.
// `DEFAULT_FILTER.includeLabels.push(...)`). Consumers that need a mutable
// copy (useCardFilter's `clear()`/`load()`) build one with `freshDefault()`
// rather than handing out this object or its arrays by reference.
Object.freeze(DEFAULT_FILTER);
Object.freeze(DEFAULT_FILTER.includeLabels);
Object.freeze(DEFAULT_FILTER.excludeLabels);

export function distinctLabels(cards: BoardCard[]): string[] {
  const set = new Set<string>();
  for (const c of cards) for (const l of c.labels) set.add(l);
  return [...set].sort();
}

function searchMatch(c: BoardCard, q: string): boolean {
  if (!q) return true;
  const n = q.toLowerCase();
  return (
    c.id.toLowerCase().includes(n) ||
    c.title.toLowerCase().includes(n) ||
    c.body.toLowerCase().includes(n)
  );
}

function passesFilters(c: BoardCard, s: FilterState): boolean {
  const labels = new Set(c.labels);
  if (s.excludeLabels.some((l) => labels.has(l))) return false;
  if (s.includeLabels.length > 0 && !s.includeLabels.some((l) => labels.has(l))) return false;
  if (s.priority !== null && c.priority !== s.priority) return false;
  if (s.complexity !== null && c.complexity !== s.complexity) return false;
  return true;
}

export function visibleCardIds(cards: BoardCard[], state: FilterState): Set<string> {
  const q = state.query.trim();

  // "Epics only" is a hard gate: only epic cards can be visible, still subject
  // to the other facets + search. No parent/child expansion (an epic stands
  // on its own; its children carry their epic reference on their own tiles).
  if (state.epicsOnly) {
    const epics = new Set<string>();
    for (const c of cards) {
      if (!c.is_epic) continue;
      if (!passesFilters(c, state)) continue;
      if (q && !searchMatch(c, q)) continue;
      epics.add(c.id);
    }
    return epics;
  }

  const out = new Set<string>();
  if (!q) {
    for (const c of cards) if (passesFilters(c, state)) out.add(c.id);
    return out;
  }
  // parent id -> has children?
  const hasChildren = new Set<string>();
  for (const c of cards) if (c.parent) hasChildren.add(c.parent);
  const isMatchedParent = (c: BoardCard) => searchMatch(c, q) && hasChildren.has(c.id);
  const matchedParentIds = new Set<string>();
  for (const c of cards) if (isMatchedParent(c)) matchedParentIds.add(c.id);

  for (const c of cards) {
    if (matchedParentIds.has(c.id)) out.add(c.id); // matched epic anchor
    else if (c.parent && matchedParentIds.has(c.parent)) out.add(c.id); // its children
    else if (searchMatch(c, q) && passesFilters(c, state)) out.add(c.id); // other direct matches, gated
  }
  return out;
}
