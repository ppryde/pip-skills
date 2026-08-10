import { useCallback, useEffect, useState } from "react";
import { DEFAULT_FILTER, type FilterState } from "./cardFilter";

const KEY = "overseer_board_filter";

function load(): FilterState {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return DEFAULT_FILTER;
    return { ...DEFAULT_FILTER, ...(JSON.parse(raw) as Partial<FilterState>) };
  } catch {
    return DEFAULT_FILTER;
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
  const clear = useCallback(() => setFilter(DEFAULT_FILTER), []);

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
