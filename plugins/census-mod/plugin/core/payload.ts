import { SCHEMA } from './name'
import { expiresAtMs, isWarm, sessionRatio, totalInputTokens } from './cache'
import type { RateLimit, Snap } from './types'

export type Event =
  | 'session.start' | 'session.clear' | 'session.resume' | 'session.fork' | 'turn.complete'
  | 'rate-limit' | 'model' | 'cwd' | 'branch' | 'pr' | 'cache.cold' | 'compact' | 'session.end'

/** `claude-opus-5-5[1m]` -> `{ id: 'claude-opus-5-5', display_name: 'Opus 5.5' }`. */
export function modelOf(raw: string): { id: string; display_name: string } {
  const id = raw.replace(/\[[^\]]*\]$/, '')
  const m = /^claude-(opus|sonnet|haiku|fable)-(\d+)-(\d+)/.exec(id)
  const name = m ? `${(m[1] ?? '').charAt(0).toUpperCase()}${(m[1] ?? '').slice(1)} ${m[2]}.${m[3]}` : id
  return { id, display_name: name }
}

/** ISO `resetsAt` and decimal `percentUsed` to census's windows: epoch SECONDS, or census drops it. */
export function rateLimitsOf(limits: RateLimit[]): Record<string, { used_percentage: number; resets_at: number }> {
  const out: Record<string, { used_percentage: number; resets_at: number }> = {}
  for (const l of limits) {
    const ms = l.resetsAt ? Date.parse(l.resetsAt) : Number.NaN
    if (!Number.isFinite(ms) || !Number.isFinite(l.percentUsed)) continue
    out[l.kind] = { used_percentage: l.percentUsed, resets_at: Math.floor(ms / 1000) }
  }
  return out
}

/**
 * The status-line payload shape census reads, plus `census_mod`. `now` in ms. Keys census does not
 * know are stored verbatim, so every extra here is free; a key this cannot fill is OMITTED, not
 * faked (census keeps the prior value of a null, and drops a half-formed window).
 */
export function buildPayload(s: Snap, now: number, event: Event, ended?: string): Record<string, unknown> {
  const c = s.counters
  const expires = expiresAtMs(c, s.ttl)
  const cache: Record<string, unknown> = {
    warm: isWarm(c, s.ttl, now),
    ttl: s.ttl,
    requests: c.requests,
  }
  if (expires !== null) cache.expires_at = Math.floor(expires / 1000)
  if (c.lastRatio !== null) cache.hit_ratio = c.lastRatio
  const whole = sessionRatio(c)
  if (whole !== null) cache.session_hit_ratio = whole

  const p: Record<string, unknown> = { session_id: s.sessionId }
  if (s.transcriptPath) p.transcript_path = s.transcriptPath
  p.cwd = s.cwd
  // No project_dir: the mod tracks the current directory, not a project root, and would go stale after a cd.
  p.workspace = { current_dir: s.cwd }
  if (s.worktreePath) p.worktree = { path: s.worktreePath }
  if (s.model) p.model = s.model
  p.context_window = {
    used_percentage: s.ctxPct,
    ...(s.ctxWindow !== null ? { context_window_size: s.ctxWindow } : {}),
    total_input_tokens: totalInputTokens(c),
    total_output_tokens: c.output,
  }
  const cost: Record<string, number> = {}
  if (s.costUsd !== null) cost.total_cost_usd = s.costUsd
  if (s.startedAt !== null) cost.total_duration_ms = Math.max(0, Math.round(now - s.startedAt))
  p.cost = cost
  const limits = rateLimitsOf(s.rateLimits)
  if (Object.keys(limits).length) p.rate_limits = limits
  p.prompt_cache = cache
  if (s.sessionName) p.session_name = s.sessionName
  if (s.pr) p.pr = { number: s.pr.number, url: s.pr.url, ...(s.pr.reviewState ? { review_state: s.pr.reviewState } : {}) }
  if (s.version) p.version = s.version
  p.census_mod = {
    version: SCHEMA,
    ...(s.proc ? { pid: s.proc.pid, proc_start: s.proc.procStart } : {}),
    event,
    ...(ended !== undefined ? { ended } : {}),
    // The `-uno` git pass, in gitcache's field names, so readers never shell out to git themselves.
    git: s.git ? { branch: s.git.branch, uncommitted: s.git.uncommitted, ahead: s.git.ahead, has_upstream: s.git.hasUpstream, detached: s.git.detached } : null,
  }
  return p
}
