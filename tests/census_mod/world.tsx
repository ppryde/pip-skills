import { mock } from 'claude-code/testing'
import type { On } from 'claude-code'

export type Run = { argv: string[]; cwd?: string; stdin?: string; env?: Record<string, string>; timeoutMs?: number }
const done = (exitCode: number, stdout = '', stderr = '') => ({ exitCode, stdout, stderr, isStdoutTruncated: false, isStderrTruncated: false })

export type World = {
  clock: ReturnType<typeof mock.clock>
  files: Map<string, string>
  dirs: Map<string, string[]>          // fs.list by directory
  store: Map<string, unknown>
  sessionId: { value: string }
  cwd: { value: string }
  usage: { value: { startedAt: number; context: { window: number; percent?: number }; rateLimits: { kind: string; percentUsed: number; resetsAt?: string }[]; cost?: { usd: number } } }
  model: { value: string }
  runs: Run[]                          // every process.run, in order
  ingests: { payload: Record<string, any>; argv: string[]; env?: Record<string, string>; timeoutMs?: number }[]
  git: { status: string; dir: string; exitCode: number }
  gh: { stdout: string; exitCode: number; throws: boolean }
  titles: Map<string, string>          // transcript path -> grep output
  tail: { value: string }              // transcript tail grep output
  which: { value: string }             // `command -v census` output ('' = not found)
  logs: string[]
  invalidations: { count: number }
  surfaces: { value: string[] }
  /** A census plugin beside this one, answered for WHATEVER folder the plugin sits in (the kit stages it in a temp dir). */
  sibling: { layout: 'repo' | 'cache' | null; versions: Record<string, { orphaned?: boolean; cli?: boolean }> }
  below: { text: string }              // what another mod beneath this one draws in the band ('' = nothing)
}

export const CLI = '/plugins/census/scripts/cli.py'
export const REGISTRY = '/cfg/sessions'

export function world(on: On, opts: { now?: number; env?: Record<string, string>; files?: Record<string, string> } = {}): World {
  const w: World = {
    clock: mock.clock(on, { now: opts.now ?? 1_791_000_000_000 }),
    files: new Map(Object.entries({ '/cfg/census/cli.path': CLI, [CLI]: '', ...(opts.files ?? {}) })),
    dirs: new Map([[REGISTRY, ['22695.json']]]),
    store: new Map(),
    sessionId: { value: 's1' },
    cwd: { value: '/repo' },
    usage: { value: { startedAt: 1_791_000_000_000 - 600_000, context: { window: 1_000_000, percent: 9 }, rateLimits: [], cost: { usd: 0.9 } } },
    model: { value: 'claude-opus-5-5[1m]' },
    runs: [], ingests: [],
    git: { status: '# branch.oid abc1234def\n# branch.head main\n# branch.upstream origin/main\n# branch.ab +1 -0\n1 .M N... 100644 100644 100644 a b f.ts\n', dir: '/repo/.git\n/repo\n', exitCode: 0 },
    gh: { stdout: '[]', exitCode: 0, throws: false },
    titles: new Map(), tail: { value: '"cache_creation":{"ephemeral_5m_input_tokens":0,"ephemeral_1h_input_tokens":100}\n' },
    which: { value: '' }, logs: [], invalidations: { count: 0 }, surfaces: { value: ['terminal'] }, below: { text: '' }, sibling: { layout: null, versions: {} },
  }
  w.files.set(`${REGISTRY}/22695.json`, JSON.stringify({ pid: 22695, sessionId: 's1', procStart: 'Sun Oct  4 22:57:51 2026', version: '2.1.289' }))
  on('store.get', (_$, e) => ({ value: w.store.get(e.key) as never }))
  on('store.set', (_$, e) => { w.store.set(e.key, e.value); return { value: undefined } })
  on('store.delete', (_$, e) => { w.store.delete(e.key); return { value: undefined } })
  on('store.keys', () => ({ value: [...w.store.keys()] }))
  mock.env(on, opts.env ?? { CLAUDE_CONFIG_DIR: '/cfg', HOME: '/home/u' })
  on('fs.read', (_$, e) => { const t = w.files.get(e.path); return t === undefined ? { deny: `ENOENT ${e.path}` } : { value: t as never } })
  on('fs.exists', (_$, e) => {
    const path = (e as { path: string }).path
    if (w.files.has(path)) return { value: true }
    if (w.sibling.layout === 'repo') return { value: /\/census\/scripts\/cli\.py$/.test(path) && !path.startsWith('/cfg') && path !== CLI }
    if (w.sibling.layout === 'cache') {
      const m = /\/census\/([^/]+)\/(\.orphaned_at|scripts\/cli\.py)$/.exec(path)
      const v = m ? w.sibling.versions[m[1] ?? ''] : undefined
      return { value: m?.[2] === '.orphaned_at' ? v?.orphaned === true : v?.cli !== false && v !== undefined }
    }
    return { value: false }
  })
  on('fs.list', (_$, e) => {
    const path = (e as { path: string }).path
    if (w.sibling.layout === 'cache' && /\/census$/.test(path) && !path.startsWith('/cfg')) {
      return { value: Object.keys(w.sibling.versions).map(name => ({ name, kind: 'dir' as const, size: 0, mtimeMs: 0, isLink: false })) as never }
    }
    const names = w.dirs.get(path)
    return names ? { value: names.map(name => ({ name, kind: 'file' as const, size: 1, mtimeMs: 0, isLink: false })) as never } : { deny: 'ENOENT' }
  })
  on('process.run', (_$, e) => {
    const init = (e as unknown as { init?: { cwd?: string; stdin?: string; env?: Record<string, string>; timeoutMs?: number } }).init ?? {}
    const run: Run = { argv: [...e.argv], cwd: init.cwd, stdin: init.stdin, env: init.env, timeoutMs: init.timeoutMs }
    w.runs.push(run)
    const [cmd, ...args] = e.argv
    if (cmd === 'git' && args.includes('status')) return { value: done(w.git.exitCode, w.git.status) }
    if (cmd === 'git' && args.includes('rev-parse')) return { value: done(w.git.exitCode, w.git.dir) }
    if (cmd === 'gh') {
      if (w.gh.throws) throw new Error('spawn gh ENOENT')
      return { value: done(w.gh.exitCode, w.gh.stdout) }
    }
    if (cmd === 'grep') return { value: w.titles.has(e.argv[e.argv.length - 1] ?? '') ? done(0, w.titles.get(e.argv[e.argv.length - 1] ?? '')) : done(1) }
    if (cmd === 'sh' && e.argv[2]?.includes('cache_creation')) return { value: done(0, w.tail.value) }
    if (cmd === 'sh' && e.argv[2]?.includes('command -v census')) return { value: w.which.value ? done(0, `${w.which.value}\n`) : done(1) }
    if (args.includes('ingest')) {
      w.ingests.push({ payload: JSON.parse(init.stdin ?? '{}'), argv: [...e.argv], env: init.env, timeoutMs: init.timeoutMs })
      return { value: done(0) }
    }
    return { value: done(1) }
  })
  on('session.id', () => ({ value: w.sessionId.value }))
  on('session.cwd', () => ({ value: w.cwd.value }))
  on('session.model', () => ({ value: w.model.value }))
  on('session.usage', () => ({ value: w.usage.value as never }))
  on('session.surfaces', () => ({ value: w.surfaces.value as never }))
  on('ui.log', (_$, e) => { w.logs.push(e.text); return { value: undefined } })
  on('ui.invalidate', () => { w.invalidations.count++; return { value: undefined } })
  on('ui.render', ($, e) => { const { Box, Text } = $.ui.resolve(e); return w.below.text ? <Box><Text>{w.below.text}</Text></Box> : <Box /> })
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  on('session.measure', (_$, e) => ({ changed: e.changed }))
  on('session.end', (_$, e) => ({ sessionId: e.sessionId }))
  on('turn.complete', (_$, e) => ({ text: e.answer }))
  on('classic.SessionStart', () => ({}))
  on('classic.FileChanged', () => ({}))
  on('classic.PostModelSwitch', () => ({}))
  on('classic.CwdChanged', () => ({}))
  on('classic.PostCompact', () => ({}))
  on('tool.call', () => ({ result: 'ok' }) as never)
  return w
}

export const START = { cwd: '/repo', surface: 'terminal' as const, isInteractive: true }
export const turn = (usage?: { input_tokens: number; output_tokens: number; cache_read_input_tokens: number; cache_creation_input_tokens: number }, extra: object = {}) => ({
  answer: 'a', durationMs: 1, isAborted: false, turnId: 't', reason: 'answer' as const,
  ...(usage ? { usage: { ...usage, model: 'claude-opus-5-5' } } : {}), ...extra,
})
export const USAGE = { input_tokens: 2, output_tokens: 100, cache_read_input_tokens: 90, cache_creation_input_tokens: 8 }
export const classicStart = (source: 'startup' | 'resume' | 'clear' | 'compact' | 'fork', session_id = 's1') =>
  ({ session_id, transcript_path: `/cfg/projects/-repo/${session_id}.jsonl`, cwd: '/repo', hook_event_name: 'SessionStart' as const, source }) as never
export const BAND = (props: Record<string, unknown> = {}) =>
  ({ plugin: 'census-mod', surface: 'terminal' as const, component: 'AbovePrompt' as const, props: { hasSurvey: false, isWorking: false, maxRows: 10, bodyColumns: 120, ...props } as never })

type Node = { type?: string; props?: { key?: string }; key?: string; text?: string; children?: (Node | string)[] }
const textOf = (n: Node | string): string => (typeof n === 'string' ? n : (n.children ?? []).map(textOf).join(''))

/** The band as lines of plain text: one per row of the mod's column, whatever is nested beneath last. */
export async function bandLines(ui: { drawn: () => Promise<unknown> }): Promise<string[]> {
  const root = (await ui.drawn()) as Node
  return (root.children ?? []).map(textOf).filter(l => l !== '')
}
