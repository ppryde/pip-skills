import { useCallback, useEffect, useState } from "react";
import { DEFAULT_FILTER, type FilterState } from "./cardFilter";

const KEY = "overseer_board_filter";

/** Fresh copy of `DEFAULT_FILTER`, including its own array instances — never
 * hand out the frozen shared object/arrays from `cardFilter.ts` directly. */
function freshDefault(): FilterState {
  return {
    ...DEFAULT_FILTER,
    includeLabels: [...DEFAULT_FILTER.includeLabels],
    excludeLabels: [...DEFAULT_FILTER.excludeLabels],
  };
}

function isStringArray(v: unknown): v is string[] {
  return Array.isArray(v) && v.every((x) => typeof x === "string");
}

/** Shape guard for a value parsed from localStorage: rejects anything whose
 * present fields don't look like `Partial<FilterState>`, so a corrupted or
 * stale-shape stored value can't silently merge bad data (e.g. a numeric
 * `query` that crashes `.trim()` downstream, or a non-string `priority`
 * that hides everything) into live filter state. */
function looksLikeFilter(v: unknown): v is Partial<FilterState> {
  if (typeof v !== "object" || v === null) return false;
  const o = v as Record<string, unknown>;
  if ("query" in o && typeof o.query !== "string") return false;
  if ("priority" in o && o.priority !== null && typeof o.priority !== "string") return false;
  if ("complexity" in o && o.complexity !== null && typeof o.complexity !== "string") return false;
  if ("includeLabels" in o && !isStringArray(o.includeLabels)) return false;
  if ("excludeLabels" in o && !isStringArray(o.excludeLabels)) return false;
  return true;
}

function load(): FilterState {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return freshDefault();
    const parsed: unknown = JSON.parse(raw);
    if (!looksLikeFilter(parsed)) return freshDefault();
    return { ...freshDefault(), ...parsed };
  } catch {
    return freshDefault();
  }
}

export function useCardFilter() {
  const [filter, setFilter] = useState<FilterState>(load);

  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify(filter));
    } catch {
      /* ignore persistence failures (e.g. storage disabled/full) */
    }
  }, [filter]);

  const setQuery = useCallback((query: string) => setFilter((f) => ({ ...f, query })), []);
  const setPriority = useCallback(
    (priority: string | null) => setFilter((f) => ({ ...f, priority })),
    [],
  );
  const setComplexity = useCallback(
    (complexity: string | null) => setFilter((f) => ({ ...f, complexity })),
    [],
  );
  const clear = useCallback(() => setFilter(freshDefault()), []);

  const cycleLabel = useCallback(
    (label: string) =>
      setFilter((f) => {
        const inc = new Set(f.includeLabels);
        const exc = new Set(f.excludeLabels);
        if (!inc.has(label) && !exc.has(label)) {
          inc.add(label); // neutral -> include
        } else if (inc.has(label)) {
          inc.delete(label);
          exc.add(label); // include -> exclude
        } else {
          exc.delete(label); // exclude -> neutral
        }
        return { ...f, includeLabels: [...inc], excludeLabels: [...exc] };
      }),
    [],
  );

  return { filter, setQuery, setPriority, setComplexity, clear, cycleLabel };
}
