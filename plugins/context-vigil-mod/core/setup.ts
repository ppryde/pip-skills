import type { Settings, StepId, Window } from '../types'

export const TELL = 'Tell me more'

export type Question = {
  header: string
  question: string
  multiSelect: boolean
  options: { label: string; description: string }[]
}

type Opt = { label: string; description: string; apply: (s: Settings) => Settings }
type Step = {
  header: string
  question: string
  explain: string
  options: Opt[]
  multiSelect?: true
  other?: (s: Settings, text: string) => Settings | null
  askIf: (s: Settings) => boolean
}

const pctOpts = (key: 'nudgeAt' | 'lastLightAt', values: number[], rec: number): Opt[] =>
  values.map(n => ({ label: `${n}%`, description: n === rec ? 'Recommended' : '', apply: s => ({ ...s, [key]: n }) }))
const onOff = (key: 'bar' | 'auto' | 'lastLight' | 'limits', recommendOn: boolean, onFirst: boolean): Opt[] => {
  const on: Opt = { label: 'On', description: recommendOn ? 'Recommended' : '', apply: s => ({ ...s, [key]: true }) }
  const off: Opt = { label: 'Off', description: recommendOn ? '' : 'Recommended', apply: s => ({ ...s, [key]: false }) }
  return onFirst ? [on, off] : [off, on]
}
const always = () => true
const WINDOW_LABEL: Record<Window, string> = { seven_day: 'Weekly (seven_day)', spend_limit: 'Spend cap (spend_limit)' }

export const STEPS: Record<StepId, Step> = {
  nudge: {
    header: '🎚️ Nudge at', question: 'Big contexts get slower and pricier. At what % should I suggest a handover?',
    explain: 'The vigil bar shows in the terminal when context reaches this level, and again every +5%. Lower means earlier, smaller handovers. Terminal only. Default 35%.',
    options: pctOpts('nudgeAt', [25, 35, 50], 35), askIf: always,
  },
  bar: {
    header: '🎛️ The bar', question: "Show a one-line bar above the prompt when it's time to hand over?",
    explain: '1 hand over · 2 remind me at +5% · 0 dismiss. A bare digit typed into an empty prompt presses it, so the bar only shows from the threshold until you pick. Off = a notice line instead. Default On.',
    options: onOff('bar', true, true), askIf: always,
  },
  auto: {
    header: '🤖 Auto mode', question: "While you're away and I'm still working, may I hand over, clear and carry on by myself?",
    explain: 'Auto mode arms only when you have sent nothing for the idle window and the agent is still working on its own; any message from you disarms it at once. Default Off.',
    options: onOff('auto', false, false), askIf: always,
  },
  idle: {
    header: '⏱️ Idle time', question: "Auto handovers pause while you're interacting. How long without a message from you before I treat the session as unattended?",
    explain: 'Messages, slash commands and typing in the terminal all count as you being here. Pick longer if you flit between windows. Default 30 min.',
    options: [15, 30, 60].map(n => ({ label: `${n} min`, description: { 15: 'You step away properly when you leave', 30: 'Recommended', 60: 'You flit between windows and come back later' }[n] ?? '', apply: (s: Settings) => ({ ...s, idleMin: n }) })),
    askIf: s => s.auto,
  },
  last_light: {
    header: '🌅 Lastlight', question: "When we're both idle, write a handover just before the 1-hour cache expires, so coming back is cheap?",
    explain: 'Works only with a 1-hour prompt cache: Just before I would act I check which one your session writes, and stay off for a 5-minute cache (or if I cannot tell) rather than warm a cold one. When you and the agent are both idle, a few minutes before that cache expires I write a handover — nothing is cleared. When you come back I ask: resume from it cheaply, or carry on and pay the cold cache. Default Off.',
    options: onOff('lastLight', false, false), askIf: always,
  },
  last_light_at: {
    header: '🌅 Threshold', question: 'Only bother when context is at least…?',
    explain: 'Below this, a cold cache is cheap enough not to bother. Default 25%.',
    options: pctOpts('lastLightAt', [25, 35, 50], 25), askIf: s => s.lastLight,
  },
  limits: {
    header: '⏳ Limits', question: 'Near a 7-day or spend limit, stop early with a handover so no work is lost?',
    explain: 'Near the limit I write a handover and arrange to resume after the reset if this session stays open. The 5-hour limit is left to Claude Code\'s own wrap-up and auto-continue. Default On.',
    options: onOff('limits', true, true), askIf: always,
  },
  limit_pct: {
    header: '⏳ Trigger %', question: 'Stop at what % of the limit?',
    explain: 'Higher squeezes more work in; lower leaves more room for the handover itself. Type any whole number under Other. Default 95%.',
    options: [90, 95, 98].map(n => ({ label: n === 95 ? '95% (Recommended)' : `${n}%`, description: '', apply: (s: Settings) => ({ ...s, limitPct: n }) })),
    other: (s, text) => {
      const n = Number.parseInt(text, 10)
      return Number.isFinite(n) && n >= 1 && n <= 100 ? { ...s, limitPct: n } : null
    },
    askIf: s => s.limits,
  },
  limit_windows: {
    header: '⏳ Windows', question: 'Which limits should I watch?',
    explain: 'seven_day is the weekly window; spend_limit is a gateway or monthly spend cap. Pick either or both. Default both.',
    options: (['seven_day', 'spend_limit'] as Window[]).map(w => ({ label: WINDOW_LABEL[w], description: '', apply: (s: Settings) => s })),
    multiSelect: true, askIf: s => s.limits,
  },
  rc: {
    header: '📱 RC clear', question: "I can't see you typing on the phone, so a clear could land mid-message. Allow auto-clear in phone sessions?",
    explain: 'Your phone\'s typing is invisible to me, so a clear could land while you write. With Yes, a 30-second countdown runs first (send anything to cancel) and I never clear within 2 minutes of your last phone message. Default No.',
    options: [
      { label: 'No', description: 'Recommended', apply: s => ({ ...s, rcAutoClear: 'no' }) },
      { label: 'Yes', description: 'With countdown and holdback', apply: s => ({ ...s, rcAutoClear: 'yes' }) },
    ],
    askIf: () => false,
  },
}

export const FLOW: StepId[] = ['nudge', 'bar', 'auto', 'idle', 'last_light', 'last_light_at', 'limits', 'limit_pct', 'limit_windows']

export const ALIASES: Record<string, StepId[]> = {
  nudge: ['nudge'], bar: ['bar'], auto: ['auto', 'idle'], 'last-light': ['last_light', 'last_light_at'],
  limits: ['limits', 'limit_pct', 'limit_windows'], rc: ['rc'],
}

export function questionFor(id: StepId, explain = false): Question {
  const st = STEPS[id]
  return {
    header: st.header,
    question: explain ? `${st.explain}\n\n${st.question}` : st.question,
    multiSelect: st.multiSelect === true,
    options: [...st.options.map(o => ({ label: o.label, description: o.description })), { label: TELL, description: 'Explain this step, then ask again' }],
  }
}

// A dependant is never asked in the same card as its parent: the parent's answer decides it.
const PARENT: Partial<Record<StepId, StepId>> = {
  idle: 'auto', last_light_at: 'last_light', limit_pct: 'limits', limit_windows: 'limits',
}

export function isStep(alias: string): boolean {
  return Object.hasOwn(ALIASES, alias)
}

export function nextCard(s: Settings, asked: StepId[], only?: string): StepId[] {
  const pool = only === undefined ? FLOW : isStep(only) ? (ALIASES[only] ?? []) : []
  const explicit = only !== undefined
  const card: StepId[] = []
  for (const id of pool) {
    if (card.length === 4) break
    if (asked.includes(id)) continue
    if (!(STEPS[id].askIf(s) || (explicit && (id === 'rc' || pool[0] === id)))) continue
    const parent = PARENT[id]
    if (parent !== undefined && card.includes(parent)) continue
    card.push(id)
  }
  return card
}

// AskUserQuestion answers: on the tool input (answers collected by the permission
// component) or on the result ({ questions, answers }). PROBES.md §3 says which.
export function extractAnswers(input: unknown, result: unknown): Record<string, string> {
  const pick = (v: unknown): Record<string, string> | null => {
    if (!v || typeof v !== 'object') return null
    const out: Record<string, string> = {}
    for (const [k, a] of Object.entries(v as Record<string, unknown>)) if (typeof a === 'string') out[k] = a
    return Object.keys(out).length ? out : null
  }
  const fromInput = pick((input as { answers?: unknown } | null)?.answers)
  if (fromInput) return fromInput
  const res = (result as { result?: { answers?: unknown } } | null | undefined)?.result
  return pick(res?.answers) ?? {}
}

export function stepForQuestion(text: string): StepId | undefined {
  return (Object.keys(STEPS) as StepId[]).find(id => text === STEPS[id].question || text.endsWith(`\n\n${STEPS[id].question}`))
}

export function applyAnswers(s: Settings, pairs: { step: StepId; answer: string }[]): { settings: Settings; retell: StepId[] } {
  let out: Settings = { ...s, limitWindows: [...s.limitWindows] }
  const retell: StepId[] = []
  for (const { step, answer } of pairs) {
    const st = STEPS[step]
    if (st.multiSelect) {
      const picked = answer.split(',').map(x => x.trim()).filter(Boolean)
      if (picked.includes(TELL)) { retell.push(step); continue }
      const order: Window[] = ['seven_day', 'spend_limit']
      out = { ...out, limitWindows: order.filter(w => picked.includes(w) || picked.includes(WINDOW_LABEL[w])) }
      continue
    }
    if (answer === TELL) { retell.push(step); continue }
    const opt = st.options.find(o => o.label === answer)
    if (opt) { out = opt.apply(out); continue }
    const viaOther = st.other?.(out, answer) ?? null
    if (viaOther) { out = viaOther; continue }
    retell.push(step)
  }
  return { settings: out, retell }
}
