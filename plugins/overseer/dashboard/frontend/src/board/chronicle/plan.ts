/**
 * Display labels for the plan a session ran on (`plan_organization_type`).
 *
 * Chronicle snapshots the raw value from the account's config at ingest and
 * never interprets it; naming is a presentation concern and lives here.
 *
 * Unrecognised values are TIDIED, not dropped: a plan this build has never
 * heard of should still show something truthful rather than vanish, since the
 * set upstream can grow at any time. Only a missing value renders nothing.
 */
const KNOWN: Record<string, string> = {
  claude_max: "Max",
  claude_enterprise: "Enterprise",
  claude_team: "Team",
  claude_pro: "Pro",
  claude_free: "Free",
};

/** A short badge label, or null when the plan is unknown — in which case the
 * caller must render NOTHING, never "unknown". */
export function planLabel(plan: string | null | undefined): string | null {
  if (!plan) return null;
  const known = KNOWN[plan];
  if (known) return known;
  // e.g. "claude_something_new" -> "Something New"
  return plan
    .replace(/^claude[_-]/, "")
    .split(/[_-]+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ") || null;
}

/** The distinct plans present in a set of sessions, ordered by frequency then
 * name, so a filter offers the busiest first. Sessions with no plan are
 * excluded — there is no "unknown" option to choose. */
export function plansPresent(
  sessions: { plan_organization_type?: string | null }[]
): { plan: string; label: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const s of sessions) {
    const plan = s.plan_organization_type;
    if (plan) counts.set(plan, (counts.get(plan) ?? 0) + 1);
  }
  // Filter on the LABEL, not on the raw plan. A truthy value can still tidy
  // to nothing — "_", "-" and "claude_" all pass the `if (plan)` guard above
  // and come back null — and the old `as string` assertion carried that null
  // into `localeCompare`, taking down the whole Chronicle page rather than
  // dropping one badge.
  return [...counts.entries()]
    .map(([plan, count]) => ({ plan, label: planLabel(plan), count }))
    .filter((p): p is { plan: string; label: string; count: number } => p.label !== null)
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
}
