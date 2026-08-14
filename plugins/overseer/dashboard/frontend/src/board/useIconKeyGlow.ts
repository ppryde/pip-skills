import { useEffect, useRef, useState } from "react";
import type { BoardCard } from "../api/types";
import { cardIconKey } from "./laneIcons";

const GLOW_MS = 60_000;

/** Pure: ids present in `next` whose key differs from `prev` (a first-seen id,
 * absent from `prev`, is a baseline, NOT a change). */
export function changedIconKeys(
  prev: Map<string, string>,
  next: Map<string, string>,
): string[] {
  const out: string[] = [];
  for (const [id, key] of next) {
    const before = prev.get(id);
    if (before !== undefined && before !== key) out.push(id);
  }
  return out;
}

/** Ids whose cardIconKey changed within the last GLOW_MS, observed live across
 * board updates (polls/mutations feed new `cards` arrays). The first observation
 * is a baseline and never glows; a reload starts a fresh baseline. */
export function useIconKeyGlow(cards: BoardCard[]): Set<string> {
  const prevKeys = useRef<Map<string, string> | null>(null);
  const [glowUntil, setGlowUntil] = useState<Map<string, number>>(new Map());

  useEffect(() => {
    const nextKeys = new Map(cards.map((c) => [c.id, cardIconKey(c)]));
    const prev = prevKeys.current;
    prevKeys.current = nextKeys;
    if (prev === null) return; // baseline
    const changed = changedIconKeys(prev, nextKeys);
    if (changed.length === 0) return;
    const until = Date.now() + GLOW_MS;
    setGlowUntil((m) => {
      const nextMap = new Map(m);
      for (const id of changed) nextMap.set(id, until);
      return nextMap;
    });
  }, [cards]);

  useEffect(() => {
    if (glowUntil.size === 0) return;
    const soonest = Math.min(...glowUntil.values());
    const t = setTimeout(() => {
      setGlowUntil((m) => {
        const now = Date.now();
        const kept = new Map<string, number>();
        for (const [id, until] of m) if (until > now) kept.set(id, until);
        return kept;
      });
    }, Math.max(0, soonest - Date.now()));
    return () => clearTimeout(t);
  }, [glowUntil]);

  const now = Date.now();
  const active = new Set<string>();
  for (const [id, until] of glowUntil) if (until > now) active.add(id);
  return active;
}
