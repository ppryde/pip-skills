import { describe, expect, test } from 'claude-code/testing'
import { FIELD_NAMES, INPUT_SCHEMA, cleanName, injectText, instructionText, limitResumeText, nextThreshold, parseFields, renderHandover, resumeText, reusable } from '../core/handover'

const S = { nudgeAt: 35, step: 5 }

describe('nextThreshold', () => {
  test('below the threshold nothing is due', () => expect(nextThreshold(34, S, null)).toBe(null))
  test('the first crossing', () => expect(nextThreshold(35, S, null)).toBe(35))
  test('a jump lands on the highest step crossed', () => expect(nextThreshold(47, S, null)).toBe(45))
  test('the same step never repeats', () => expect(nextThreshold(39, S, 35)).toBe(null))
  test('the next step is due', () => expect(nextThreshold(40, S, 35)).toBe(40))
  test('after reset (a /clear) the first crossing is due again', () => {
    expect(nextThreshold(12, S, null)).toBe(null)
    expect(nextThreshold(36, S, null)).toBe(35)
  })
})

describe('parseFields', () => {
  const good = { goal: 'g', state: 's', next_step: 'n', session_name: 'nm' }
  test('required fields only; optional ones default to empty', () => {
    expect(parseFields(good)).toEqual({ ok: true, fields: { goal: 'g', state: 's', decisions: '', next_step: 'n', open_questions: '', failed_attempts: '', session_name: 'nm' } })
  })
  test('a missing or blank required field is rejected with its name', () => {
    const r = parseFields({ ...good, state: '  ' })
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.error).toContain('state')
  })
  test('a non-string field is rejected', () => {
    const r = parseFields({ ...good, decisions: 42 })
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.error).toContain('decisions')
  })
  test('strings are trimmed', () => {
    const r = parseFields({ ...good, goal: ' g ' })
    expect(r.ok && r.fields.goal).toBe('g')
  })
  test('the schema requires the core fields and the session name', () => {
    expect(INPUT_SCHEMA.required).toEqual(['goal', 'state', 'next_step', 'session_name'])
    expect(INPUT_SCHEMA.properties.session_name?.description).toContain('name')
  })
  test('field names end with session_name', () => {
    expect([...FIELD_NAMES]).toEqual(['goal', 'state', 'decisions', 'next_step', 'open_questions', 'failed_attempts', 'session_name'])
  })
  test('a missing or blank session_name is rejected, naming it', () => {
    for (const session_name of [undefined, '   ', '/']) {
      const r = parseFields({ goal: 'g', state: 's', next_step: 'n', session_name })
      expect(r.ok).toBe(false)
      if (!r.ok) expect(r.error).toContain('session_name')
    }
  })
  test('session_name is stored cleaned', () => {
    const r = parseFields({ ...good, session_name: '  /clear\n x ' })
    expect(r.ok && r.fields.session_name).toBe('clear x')
  })
})

describe('cleanName', () => {
  test('whitespace and newlines collapse and trim', () => expect(cleanName('  vigil-mod:\n shell   flow ')).toBe('vigil-mod: shell flow'))
  test('a leading slash is stripped', () => expect(cleanName('/clear x')).toBe('clear x'))
  test('cut to 60 code units then trimmed', () => {
    expect(cleanName('a'.repeat(70))).toBe('a'.repeat(60))
    expect(cleanName('a'.repeat(59) + ' bbb')).toBe('a'.repeat(59))
  })
})

describe('renderHandover', () => {
  const snap = { session: 's1', at: '2026-10-04T12:00:00.000Z', cwd: '/repo', branch: 'main', dirty: ['a.ts'], edited: ['b.ts', 'c.ts'], contextPct: 41 }
  const fields = { goal: 'Ship it', state: 'Half done', decisions: 'Use B', next_step: 'Write tests', open_questions: '', failed_attempts: 'tmux keys', session_name: 'vigil-mod: shell flow' }
  test('sections in order, empty ones left out, snapshot at the end', () => {
    const md = renderHandover(fields, snap)
    expect(md.startsWith('# 📜 Handover — s1 (2026-10-04T12:00:00.000Z)\n')).toBe(true)
    const order = ['## Goal', '## State', '## Decisions', '## Next step', '## Failed attempts', '## Snapshot']
    let at = -1
    for (const h of order) { const i = md.indexOf(h); expect(i).toBeGreaterThan(at); at = i }
    expect(md).not.toContain('## Open questions')
    expect(md).toContain('- branch: main')
    expect(md).toContain('- context: 41%')
    expect(md).toContain('- dirty: a.ts')
    expect(md).toContain('- edited this session: b.ts, c.ts')
  })
  test('the next session name is the second line, never a section', () => {
    const md = renderHandover(fields, snap)
    expect(md.split('\n')[1]).toBe('**Next session:** vigil-mod: shell flow')
    expect(md).not.toContain('## Session name')
    expect(md).not.toContain('## session_name')
  })
  test('unknowns are said plainly', () => {
    const md = renderHandover(fields, { ...snap, branch: null, dirty: [], edited: [], contextPct: null })
    expect(md).toContain('- branch: (not a git repo)')
    expect(md).toContain('- dirty: none')
    expect(md).toContain('- context: unknown')
  })
})

test('texts name the tool and the file', () => {
  expect(instructionText('threshold')).toContain('mcp__context-vigil-mod__vigil_handover')
  expect(instructionText('last_light')).toContain('Do not clear')
  expect(resumeText('/cfg/x.md')).toContain('/cfg/x.md')
  expect(injectText('# H')).toContain('# H')
  const after = limitResumeText('/cfg/x.md')
  expect(after).toContain('/cfg/x.md')
  expect(after).toContain('limit has reset')
  expect(after).not.toContain('injected above')
})

describe('reusable', () => {
  const p = (reason: 'threshold' | 'request' | 'last_light' | 'limit') => ({ reason, createdAt: 1_000_000 })
  test('no pending handover: nothing to reuse', () => expect(reusable(null, null)).toBe(false))
  test('written for a clear, no turn since: reused', () => {
    expect(reusable(p('request'), null)).toBe(true)
    expect(reusable(p('threshold'), 1_000_000 + 30_000)).toBe(true)
  })
  test('a turn completed well after it was written: stale', () => expect(reusable(p('request'), 1_000_000 + 5 * 60_000)).toBe(false))
  test('last light and limit handovers are never cleared into', () => {
    expect(reusable(p('last_light'), null)).toBe(false)
    expect(reusable(p('limit'), null)).toBe(false)
  })
})
