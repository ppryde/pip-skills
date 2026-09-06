/**
 * Counsel — token-efficiency insights derived from the Chronicle's summary.
 *
 * Each insight is a pure function from summary data to one figure, a verdict
 * word and a line of counsel, the same shape `cacheVerdict` gives the gauge.
 * Nothing here fetches or renders: the page (a window) and the drawer (one
 * session) can both feed it, and the orchestrate skill's handoff decision
 * could later read the same numbers.
 *
 * Every threshold below is advisory — a band that has looked reasonable on
 * real sessions, not a rule the data must obey. Keep them here, named, so
 * retuning is a one-line change with a comment, never a magic number in JSX.
 *
 * The levers draw on the Claude Code docs' own cost guidance (costs,
 * prompt-caching, sub-agents, model-config, context-window pages) as
 * researched Sept 2026 — see scratch notes "context-levers-research". Where a
 * lever depends on a version-specific behaviour the body says so.
 */
import type { ChronicleModel, ChronicleSession, ChronicleShape, ChronicleTotals } from "../../api/types";
import { formatPct, formatTokens, formatUsd, sessionName, shortModel } from "./format";

/** `info` is a figure with no band — worth knowing, not a judgement. */
export type Verdict = "good" | "mixed" | "poor" | "info" | "none";

/** One thing the reader could do about an insight. Phrased as an option,
 * never an order: the counsel line says what the figure means, these say
 * what levers exist, and the reader knows their own work better than we do.
 *
 * `from` is the mildest verdict at which the lever is worth showing. A
 * healthy reading lists only the one or two things that still pay off; the
 * full list appears as the verdict worsens, so the panel never nags someone
 * whose numbers are fine. */
export interface Resolution {
  title: string;
  body: string;
  from: "good" | "mixed" | "poor";
}

const SEVERITY: Record<Verdict, number> = { none: -1, info: 0, good: 0, mixed: 1, poor: 2 };

/** The levers that apply at this verdict — every one whose `from` is no
 * worse than the reading. `none` gets nothing: there is no reading. */
export function leversFor(all: Resolution[], verdict: Verdict): Resolution[] {
  const level = SEVERITY[verdict];
  if (level < 0) return [];
  return all.filter((r) => SEVERITY[r.from] <= level);
}

/** A verdict band plus the words that go with it. */
interface Band {
  verdict: Verdict;
  verdictWord: string;
  counsel: string;
}

/** Pick the band for `value` against two ascending thresholds: below `low`
 * is the first band, below `high` the second, else the third. Every banded
 * insight uses this so the boundary rule (exclusive at both edges) is one
 * rule, and a fourth band or an inclusive edge is one change. */
export function bandByThreshold(value: number, low: number, high: number, bands: [Band, Band, Band]): Band {
  return value < low ? bands[0] : value < high ? bands[1] : bands[2];
}

export interface InsightRow {
  label: string;
  value: string;
  /** This row's share of the whole, formatted ("42%"). */
  share?: string;
  detail?: string;
}

export interface Insight {
  id: string;
  title: string;
  /** The headline figure, already formatted ("292k / 1M", "$0.18"). */
  value: string;
  verdict: Verdict;
  /** The verdict in a word, so the reading never rests on styling alone. */
  verdictWord: string;
  /** One sentence: what the figure means and what to do about it. */
  counsel: string;
  /** Supporting figures behind the headline. */
  detail?: string;
  /** Optional breakdown (e.g. one row per model). */
  rows?: InsightRow[];
  /** Column headings for `rows`, when the values need naming ("avg / turn"). */
  rowHeadings?: { value: string; share?: string };
  /** Things true of THIS window that bear on the figure — the sessions that
   * drove it, caveats about what is counted. Shown only when expanded. */
  facts?: string[];
  /** Levers worth knowing about, shown only when the row is expanded. */
  resolutions?: Resolution[];
}

/** Everything an insight may draw on. `sessions` is the page's session list
 * for the same window and scope; facts are mined from it. */
export interface InsightInputs {
  totals: ChronicleTotals;
  models: ChronicleModel[];
  shape: ChronicleShape | null;
  sessions: ChronicleSession[];
}

function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

/* --- window fill ------------------------------------------------------------ */

/** How full the context window is on a typical turn: average context per
 * call against the inferred window. Below LEAN the window is being kept
 * tight; above HEAVY the same large window is being re-sent turn after turn
 * and a clear or a handoff would have been cheaper. The bands sit where the
 * counsel does — "hand off at about half". */
export const FILL_LEAN = 0.25;
export const FILL_HEAVY = 0.5;

const FILL_RESOLUTIONS: Resolution[] = [
  {
    title: "Clear between tasks",
    body: "Stale history rides along on every turn, even a one-line question. /clear costs nothing and the old session stays there to /resume by name; a /compact is itself a large request.",
    from: "good",
  },
  {
    title: "Read narrower",
    body: "A Grep to find the lines, then a Read with an offset and limit, brings in a fraction of what a whole-file Read does — and whatever comes in stays in the window for every turn after.",
    from: "mixed",
  },
  {
    title: "Send the sweep to a subagent, on a cheaper model",
    body: "A subagent reads in its own window and hands back a paragraph. Since Claude Code 2.1.198 the Explore agent inherits your main model, so set CLAUDE_CODE_SUBAGENT_MODEL if the sweep should also be cheap.",
    from: "mixed",
  },
  {
    title: "Ask side questions with /btw",
    body: "A quick \"what does this do?\" normally becomes permanent context that every later turn pays to re-read. /btw answers without adding to the history.",
    from: "poor",
  },
  {
    title: "Hand off, then start fresh",
    body: "Two compactions in, a handoff note and a new session beats summarising summaries. To abandon a dead end, /rewind lands on an already-cached prefix; /compact pays to summarise what you are discarding.",
    from: "poor",
  },
];

/** Tokens read for every token written, in lowest terms: "181 : 1". Context
 * always outweighs output in agentic work, so the right-hand side is 1; if
 * it ever didn't, the ratio flips to "1 : N" rather than showing a fraction. */
export function readWriteRatio(read: number, written: number): string {
  if (read <= 0 || written <= 0) return "—";
  return read >= written ? `${Math.round(read / written)} : 1` : `1 : ${Math.round(written / read)}`;
}

export function windowFill({ totals: t, sessions }: InsightInputs): Insight {
  const context = t.input_tokens + t.cache_read_tokens + t.cache_creation_tokens;
  const base = { id: "window-fill", title: "Read-to-write ratio" };
  if (t.turns <= 0 || t.output_tokens <= 0) {
    return { ...base, value: "—", verdict: "none", verdictWord: "no data", counsel: "Nothing written in this window yet." };
  }
  const perTurn = context / t.turns;
  const window = t.context_window > 0 ? t.context_window : null;
  const fill = window === null ? null : perTurn / window;
  // Headline: the ratio. Band: the window fill behind it, because a ratio
  // has no natural ceiling and the fill has one the reader already knows —
  // the detail line ties the two together.
  const value = readWriteRatio(context, t.output_tokens);
  // Both sides of the ratio, per turn, so the headline is derivable from
  // the detail — then the same context against the window, which is what
  // the band judges. formatTokens leaves sub-1k values as-is, so round the
  // written figure ourselves.
  const perTurnWritten = Math.round(t.output_tokens / t.turns);
  const detail = [
    `a typical turn read ${formatTokens(perTurn)} and wrote ${formatTokens(perTurnWritten)}`,
    fill === null ? null : `that read is ${formatPct(fill)} of the ${formatTokens(window as number)} window`,
  ]
    .filter(Boolean)
    .join("; ");

  const half = sessions.filter((s) => (s.peak_context_pct ?? 0) >= 0.5);
  const largest = sessions.reduce<ChronicleSession | null>(
    (best, s) => (best === null || (s.peak_context_pct ?? 0) > (best.peak_context_pct ?? 0) ? s : best),
    null
  );
  const compacted = sessions.filter((s) => s.compactions > 0).length;
  const facts: string[] = [];
  if (sessions.length > 0) {
    facts.push(
      half.length === 0
        ? `No session pushed past half the window.`
        : `${half.length} of ${plural(sessions.length, "session")} pushed past half the window.`
    );
  }
  if (largest && (largest.peak_context_pct ?? 0) > 0) {
    facts.push(`Largest: ${sessionName(largest)} reached ${formatPct(largest.peak_context_pct)} over ${plural(largest.turns, "turn")}.`);
  }
  if (compacted > 0) facts.push(`${plural(compacted, "session")} compacted, ${plural(t.compactions, "compaction")} in all.`);
  if (t.subagents > 0) facts.push(`${plural(t.subagents, "subagent")} ran in this window; their turns are counted here too.`);

  // An unknown window cannot be banded; it reads as lean rather than as a
  // judgement it has no basis for.
  const banded = bandByThreshold(fill ?? 0, FILL_LEAN, FILL_HEAVY, [
    {
      verdict: "good",
      verdictWord: "lean",
      counsel: "Typical turns carry a quarter of the window or less; keep clearing between tasks and they will stay that way.",
    },
    {
      verdict: "mixed",
      verdictWord: "typical",
      counsel: "Turns carry a fair share of the window; the long sessions are where it adds up.",
    },
    {
      verdict: "poor",
      verdictWord: "heavy",
      counsel: "A typical turn is re-sending more than half the window. Clear or hand off sooner, and read narrower ranges.",
    },
  ]);
  return { ...base, value, detail, facts, ...banded, resolutions: leversFor(FILL_RESOLUTIONS, banded.verdict) };
}

/* --- cost per turn by model ------------------------------------------------ */

/** When the priciest model's turn costs at least this many times the
 * cheapest's, AND it is doing most of the turns, the counsel is to route
 * routine work down a tier. */
export const MODEL_SPREAD_NOTABLE = 3;

const MODEL_RESOLUTIONS: Resolution[] = [
  {
    title: "Pin the subagent model",
    body: "Since Claude Code 2.1.198 the Explore agent runs on your main model, not Haiku. CLAUDE_CODE_SUBAGENT_MODEL, or a model line in the agent file, keeps a sweep of the codebase off the top-tier price.",
    from: "good",
  },
  {
    title: "Compare per repo",
    body: "The mix can be right overall and wrong in one repo. The 'This repo' scope in Filters recomputes this table for the active root alone.",
    from: "mixed",
  },
  {
    title: "Use Sonnet for the routine turns",
    body: "Most edits, tests and refactors come out the same on a cheaper model. Set the default to Sonnet and step up with /model only for the hard reasoning — the docs trace most surprise bills to Opus left as the default.",
    from: "poor",
  },
  {
    title: "Pick model and effort before you start",
    body: "Changing model, effort or MCP servers mid-session throws away the prompt cache and re-reads the whole conversation at write rate. Set them up front, or change them right after a /clear.",
    from: "poor",
  },
];

interface ModelRate {
  model: string;
  turns: number;
  perTurn: number;
}

export function costPerTurnByModel({ models, totals: t, sessions }: InsightInputs): Insight {
  const priced: ModelRate[] = models
    .filter((m): m is ChronicleModel & { cost_usd: number } => m.cost_usd !== null && m.turns > 0)
    .map((m) => ({ model: m.model, turns: m.turns, perTurn: m.cost_usd / m.turns }))
    .sort((a, b) => b.perTurn - a.perTurn);
  // The headline is the blended average across every priced turn; each row
  // is that model's own average per turn beside its share of all turns
  // (unpriced models count in the denominator — they were turns too).
  const base = {
    id: "cost-per-turn",
    title: "Average cost per turn by model",
    rowHeadings: { value: "avg / turn", share: "of turns" },
  };
  if (priced.length === 0) {
    return { ...base, value: "—", verdict: "none", verdictWord: "no data", counsel: "No priced turns in this window." };
  }
  const allTurns = models.reduce((n, m) => n + m.turns, 0);
  const rows: InsightRow[] = priced.map((m) => ({
    label: shortModel(m.model),
    value: formatUsd(m.perTurn),
    share: `${Math.round((m.turns / allTurns) * 100)}%`,
    detail: `${m.model} · ${formatTokens(m.turns)} turns · ${formatUsd(m.perTurn * m.turns)} in all`,
  }));
  const totalTurns = priced.reduce((n, m) => n + m.turns, 0);
  const blended = priced.reduce((usd, m) => usd + m.perTurn * m.turns, 0) / totalTurns;
  const value = formatUsd(blended);
  const detailBase = `blended average over ${formatTokens(totalTurns)} priced turns`;

  const dearestSession = sessions.reduce<ChronicleSession | null>(
    (best, s) => (best === null || s.cost_usd > best.cost_usd ? s : best),
    null
  );
  const facts: string[] = [];
  if (dearestSession && dearestSession.cost_usd > 0) {
    facts.push(
      `Dearest session: ${sessionName(dearestSession)} at ${formatUsd(dearestSession.cost_usd)} over ${plural(dearestSession.turns, "turn")}.`
    );
  }
  if (t.unpriced_turns > 0) {
    facts.push(`${plural(t.unpriced_turns, "turn")} ran on models the price table does not know; they cost something, but not here.`);
  }
  facts.push("Subagent turns are priced in — they cost the same money as the main agent's.");

  if (priced.length === 1) {
    // A reading with nothing to compare against — no band, but the one
    // always-useful lever still applies to a single-model window.
    return {
      ...base,
      value,
      verdict: "none",
      verdictWord: "one model",
      counsel: "Only one model in this window; nothing to compare against.",
      detail: detailBase,
      rows,
      facts,
      resolutions: leversFor(MODEL_RESOLUTIONS, "good"),
    };
  }
  const dearest = priced[0];
  const cheapest = priced[priced.length - 1];
  const spread = cheapest.perTurn > 0 ? dearest.perTurn / cheapest.perTurn : Infinity;
  const dearestShare = dearest.turns / totalTurns;
  const detail = `${detailBase}; a ${shortModel(dearest.model)} turn costs ${
    Number.isFinite(spread) ? `${spread.toFixed(1)}× a` : "far more than a"
  } ${shortModel(cheapest.model)} turn`;
  const banded =
    spread >= MODEL_SPREAD_NOTABLE && dearestShare > 0.5
      ? {
          verdict: "poor" as const,
          verdictWord: "top-heavy",
          counsel: `Most turns ran on the dearest model. Route routine reads, edits and test runs to ${shortModel(cheapest.model)}.`,
        }
      : spread >= MODEL_SPREAD_NOTABLE
        ? {
            verdict: "good" as const,
            verdictWord: "tiered",
            counsel: "The expensive model is doing a minority of the turns; the mix is working for you.",
          }
        : {
            verdict: "mixed" as const,
            verdictWord: "flat",
            counsel: "The models in play cost about the same per turn, so model choice is not the lever here.",
          };
  return { ...base, value, detail, rows, facts, ...banded, resolutions: leversFor(MODEL_RESOLUTIONS, banded.verdict) };
}

/* --- cost per prompt -------------------------------------------------------- */

const PROMPT_RESOLUTIONS: Resolution[] = [
  {
    title: "Bundle related asks into one prompt",
    body: "Each message re-reads the whole conversation, so five one-liners cost five re-reads. One well-scoped prompt — or a claude -p one-shot for a standalone job — is cheaper.",
    from: "good",
  },
  {
    title: "Watch the per-session figure",
    body: "A cheap prompt in an expensive session is still an expensive session. The session shape table below shows where the median and the outliers sit.",
    from: "mixed",
  },
];

/** What a unit of your own work costs. Turns vary with how agentic a session
 * is; prompts are the thing you actually did, so this is the figure that
 * stays comparable across weeks. Informational — there is no right number,
 * so only the always-useful lever is offered. */
export function costPerPrompt({ totals: t, shape }: InsightInputs): Insight {
  const base = { id: "cost-per-prompt", title: "Cost per prompt" };
  if (t.prompts <= 0 || t.cost_usd <= 0) {
    return { ...base, value: "—", verdict: "none", verdictWord: "no data", counsel: "No priced prompts in this window." };
  }
  const perPrompt = t.cost_usd / t.prompts;
  const perSession = t.sessions > 0 ? t.cost_usd / t.sessions : null;
  const turnsPerPrompt = t.turns / t.prompts;
  const facts: string[] = [];
  if (shape && shape.cost_usd.p50 !== null && shape.cost_usd.max !== null) {
    facts.push(`Median session ${formatUsd(shape.cost_usd.p50)}; the dearest ${formatUsd(shape.cost_usd.max)}.`);
  }
  if (t.sessions > 0) {
    facts.push(`About ${Math.round(t.prompts / t.sessions)} prompts per session across ${plural(t.sessions, "session")}.`);
  }
  facts.push("Prompts are the main agent's only; the turns they spawned include subagents.");
  return {
    ...base,
    value: formatUsd(perPrompt),
    verdict: "info",
    verdictWord: "per prompt",
    counsel: `Each thing you asked for cost about ${formatUsd(perPrompt)} at list prices and ran ${Math.round(turnsPerPrompt)} turns.`,
    detail: perSession === null ? undefined : `${formatUsd(perSession)} per session · ${formatUsd(t.cost_usd)} in all`,
    facts,
    resolutions: leversFor(PROMPT_RESOLUTIONS, "info"),
  };
}

/* --- thinking share --------------------------------------------------------- */

/** Thinking is billed as output. Below LIGHT the model is mostly acting;
 * above DEEP more than half of what you pay for is deliberation. */
export const THINKING_LIGHT = 0.25;
export const THINKING_DEEP = 0.5;

const THINKING_RESOLUTIONS: Resolution[] = [
  {
    title: "Keep it where it earns its keep",
    body: "Design, review and the hard debugging are where deliberation changes the answer. A high share is not a fault if that is what the window was.",
    from: "good",
  },
  {
    title: "Drop effort for the simple stuff",
    body: "Thinking tokens are output tokens. /effort low for renames and test runs, back up for design — and set it at session start, since changing it mid-session invalidates the cache on every model but Fable 5.1.",
    from: "mixed",
  },
  {
    title: "Plan the big ones, skip it for the small",
    body: "Plan mode prevents costly wrong turns on multi-file work but is pure overhead on a fix you could describe in one sentence.",
    from: "poor",
  },
];

export function thinkingShare({ totals: t, sessions }: InsightInputs): Insight {
  const base = { id: "thinking-share", title: "Thinking share of output" };
  if (t.output_tokens <= 0) {
    return { ...base, value: "—", verdict: "none", verdictWord: "no data", counsel: "Nothing written in this window yet." };
  }
  const share = t.thinking_tokens / t.output_tokens;
  const value = `${Math.round(share * 100)}%`;
  const detail = `${formatTokens(t.thinking_tokens)} thinking of ${formatTokens(t.output_tokens)} written, billed at output rates`;
  const deepSessions = sessions.filter((s) => s.output_tokens > 0 && s.thinking_tokens / s.output_tokens >= THINKING_DEEP);
  const deepest = sessions.reduce<ChronicleSession | null>((best, s) => {
    if (s.output_tokens <= 0) return best;
    const r = s.thinking_tokens / s.output_tokens;
    return best === null || r > best.thinking_tokens / Math.max(1, best.output_tokens) ? s : best;
  }, null);
  const facts: string[] = [];
  if (sessions.length > 0) {
    facts.push(
      deepSessions.length === 0
        ? "No session spent more than half its output thinking."
        : `${deepSessions.length} of ${plural(sessions.length, "session")} spent more than half their output thinking.`
    );
  }
  if (deepest && deepest.output_tokens > 0) {
    facts.push(`Deepest: ${sessionName(deepest)} at ${formatPct(deepest.thinking_tokens / deepest.output_tokens)}.`);
  }
  const banded = bandByThreshold(share, THINKING_LIGHT, THINKING_DEEP, [
    {
      verdict: "good",
      verdictWord: "light",
      counsel: "Most of the output is the work itself; thinking is a small part of what you pay for.",
    },
    {
      verdict: "mixed",
      verdictWord: "balanced",
      counsel: "A fair share of the output is deliberation, which is what design and review work looks like.",
    },
    {
      verdict: "poor",
      verdictWord: "deep",
      counsel: "More than half of what you pay for as output is thinking. Worth checking that routine turns are not running at high effort.",
    },
  ]);
  return { ...base, value, detail, facts, ...banded, resolutions: leversFor(THINKING_RESOLUTIONS, banded.verdict) };
}

/** The page's counsel, in display order. */
export function windowInsights(inputs: InsightInputs): Insight[] {
  return [windowFill(inputs), costPerTurnByModel(inputs), costPerPrompt(inputs), thinkingShare(inputs)];
}
