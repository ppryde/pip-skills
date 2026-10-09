import { describe, expect, test } from 'claude-code/testing'
import { isHandoverRequest, mentionsHandover } from '../../plugins/context-vigil-mod/core/handover'

const YES = [
  'handover', 'Handover', 'handover.', 'handover please', 'do a handover', 'do a handover now', 'hand over', 'hand over now',
  'hand this off', 'hand it over', 'hand this over', 'handoff', 'handoff please', 'hand off', 'hand-over', 'hand-off',
  'time for a handover', "let's hand over and clear", 'lets do a handover', 'can you do a handover?', 'could you do a handover please',
  'please hand over', 'ok do the handover', 'okay, handover now', 'run a handover', 'start a handover', 'make a handover',
  'I want a handover', 'we need a handover', 'ready for a handover', 'go ahead and hand over', 'just do the handover',
  'hand this session off', 'write a handover and clear', 'do a handoff', 'time to hand off',
]

const NO = [
  'how does the handover work', 'how does handover work?', "what's in the last handover", 'what is a handover', 'fix the handover bug',
  "don't hand over yet", 'do not hand over', 'no handover', 'no handover please', 'not yet, no handoff', 'never hand over',
  'why did the handover fail', 'the handover file is empty', 'explain the handover', 'review the handover code', 'show me the last handover',
  'read the handover', 'is the handover done?', 'did the handover work', 'when does the handover happen', 'which handover is newest',
  'update the handover tests', 'debug the handoff hook', 'the handover failed again', 'cancel the handover', 'skip the handover',
  'stop the handover', 'handover is broken', 'I think the handover is wrong', 'write tests for the handover mod', 'improve the handover spec',
  'if context is high, do a handover', 'after this, do a handover', 'when you are done hand over', 'refactor handover.ts', 'handover status?', 'handover summary', 'handover details please', 'handover history',
]

const LONG = 'please could you take a good look at everything we have discussed and then do a handover for me now'

describe('isHandoverRequest', () => {
  for (const s of YES) test(`yes: ${s}`, () => expect(isHandoverRequest(s)).toBe(true))
  for (const s of NO) test(`no: ${s}`, () => expect(isHandoverRequest(s)).toBe(false))
  test('there are enough cases', () => { expect(YES.length).toBeGreaterThanOrEqual(25); expect(NO.length).toBeGreaterThanOrEqual(25) })
  test('more than twelve words is talk, not a request', () => expect(isHandoverRequest(LONG)).toBe(false))
  test('twelve words is the limit', () => expect(isHandoverRequest('ok so now please can you just do a handover for me')).toBe(true))
  test('blank and unrelated text', () => {
    expect(isHandoverRequest('')).toBe(false)
    expect(isHandoverRequest('   ')).toBe(false)
    expect(isHandoverRequest('run the tests')).toBe(false)
    expect(isHandoverRequest('hand me the file')).toBe(false)
  })
  test('a slash command is not a plain request', () => expect(isHandoverRequest('/vho')).toBe(false))
})

describe('mentionsHandover', () => {
  for (const s of ['handover', 'a Handover please', 'hand over', 'handoff', 'hand off', 'handing off', 'how does handover work', 'fix the hand-over']) test(`yes: ${s}`, () => expect(mentionsHandover(s)).toBe(true))
  for (const s of ['hello', 'overhand', 'hand me that', 'run tests', '']) test(`no: ${s}`, () => expect(mentionsHandover(s)).toBe(false))
})
