import { expect, test } from 'claude-code/testing'
import { CLI, START, USAGE, classicStart, turn, world } from './world'

const SEC = 1000
const MIN = 60 * SEC

test('a session start records one ingest through the census CLI named by the cli.path pointer', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await w.clock.advance(0)

  expect(w.ingests).toHaveLength(1)
  expect(w.ingests[0]?.argv).toEqual(['python3', CLI, 'ingest'])
  expect(w.ingests[0]?.env).toBeUndefined()
  expect(w.ingests[0]?.payload).toMatchObject({
    session_id: 's1',
    cwd: '/repo',
    model: { id: 'claude-opus-5-5', display_name: 'Opus 5.5' },
    context_window: { used_percentage: 9, context_window_size: 1_000_000 },
    cost: { total_cost_usd: 0.9, total_duration_ms: 600_000 },
    census_mod: { version: 1, pid: 22695, proc_start: 'Sun Oct  4 22:57:51 2026', event: 'session.start' },
    version: '2.1.289',
  })
})

test('a -p run records nothing', async ($, on) => {
  const w = world(on)
  await $.session.start({ ...START, isInteractive: false })
  await $.turn.complete(turn(USAGE))
  await w.clock.advance(10 * SEC)

  expect(w.ingests).toHaveLength(0)
})

test('classic SessionStart on startup after session.start is the same session: one ingest, not two', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.classic.SessionStart(classicStart('startup'))
  await w.clock.advance(0)

  expect(w.ingests).toHaveLength(1)
  expect((w.ingests[0]?.payload as { transcript_path?: string }).transcript_path).toBe('/cfg/projects/-repo/s1.jsonl')
})

test('a /clear ends the old session and registers the new one under its new id', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await w.clock.advance(0)
  await $.session.end({ reason: 'clear', sessionId: 's1', resume: {} as never })
  w.sessionId.value = 's2'
  await $.classic.SessionStart(classicStart('clear', 's2'))
  await w.clock.advance(2 * SEC)

  const last = w.ingests.at(-1)?.payload as { session_id: string; census_mod: { event: string } }
  const ended = w.ingests.find(i => i.payload.census_mod.ended !== undefined)?.payload
  expect(ended).toMatchObject({ session_id: 's1', census_mod: { event: 'session.end', ended: 'clear' } })
  expect(last).toMatchObject({ session_id: 's2', census_mod: { event: 'session.clear' } })
})

test('every classic start source registers: resume and fork are new sessions too', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await w.clock.advance(0)
  for (const [i, source] of (['resume', 'fork'] as const).entries()) {
    w.sessionId.value = `r${i}`
    await $.classic.SessionStart(classicStart(source, `r${i}`))
    await w.clock.advance(2 * SEC)
    expect(w.ingests.at(-1)?.payload).toMatchObject({ session_id: `r${i}`, census_mod: { event: `session.${source}` } })
  }
})

test('a main-thread turn records its counters; subagent turns and turns with no usage do not', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await w.clock.advance(0)
  await $.turn.complete(turn(USAGE, { agentId: 'sub' }))
  await $.turn.complete(turn(undefined))
  await w.clock.advance(5 * SEC)
  expect(w.ingests).toHaveLength(1)

  await $.turn.complete(turn(USAGE))
  await w.clock.advance(0)
  await w.clock.advance(2 * SEC)
  const p = w.ingests.at(-1)?.payload as Record<string, any>
  expect(p.census_mod.event).toBe('turn.complete')
  expect(p.prompt_cache).toMatchObject({ requests: 1, warm: true, ttl: '1h', hit_ratio: 0.9 })
  expect(p.context_window).toMatchObject({ total_input_tokens: 100, total_output_tokens: 100 })
})

test('ingests are coalesced: a burst is one write now and one carrying the latest state 2 s on', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await w.clock.advance(0)
  for (let i = 0; i < 4; i++) {
    await $.turn.complete(turn(USAGE))
    await w.clock.advance(0)
  }
  expect(w.ingests).toHaveLength(1) // the start; the burst waits
  await w.clock.advance(2 * SEC)
  expect(w.ingests).toHaveLength(2)
  expect((w.ingests[1]?.payload as any).prompt_cache.requests).toBe(4)
  await w.clock.advance(10 * SEC)
  expect(w.ingests).toHaveLength(2)
})

test('the last word on session.end is written at once, with the exit reason and a timeout inside the budget', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await w.clock.advance(0)
  await $.session.end({ reason: 'prompt_input_exit', sessionId: 's1', resume: {} as never })

  const last = w.ingests.at(-1)
  expect(last?.payload.census_mod).toMatchObject({ event: 'session.end', ended: 'prompt_input_exit' })
  expect(last?.timeoutMs).toBeGreaterThan(0)
  expect(last?.timeoutMs).toBeLessThanOrEqual(1000)
  const count = w.ingests.length
  await w.clock.advance(60 * MIN)
  expect(w.ingests).toHaveLength(count) // nothing after the end: no timers left
})

test('the cache goes cold on the clock: a write at last turn + ttl says warm is false', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await w.clock.advance(0)
  await $.turn.complete(turn(USAGE))
  await w.clock.advance(2 * SEC)
  expect((w.ingests.at(-1)?.payload as any).prompt_cache.warm).toBe(true)
  const before = w.ingests.length

  await w.clock.advance(58 * MIN) // 1h ttl (the tail says 1h): still warm
  expect(w.ingests).toHaveLength(before)
  await w.clock.advance(2 * MIN)
  const p = w.ingests.at(-1)?.payload as any
  expect(w.ingests.length).toBe(before + 1)
  expect(p.census_mod.event).toBe('cache.cold')
  expect(p.prompt_cache.warm).toBe(false)
})

test('without a 1h write in the tail the ttl is 5 minutes, and cools sooner', async ($, on) => {
  const w = world(on)
  w.tail.value = '"cache_creation":{"ephemeral_5m_input_tokens":50,"ephemeral_1h_input_tokens":0}\n'
  await $.session.start(START)
  await w.clock.advance(0)
  await $.turn.complete(turn(USAGE))
  await w.clock.advance(2 * SEC)
  await w.clock.advance(5 * MIN)

  expect(w.ingests.at(-1)?.payload).toMatchObject({ census_mod: { event: 'cache.cold' }, prompt_cache: { warm: false, ttl: '5m' } })
})

test('a compaction cold-starts the cache at once', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await w.clock.advance(0)
  await $.turn.complete(turn(USAGE))
  await w.clock.advance(2 * SEC)
  await $.classic.PostCompact({ trigger: 'auto', compact_summary: 's' } as never)
  await w.clock.advance(2 * SEC)

  expect(w.ingests.at(-1)?.payload).toMatchObject({ census_mod: { event: 'compact' }, prompt_cache: { warm: false } })
})

test('counters live in $.store: written each turn, and picked up again after a reload or a restart', async ($, on) => {
  const w = world(on)
  w.store.set('counters:s1', { requests: 7, input: 70, read: 700, create: 7000, output: 70_000, lastTurnAt: null, ttl: '1h', lastRatio: 0.5, cold: false, updatedAt: 1 })
  await $.session.start(START)
  await w.clock.advance(0)
  expect(w.ingests.at(-1)?.payload).toMatchObject({
    prompt_cache: { requests: 7, ttl: '1h' },
    context_window: { total_input_tokens: 7770, total_output_tokens: 70_000 },
  })

  await $.turn.complete(turn(USAGE))
  await w.clock.advance(0)
  expect(w.store.get('counters:s1')).toMatchObject({ requests: 8, output: 70_100 })
})

test('the session name comes from the last custom-title row of the transcript', async ($, on) => {
  const w = world(on)
  w.titles.set('/cfg/projects/-repo/s1.jsonl', '{"type":"custom-title","customTitle":"census mod","sessionId":"s1"}\n')
  await $.session.start(START)
  await $.classic.SessionStart(classicStart('startup'))
  await w.clock.advance(0)

  expect((w.ingests.at(-1)?.payload as any).session_name).toBe('census mod')
})

test('a rate-limit change records with census windows (epoch seconds); an unchanged one does not', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await w.clock.advance(0)
  const limits = [{ kind: 'five_hour', percentUsed: 41.5, resetsAt: '2026-10-09T22:00:00Z' }]
  w.usage.value = { ...w.usage.value, rateLimits: limits }
  const m = { context: { window: 1_000_000, percent: 10 }, rateLimits: limits, changed: ['rateLimits'] as never }
  await $.session.measure(m)
  await w.clock.advance(2 * SEC)
  expect(w.ingests).toHaveLength(2)
  expect(w.ingests[1]?.payload).toMatchObject({ census_mod: { event: 'rate-limit' }, rate_limits: { five_hour: { used_percentage: 41.5, resets_at: Date.parse('2026-10-09T22:00:00Z') / 1000 } } })

  await $.session.measure({ ...m, context: { window: 1_000_000, percent: 11 } })
  await w.clock.advance(10 * SEC)
  expect(w.ingests).toHaveLength(2)
})

test('a model switch and a cwd change record', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await w.clock.advance(0)
  w.model.value = 'claude-sonnet-5-5'
  await $.classic.PostModelSwitch({ from_model: 'claude-opus-5-5', to_model: 'claude-sonnet-5-5' } as never)
  await w.clock.advance(2 * SEC)
  expect(w.ingests.at(-1)?.payload).toMatchObject({ census_mod: { event: 'model' }, model: { display_name: 'Sonnet 5.5' } })

  await $.classic.CwdChanged({ old_cwd: '/repo', new_cwd: '/repo/sub' } as never)
  await w.clock.advance(2 * SEC)
  expect(w.ingests.at(-1)?.payload).toMatchObject({ census_mod: { event: 'cwd' }, cwd: '/repo/sub' })
})

test('a second session.start (a hot reload) is the same session: one set of timers, not two', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.session.start(START)
  await w.clock.advance(0)
  const redraws = w.invalidations.count
  await w.clock.advance(5 * MIN)

  expect(w.ingests).toHaveLength(1)
  expect(w.invalidations.count - redraws).toBeLessThanOrEqual(11) // ten 30 s ticks, not twenty
})

test('a reload re-arms the cache-cold timer from the stored counters', async ($, on) => {
  const w = world(on)
  w.store.set('counters:s1', { requests: 3, input: 1, read: 1, create: 1, output: 1, lastTurnAt: 1_791_000_000_000 - 4 * MIN, ttl: '5m', lastRatio: 0.9, cold: false, updatedAt: 1 })
  await $.session.start(START)
  await w.clock.advance(0)
  expect((w.ingests.at(-1)?.payload as any).prompt_cache.warm).toBe(true)

  await w.clock.advance(MIN + 2 * SEC)
  expect(w.ingests.at(-1)?.payload).toMatchObject({ census_mod: { event: 'cache.cold' }, prompt_cache: { warm: false } })
})

test('a process the registry does not know yet is looked for on every later write until it is found', async ($, on) => {
  const w = world(on)
  w.files.delete('/cfg/sessions/22695.json')
  await $.session.start(START)
  await w.clock.advance(0)
  expect(w.ingests.at(-1)?.payload.census_mod).not.toHaveProperty('pid')

  for (let i = 0; i < 8; i++) {
    await $.turn.complete(turn(USAGE))
    await w.clock.advance(2 * SEC)
  }
  expect(w.ingests.at(-1)?.payload.census_mod).not.toHaveProperty('pid') // far more than five tries

  w.files.set('/cfg/sessions/22695.json', JSON.stringify({ pid: 22695, sessionId: 's1', procStart: 'Sun Oct  4 22:57:51 2026', version: '2.1.289' }))
  await $.turn.complete(turn(USAGE))
  await w.clock.advance(2 * SEC)
  expect(w.ingests.at(-1)?.payload.census_mod).toMatchObject({ pid: 22695, proc_start: 'Sun Oct  4 22:57:51 2026' })
  const lists = w.registryLists.count
  await $.turn.complete(turn(USAGE))
  await w.clock.advance(2 * SEC)
  expect(w.registryLists.count).toBe(lists) // and once found it is not looked for again
})

test('a /clear, resume or fork writes the old session\'s end itself, once, even if session.end never came', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await w.clock.advance(0)
  w.sessionId.value = 's2'
  await $.classic.SessionStart(classicStart('clear', 's2'))
  await w.clock.advance(0)
  const ends = w.ingests.filter(i => i.payload.census_mod.ended !== undefined)
  expect(ends).toHaveLength(1)
  expect(ends[0]?.payload).toMatchObject({ session_id: 's1', census_mod: { event: 'session.end', ended: 'clear' } })

  w.sessionId.value = 's3'
  await $.classic.SessionStart(classicStart('fork', 's3'))
  await w.clock.advance(0)
  expect(w.ingests.filter(i => i.payload.census_mod.ended === 'fork')[0]?.payload.session_id).toBe('s2')
})

test('...but not twice when session.end already closed it', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await w.clock.advance(0)
  await $.session.end({ reason: 'clear', sessionId: 's1', resume: {} as never })
  w.sessionId.value = 's2'
  await $.classic.SessionStart(classicStart('clear', 's2'))
  await w.clock.advance(5 * SEC)

  expect(w.ingests.filter(i => i.payload.session_id === 's1' && i.payload.census_mod.ended !== undefined)).toHaveLength(1)
})

test('the git dir and the session name are read off the start hooks\' path, then folded into the first write', async ($, on) => {
  const w = world(on)
  w.git.dir = '/repo/.git/worktrees/w\n/wt\n'
  w.titles.set('/cfg/projects/-repo/s1.jsonl', '{"type":"custom-title","customTitle":"named","sessionId":"s1"}\n')
  await $.session.start(START)
  expect(w.runs.filter(r => r.argv.includes('rev-parse'))).toHaveLength(0)
  expect(w.runs.filter(r => r.argv[0] === 'grep')).toHaveLength(0)

  await w.clock.advance(0)
  expect(w.ingests).toHaveLength(1)
  expect(w.ingests[0]?.payload).toMatchObject({ session_name: 'named', worktree: { path: '/wt' } })
})

test('the first write waits for the first git status, so census_mod.git is not null until the next write', async ($, on) => {
  const w = world(on)
  let release: () => void = () => undefined
  w.gitGate.value = new Promise<void>(res => { release = res })
  await $.session.start(START)
  await w.clock.advance(0)
  await w.clock.advance(0)
  expect(w.ingests).toHaveLength(0) // held for git

  release()
  for (let i = 0; i < 4; i++) await w.clock.advance(0)
  expect(w.ingests).toHaveLength(1)
  expect(w.ingests[0]?.payload.census_mod).toMatchObject({ git: { branch: 'main', uncommitted: 1, ahead: 1, has_upstream: true, detached: false } })
})

test('...but only for a moment: a git that never answers does not hold the first write for ever', async ($, on) => {
  const w = world(on)
  w.gitGate.value = new Promise<void>(() => undefined)
  await $.session.start(START)
  await w.clock.advance(0)
  await w.clock.advance(3 * SEC + 100)

  expect(w.ingests).toHaveLength(1)
  expect(w.ingests[0]?.payload.census_mod).toMatchObject({ git: null })
})

test('a turn\'s deferred transcript reads belong to that session: a /clear in between gets nothing from them', async ($, on) => {
  const w = world(on)
  w.titles.set('/cfg/projects/-repo/s1.jsonl', '{"type":"custom-title","customTitle":"old name","sessionId":"s1"}\n')
  await $.session.start(START)
  await $.classic.SessionStart(classicStart('startup'))
  await w.clock.advance(0)
  await $.turn.complete(turn(USAGE)) // its reads are queued, not yet run
  w.sessionId.value = 's2'
  await $.classic.SessionStart(classicStart('clear', 's2'))
  for (let i = 0; i < 3; i++) await w.clock.advance(0)
  await w.clock.advance(3 * SEC)

  const mine = w.ingests.filter(i => i.payload.session_id === 's2')
  expect(mine.length).toBeGreaterThan(0)
  expect(mine.some(i => i.payload.census_mod.event === 'turn.complete')).toBe(false)
  expect(mine.every(i => i.payload.session_name === undefined)).toBe(true)
})

test('the title is read whole once, then only from the transcript tail each turn', async ($, on) => {
  const w = world(on)
  const path = '/cfg/projects/-repo/s1.jsonl'
  await $.session.start(START)
  await $.classic.SessionStart(classicStart('startup'))
  await w.clock.advance(0)
  const wholeReads = () => w.runs.filter(r => r.argv[0] === 'grep' && r.argv.includes(path)).length
  expect(wholeReads()).toBe(1)

  w.titles.set(path, '{"type":"custom-title","customTitle":"renamed later","sessionId":"s1"}\n')
  for (let i = 0; i < 3; i++) {
    await $.turn.complete(turn(USAGE))
    await w.clock.advance(2 * SEC)
  }
  expect(wholeReads()).toBe(1) // never again
  expect(w.runs.filter(r => r.argv[2]?.includes('custom-title')).length).toBeGreaterThanOrEqual(3)
  expect(w.ingests.at(-1)?.payload.session_name).toBe('renamed later')
})

test('the offer does not open a dialog after the session ended within its 3 seconds', async ($, on) => {
  const w = world(on)
  w.store.delete('census-mod:setup')
  await $.session.start(START)
  await w.clock.advance(0)
  await $.session.end({ reason: 'prompt_input_exit', sessionId: 's1', resume: {} as never })
  await w.clock.advance(5 * SEC)
  for (let i = 0; i < 6; i++) await w.clock.advance(0)

  expect(w.asks).toHaveLength(0)
})

test('a /clear within those 3 seconds moves the offer to the new session: asked once, there', async ($, on) => {
  const w = world(on)
  w.store.delete('census-mod:setup')
  await $.session.start(START)
  await w.clock.advance(0)
  w.sessionId.value = 's2'
  await $.classic.SessionStart(classicStart('clear', 's2'))
  await w.clock.advance(5 * SEC)
  for (let i = 0; i < 6; i++) await w.clock.advance(0)

  expect(w.asks.filter(a => a.header === '🧭 Setup')).toHaveLength(1)
})
