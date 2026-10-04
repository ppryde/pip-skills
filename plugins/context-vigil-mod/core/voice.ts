// Every user-facing string, emoji-led, in one place.
export type WaitReason =
  | 'draft' | 'latched' | 'classic' | 'rc-unanswered' | 'rc-declined' | 'rc-holdback'
  | 'countdown' | 'countdown-start'

const WAIT: Record<WaitReason, string> = {
  'draft': '✍️ Handover waiting — there is a draft in your prompt box',
  'latched': '⏳ Handover waiting — the usage limit is in force',
  'classic': '🕯️ Handover skipped — classic context-vigil is active here',
  'rc-unanswered': '📱 Handover saved — auto-clear in Remote Control is not switched on (/vsetup rc)',
  'rc-declined': '📱 Handover saved — auto-clear is off for Remote Control sessions',
  'rc-holdback': '📱 Handover waiting — you were active on the phone a moment ago',
  'countdown': '🧹 Handover countdown running — send anything to cancel',
  'countdown-start': '🧹 Handing over in 30 s — send anything to cancel',
}

export const V = {
  barLine: (pct: number, threshold: number, resumes: string | null) =>
    `🕯️ context ${pct}% · threshold ${threshold}%${resumes ? ` · ⏳ resumes ${resumes}` : ''}`,
  barHandover: '📜 Hand over now',
  barLater: (next: number) => `⏰ Remind me at ${next}%`,
  barDismiss: '✖ Dismiss',
  nudge: (pct: number) => `🕯️ Context at ${pct}% — say "hand over" (or /vho) when you're ready 📜`,
  handoverSaved: (path: string) => `📜 Handover saved — ${path}`,
  handoverFailed: '📜 Couldn\'t write a handover — nothing was cleared',
  clearRejected: '🧹 /clear was refused — the handover is still pending; /clear to resume from it',
  countdownLine: (s: number) => `🧹 Handing over in ${s} s — 0 or send anything to cancel`,
  cancel: '✖ Cancel',
  rcAsk: '📱 First Remote Control session with auto mode — one quick question about auto-clear',
  setupUsage: '⚙️ /vsetup [nudge|bar|auto|last-light|limits|rc] — that step name is not one of these',
  countdownCancelled: '🧹 Handover countdown cancelled — the handover is saved; /clear to resume from it',
  pendingOffer: (path: string) => `📜 A handover is waiting (${path}) — /clear to resume from it`,
  waiting: (r: WaitReason) => WAIT[r],
  lastLightReady: '🌅 Last light: a handover is ready 📜 — carry on as normal, or /clear to resume from it ✨',
  lastLightAsk: '🌅 A handover is ready — resume from it (cheap) or carry on with the full conversation (pays the cold cache)?',
  lastLightResume: 'Resume from handover',
  lastLightCarryOn: 'Carry on',
  limitLatched: (hhmm: string) => `⏳ Usage limit reached — resumes ${hhmm}; I won't clear or prompt until then`,
  limitCleared: '⏳ Usage limit lifted — back to normal',
  earlyStop: (kind: string, pct: number, hhmm: string) =>
    `⏳ ${kind} at ${pct}% — handover written; I'll resume after the reset (${hhmm}) if this session is still open`,
  classicActive: '🕯️ Classic context-vigil is active here — context-vigil-mod is standing down',
  setupSaved: '⚙️ context-vigil-mod settings saved',
  handingOver: '📜 Handing over…',
  settingUp: '⚙️ Setting up context-vigil-mod…',
  cmdHandover: '📜 Hand over now (context-vigil-mod)',
  cmdSetup: '⚙️ context-vigil-mod setup — /vsetup [nudge|bar|auto|last-light|limits|rc]',
}
