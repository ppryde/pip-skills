import type { BoardCard } from "../api/types";

export interface FilterState {
  query: string;
  includeLabels: string[];
  excludeLabels: string[];
  priority: string | null;
  complexity: string | null;
}

export const DEFAULT_FILTER: FilterState = {
  query: "",
  includeLabels: [],
  excludeLabels: ["future"],
  priority: null,
  complexity: null,
};

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
