import { mock } from 'claude-code/testing'
import type { On } from 'claude-code'
import type { Engine } from 'claude-code/testing'

export type AskSeen = { question: string; header: string; multiSelect: boolean; options: string[]; descriptions: string[] }

export type World = {
  clock: ReturnType<typeof mock.clock>
  files: Map<string, string>
  submits: { text: string; origin: string }[]
  commands: string[]
  notices: string[]   // ui.toast lines — one per notify()
  logs: string[]      // ui.log lines — kept apart so counts on `notices` stay exact
  registered: { tools: string[]; commands: string[] }
  draft: { value: string }
  sessionId: { value: string }
  liveId: { value: string }            // the id the mod last saw a conversation under: session.start's, then each endInto's
  cwd: { value: string }               // $.session.cwd(): moves with EnterWorktree or a cd
  contextPct: { value: number | undefined }
  model: { value: string | null }      // $.session.model(); null makes it reject
  rateLimits: { value: { kind: string; percentUsed: number; resetsAt?: string }[] }
  git: { branch: string; status: string; dir: string | null }   // dir: what `git rev-parse --absolute-git-dir` prints; null fails it
  runs: { count: number }              // process.run calls answered
  state: Map<string, unknown>          // $.state values by `plugin.key` — the engine's session state, wiped by a clear
  askAnswer: { value: string | null }  // answers $.ui.ask and AskUserQuestion; null = dismissed
  toastRefused: { value: boolean }     // makes ui.toast answer { deny }
  clearRefused: { value: boolean }     // makes $.command.run({ command: 'clear' }) reject
  submitRefused: { value: boolean }    // makes $.prompt.submit reject
  submitFails: { count: number }       // makes the next N $.prompt.submit calls reject (a session still starting)
  eventsWriteRefused: { value: boolean }   // makes fs.write under /events/ deny
  renameRefused: { value: boolean }    // makes $.command.run({ command: 'rename' }) reject
  renameRefusedAt: Set<number>         // makes only these renames reject, counted from 1 across the test
  renames: string[]                    // args of every rename command run
  shell: { value: boolean }            // whether `sh` runs (it does not on Windows)
  titles: Map<string, string>          // transcript path → its last custom title; a rename sets the current one's
  transcriptOf: (id: string) => string // where a session's transcript is: <config>/projects/-repo/<id>.jsonl
  wipe: () => void                     // what a /clear or /resume does to $.state (PROBES §9, §16)
  grepFails: { value: boolean }        // makes the custom-title read exit 2
  greps: string[][]                    // argv of every custom-title read
  store: Map<string, unknown>          // $.store by key — per account, NOT wiped by a clear
  handoverWriteRefused: { value: boolean }               // makes fs.write under /handovers/ deny
  cacheWrites: { value: { h1: number; m5: number } | 'none' | 'fail' | { raw: string } }   // what the transcript tail says the latest response wrote
  tails: string[][]                    // argv of every transcript-tail run
  fsRead: { gate: Promise<void> | null; error: string | null }   // gate delays every fs.read; error makes it reject with that text
  clearHold: { held: boolean; release(): void }   // while held, $.command.run({ command: 'clear' }) stays pending until release()
  promptReadFails: { count: number }   // the next N $.prompt.read calls reject
  askHold: { held: boolean; waiting: ((answer: string) => void)[] }   // while held, each ask stays open until its resolver is called
  asks: AskSeen[]                      // every AskUserQuestion question asked, $.ui.ask included, in order
  askReply: { value: ((q: AskSeen) => string | null) | null }   // answers per question when set (null = dismissed); else askAnswer
  storeGetRefused: { value: boolean }  // makes $.store.get reject
  onStoreSet: { value: ((key: string) => Promise<unknown>) | null }  // runs inside store.set, before it answers
}

export function world(on: On, opts: { now?: number; store?: Record<string, unknown>; files?: Record<string, string>; env?: Record<string, string> } = {}): World {
  const env = opts.env ?? { CLAUDE_CONFIG_DIR: '/cfg', HOME: '/home/u' }
  const configDir = env.CLAUDE_CONFIG_DIR ?? `${env.HOME ?? ''}/.claude`
  const w: World = {
    clock: mock.clock(on, { now: opts.now ?? 1_000_000 }),
    files: new Map(Object.entries(opts.files ?? {})),
    submits: [], commands: [], notices: [], logs: [],
    registered: { tools: [], commands: [] },
    draft: { value: '' }, sessionId: { value: 's1' }, liveId: { value: 's1' }, cwd: { value: '/repo' }, contextPct: { value: undefined }, model: { value: 'claude-opus-5-5[1m]' },
    rateLimits: { value: [] }, git: { branch: 'main\n', status: '', dir: '/repo/.git' }, runs: { count: 0 }, state: new Map(), askAnswer: { value: null },
    toastRefused: { value: false }, clearRefused: { value: false }, renameRefused: { value: false }, renameRefusedAt: new Set(), submitRefused: { value: false }, submitFails: { count: 0 }, eventsWriteRefused: { value: false }, renames: [],
    shell: { value: true }, titles: new Map(), transcriptOf: id => `${configDir}/projects/-repo/${id}.jsonl`, wipe: () => {}, grepFails: { value: false }, greps: [], store: new Map(Object.entries(opts.store ?? {})),
    handoverWriteRefused: { value: false }, cacheWrites: { value: { h1: 100, m5: 0 } }, tails: [], clearHold: { held: false, release() {} }, askHold: { held: false, waiting: [] }, asks: [], askReply: { value: null }, promptReadFails: { count: 0 }, onStoreSet: { value: null }, storeGetRefused: { value: false }, fsRead: { gate: null, error: null },
  }
  // $.store, per account: in memory, survives a clear, and open to the test (another process's writes).
  on('store.get', (_$, e) => (w.storeGetRefused.value ? { deny: 'store unavailable' } : { value: w.store.get(e.key) as never }))
  // The hook runs first: a refused write (the hook throws) must leave nothing stored.
  on('store.set', async (_$, e) => { await w.onStoreSet.value?.(e.key); w.store.set(e.key, e.value); return { value: undefined } })
  on('store.delete', (_$, e) => { w.store.delete(e.key); return { value: undefined } })
  on('store.keys', () => ({ value: [...w.store.keys()] }))
  mock.env(on, env)
  on('prompt.fill', (_$, e) => { w.draft.value = (e as { text: string }).text; return { isFilled: true } as never })
  on('fs.read', async (_$, e) => {
    await w.fsRead.gate
    if (w.fsRead.error !== null) return { deny: w.fsRead.error }
    const t = w.files.get(e.path)
    return t === undefined ? { deny: `ENOENT ${e.path}` } : { value: t as never }
  })
  on('fs.write', (_$, e) => {
    if (w.handoverWriteRefused.value && e.path.includes('/handovers/')) return { deny: `EACCES ${e.path}` }
    if (w.eventsWriteRefused.value && e.path.includes('/events/')) return { deny: `EACCES ${e.path}` }
    w.files.set(e.path, e.text)
    return { value: undefined }
  })
  on('fs.exists', (_$, e) => ({ value: w.files.has((e as { path: string }).path) }))
  on('process.run', (_$, e) => {
    if (e.argv[0] === 'sh' && e.argv[2] === 'exit 0') { w.runs.count++; if (!w.shell.value) throw new Error('spawn sh ENOENT'); return { value: { exitCode: 0, stdout: '', stderr: '', isStdoutTruncated: false, isStderrTruncated: false } } }
    if (e.argv[0] === 'sh' && !w.shell.value) throw new Error('spawn sh ENOENT')
    w.runs.count++
    if (e.argv[0] === 'sh' && e.argv[2]?.startsWith('tail -c "$2"')) {
      const t = w.files.get(e.argv[4] ?? '')
      return { value: { exitCode: t === undefined ? 1 : 0, stdout: t === undefined ? '' : t.slice(-Number(e.argv[5])), stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
    }
    if (e.argv[0] === 'sh' && e.argv[2]?.includes('custom-title')) {
      w.greps.push([...e.argv])
      const title = w.titles.get(e.argv[e.argv.length - 1] ?? '')
      const exitCode = w.grepFails.value ? 2 : title !== undefined ? 0 : 1
      const stdout = exitCode === 0 ? `${JSON.stringify({ type: 'custom-title', customTitle: title, sessionId: 'x' })}\n` : ''
      return { value: { exitCode, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
    }
    if (e.argv[0] === 'sh' && e.argv[2]?.includes('cache_creation')) {
      w.tails.push([...e.argv])
      const cw = w.cacheWrites.value
      if (cw === 'fail') return { value: { exitCode: 1, stdout: '', stderr: 'tail: no such file', isStdoutTruncated: false, isStderrTruncated: false } }
      if (typeof cw === 'object' && 'raw' in cw) return { value: { exitCode: 0, stdout: cw.raw, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
      const stdout = cw === 'none' ? '' : `"cache_creation":{"ephemeral_5m_input_tokens":${cw.m5},"ephemeral_1h_input_tokens":${cw.h1}}\n`
      return { value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
    }
    const a = e.argv.join(' ')
    if (a.includes('--absolute-git-dir')) {
      const dir = w.git.dir
      return { value: { exitCode: dir === null ? 128 : 0, stdout: dir === null ? '' : `${dir}\n`, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
    }
    const out = a.includes('symbolic-ref') ? w.git.branch : w.git.status
    return { value: { exitCode: 0, stdout: out, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  const stateKey = (e: { plugin: string; key: string; id?: string }) => `${e.plugin}.${e.key}${e.id === undefined ? '' : `#${e.id}`}`
  const versions = new Map<string, number>()
  w.wipe = () => { w.state.clear(); versions.clear() }
  on('state.get', (_$, e) => { const k = stateKey(e as never); return { value: { value: w.state.get(k) as never, version: versions.get(k) ?? 0 } } })
  on('state.set', (_$, e) => {
    const k = stateKey(e as never)
    const { ifVersion } = e as { ifVersion?: number }
    if (ifVersion !== undefined && ifVersion !== (versions.get(k) ?? 0)) return { value: { isSet: false as const, version: versions.get(k) ?? 0 } }
    const version = (versions.get(k) ?? 0) + 1
    versions.set(k, version)
    w.state.set(k, (e as { value: unknown }).value)
    return { value: { isSet: true as const, version } }
  })
  on('session.id', () => ({ value: w.sessionId.value }))
  on('session.cwd', () => ({ value: w.cwd.value }))
  on('session.model', () => (w.model.value === null ? { deny: 'no model' } : { value: w.model.value }))
  on('session.repo', () => ({ value: { root: '/repo', remote: null, internal: false, name: 'repo', id: 'r' } }))
  on('session.usage', () => ({ value: { startedAt: 0, context: { window: 1_000_000, percent: w.contextPct.value }, rateLimits: w.rateLimits.value } }))
  on('prompt.read', () => { if (w.promptReadFails.count > 0) { w.promptReadFails.count--; throw new Error('prompt.read failed') } return { value: { text: w.draft.value, cursor: w.draft.value.length } } })
  on('prompt.submit', (_$, e) => { if (w.submitRefused.value) throw new Error('submit refused'); if (w.submitFails.count > 0) { w.submitFails.count--; throw new Error('session not ready') } w.submits.push({ text: e.text, origin: e.origin.kind }); return { text: e.text, origin: e.origin } })
  on('prompt.edit', (_$, e) => ({ text: e.text, cursor: e.cursor }))
  let renameCalls = 0
  on('command.run', async (_$, e) => {
    if (e.command === 'clear' && w.clearRefused.value) throw new Error('clear refused')
    if (e.command === 'rename') renameCalls++
    if (e.command === 'rename' && (w.renameRefused.value || w.renameRefusedAt.has(renameCalls))) throw new Error('rename refused')
    w.commands.push(e.command)
    if (e.command === 'rename') {
      const name = String((e as { args?: string }).args ?? '')
      w.renames.push(name)
      w.titles.set(w.transcriptOf(w.sessionId.value), name)   // /rename names the current session (PROBES §15)
    }
    if (e.command === 'clear' && w.clearHold.held) await new Promise<void>(res => { w.clearHold.release = () => { w.clearHold.held = false; res() } })
    return {}
  })
  on('command.register', (_$, e) => { w.registered.commands.push(e.name); return { value: { command: e.name } } })
  on('tool.register', (_$, e) => { w.registered.tools.push(e.name); return { value: { tool: `mcp__context-vigil-mod__${e.name}` } } })
  on('ui.toast', (_$, e) => { if (w.toastRefused.value) return { deny: 'no toast surface' }; w.notices.push(e.text); return { value: undefined } })
  on('ui.log', (_$, e) => { w.logs.push(e.text); return { value: undefined } })
  on('ui.status', () => ({ value: undefined }))
  on('ui.render', ($, e) => { const { Box } = $.ui.resolve(e); return <Box /> })
  on('session.start', (_$, e) => { w.liveId.value = w.sessionId.value; return { cwd: e.cwd } })
  on('session.end', (_$, e) => ({ sessionId: e.sessionId }))
  on('session.measure', (_$, e) => ({ changed: e.changed }))
  on('turn.start', (_$, e) => e as never)
  on('turn.complete', (_$, e) => ({ text: e.answer }))
  // AskUserQuestion — and $.ui.ask, which is not an op event but runs as this tool call.
  // Result shape { questions, answers: { [question]: label } } per the claude-code-tools typings.
  // A test that passes `answers` on the input gets them echoed; otherwise every question
  // gets w.askAnswer; null means the person dismissed the dialog.
  on('tool.call', async (_$, e) => {
    const input = e as unknown as { tool: string; questions?: { question: string; header?: string; multiSelect?: boolean; options?: (string | { label: string; description?: string })[] }[]; answers?: Record<string, string> }
    if (input.tool === 'AskUserQuestion') {
      const seen = (input.questions ?? []).map(q => ({
        question: q.question, header: q.header ?? '', multiSelect: q.multiSelect === true,
        options: (q.options ?? []).map(o => (typeof o === 'string' ? o : o.label)),
        descriptions: (q.options ?? []).map(o => (typeof o === 'string' ? '' : o.description ?? '')),
      }))
      if (!input.answers) w.asks.push(...seen)
      // The paused-while-typing dialog stays open unless a test answers it (askReply): dismissing it postpones the handover.
      if (!input.answers && !w.askReply.value && seen.some(q => q.question.includes('paused while'))) return new Promise(() => undefined) as never
      if (w.askReply.value && !input.answers && !w.askHold.held) {
        const replies = seen.map(q => [q.question, w.askReply.value?.(q) ?? null] as const)
        if (replies.some(([, a]) => a === null)) return { deny: 'dismissed' }
        return { result: { questions: input.questions, answers: Object.fromEntries(replies) } } as never
      }
      if (w.askHold.held && !input.answers) {
        const held = await new Promise<string>(res => w.askHold.waiting.push(res))
        return { result: { questions: input.questions, answers: Object.fromEntries((input.questions ?? []).map(q => [q.question, held])) } } as never
      }
      if (input.answers) return { result: { questions: input.questions, answers: input.answers } } as never
      if (w.askAnswer.value === null) return { deny: 'dismissed' }
      const answer = w.askAnswer.value
      return { result: { questions: input.questions, answers: Object.fromEntries((input.questions ?? []).map(q => [q.question, answer])) } } as never
    }
    return { result: 'ok' } as never
  })
  return w
}

export const START = { cwd: '/repo', surface: 'terminal' as const, isInteractive: true }
export const turn = (id = 't') => ({ answer: 'a', durationMs: 1, isAborted: false, turnId: id, reason: 'answer' as const })
// A turn that reports usage, as the engine does: cacheCreation > 0 means a response wrote to the cache.
export const usageTurn = (cacheCreation: number, id = 't') => ({ ...turn(id), usage: { input_tokens: 1, output_tokens: 1, cache_read_input_tokens: 50, cache_creation_input_tokens: cacheCreation, model: 'm' } })
export const human = (text: string, kind: 'composer' | 'bridge' = 'composer') => ({ text, wait: false, origin: { kind } as never })

// PROBES §16: a /clear or a /resume as the mod sees it where no classic hook reaches it. session.end
// fires under the old id with $.state intact; then the engine answers the new id with $.state wiped,
// and a /clear has carried the old name into the new transcript (§8). `to` defaults to w.sessionId
// (a test that set it first); `lagMs`: how long the engine still answers the old id after the end
// (the mod polls for it); `unmoved`, or a `to` that is the old id: the id never moves (the mod gives
// up after its wait).
export async function endInto($: Engine, w: World, reason: 'clear' | 'resume', opts: { to?: string; lagMs?: number; unmoved?: boolean } = {}) {
  const from = w.liveId.value
  const to = opts.unmoved ? from : opts.to ?? w.sessionId.value
  const unmoved = to === from
  w.sessionId.value = from
  await $.session.end({ reason, sessionId: from, resume: { id: from } })
  if (opts.lagMs) await w.clock.advance(opts.lagMs)
  w.wipe()
  if (reason === 'clear') {
    const carried = w.titles.get(w.transcriptOf(from))
    if (carried !== undefined) w.titles.set(w.transcriptOf(to), carried)
  }
  w.sessionId.value = to
  w.liveId.value = to
  // The poll runs every 50 ms: the next one after the move finds the new id; an unmoved one waits it out.
  await w.clock.advance(unmoved ? 5050 : opts.lagMs ? 50 : 0)
}
