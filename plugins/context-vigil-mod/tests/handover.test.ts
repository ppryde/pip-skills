import { describe, expect, test } from 'claude-code/testing'
import { INPUT_SCHEMA, injectText, instructionText, limitResumeText, nextThreshold, parseFields, renderHandover, resumeText } from '../core/handover'

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
  const good = { goal: 'g', state: 's', next_step: 'n' }
  test('required fields only; optional ones default to empty', () => {
    expect(parseFields(good)).toEqual({ ok: true, fields: { goal: 'g', state: 's', decisions: '', next_step: 'n', open_questions: '', failed_attempts: '' } })
  })
  test('a missing or blank required field is rejected with its name', () => {
    const r = parseFields({ goal: 'g', state: '  ', next_step: 'n' })
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.error).toContain('state')
  })
  test('a non-string field is rejected', () => {
    const r = parseFields({ ...good, decisions: 42 })
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.error).toContain('decisions')
  })
  test('strings are trimmed', () => {
    const r = parseFields({ goal: ' g ', state: 's', next_step: 'n' })
    expect(r.ok && r.fields.goal).toBe('g')
  })
  test('the schema requires the three core fields', () => {
    expect(INPUT_SCHEMA.required).toEqual(['goal', 'state', 'next_step'])
  })
})

describe('renderHandover', () => {
  const snap = { session: 's1', at: '2026-10-04T12:00:00.000Z', cwd: '/repo', branch: 'main', dirty: ['a.ts'], edited: ['b.ts', 'c.ts'], contextPct: 41 }
  const fields = { goal: 'Ship it', state: 'Half done', decisions: 'Use B', next_step: 'Write tests', open_questions: '', failed_attempts: 'tmux keys' }
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
