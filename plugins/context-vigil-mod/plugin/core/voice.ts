// Every user-facing string, emoji-led, in one place.
export type WaitReason =
  | 'draft' | 'latched' | 'classic' | 'rc-unanswered' | 'rc-declined' | 'rc-holdback'
  | 'countdown' | 'countdown-start'

const WAIT: Record<WaitReason, string> = {
  'draft': '✍️ Handover waiting — there is a draft in your prompt box',
  'latched': '⏳ Handover waiting — the usage limit is in force',
  'classic': '🕯️ Handover skipped — classic context-vigil is active here',
  'rc-unanswered': '📱 Handover saved — auto-clear in Remote Control is not switched on (/vigil-setup rc)',
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
  lastLightOff: '🌅 Last light is off for this session — 5-minute prompt cache (/vigil-setup last-light)',
  lastLightBackOn: '🌅 Last light is back on — 1-hour prompt cache',
  nudge: (pct: number) => `🕯️ Context at ${pct}% — say "hand over" (or /vho) when you're ready 📜`,
  handoverSaved: (path: string) => `📜 Handover saved — ${path}`,
  clearSkippedAttended: '📜 Handover saved — you came back, so nothing was cleared; /vho or /clear when you are ready',
  clearSkippedAutoOff: '📜 Handover saved — auto mode was switched off, so nothing was cleared; /vho or /clear when you are ready',
  handoverUnrequested: (path: string) => `📜 Handover saved — ${path} — it was not asked for, so nothing was cleared; /vho or /clear when you want to use it`,
  deferredDropped: '⏳ The handover that waited on the usage limit was not run — /vho when you want one',
  handoverInterrupted: '📜 Handover interrupted — nothing was cleared; /vho when you want one',
  resumeStale: (path: string) => `📜 Handover injected (${path}) — it was written before later turns, so no automatic resume; say where to pick up`,
  injectedNoResume: (path: string) => `📜 Handover injected (${path}) — it asks for no automatic resume, so say where to pick up`,
  resumeLatched: (path: string) => `⏳ Handover injected (${path}) — the usage limit is in force, so the resume prompt was not sent; ask to resume when it lifts`,
  handoverInProgress: '📜 A handover is already in progress — one at a time',
  resumeSkipped: (path: string | null) =>
    `⏳ The limit has reset — you are back, so no resume was sent; ${path ? `the handover is at ${path}` : 'no handover was written'}`,
  handoverLost: '📜 The earlier handover instruction never completed — starting again',
  handoverFailed: '📜 Couldn\'t write a handover — nothing was cleared',
  clearRejected: '🧹 /clear was refused — the handover is still pending; /clear to resume from it',
  countdownLine: (s: number) => `🧹 Handing over in ${s} s — 0 or send anything to cancel`,
  cancel: '✖ Cancel',
  rcAsk: '📱 First Remote Control session with auto mode — one quick question about auto-clear',
  setupUsage: '⚙️ /vigil-setup [nudge|bar|auto|last-light|limits|rc] — that step name is not one of these',
  countdownCancelled: '🧹 Handover countdown cancelled — the handover is saved; /clear to resume from it',
  pendingOffer: (path: string) => `📜 A handover is waiting (${path}) — /clear to resume from it`,
  waiting: (r: WaitReason) => WAIT[r],
  lastLightReady: '🌅 Last light: a handover is ready 📜 — carry on as normal, or /clear to resume from it ✨',
  lastLightAsk: '🌅 A handover is ready — resume from it (cheap) or carry on with the full conversation (pays the cold cache)?',
  lastLightResume: '📜 Resume from handover',
  lastLightCarryOn: '💬 Carry on',
  limitLatched: (hhmm: string) => `⏳ Usage limit reached — resumes ${hhmm}; I won't clear or prompt until then`,
  limitCleared: '⏳ Usage limit lifted — back to normal',
  earlyStop: (kind: string, pct: number, hhmm: string) =>
    `⏳ ${kind} at ${pct}% — handover written; I'll resume after the reset (${hhmm}) if this session is still open`,
  classicActive: '🕯️ Classic context-vigil is active here — context-vigil-mod is standing down',
  setupSaved: '⚙️ context-vigil-mod settings saved',
  setupStopped: '⚙️ Setup stopped — what you answered is saved; /vigil-setup to finish',
  handingOver: '📜 Handing over…',
  handoverRequested: '📜 Handing over — as /vho',
  settingUp: '⚙️ Setting up context-vigil-mod…',
  renameFailed: '🏷️ couldn\'t name the new session — carrying on',
  resumeFailed: (path: string | null, held: string | null) =>
    `▶️ Couldn't resume${path ? ` — the handover is at ${path}` : ''}${held ? ` — your message was not sent: ${held}` : ''}`,
  heldNotSent: (held: string) => `🌅 Your held message was not sent: ${held}`,
  heldForLastLight: '🌅 Held by context-vigil-mod — last light asks first',
  cmdHandover: '📜 Hand over now (context-vigil-mod)',
  cmdSetup: '⚙️ context-vigil-mod setup — /vigil-setup [nudge|bar|auto|last-light|limits|rc]',
  cmdHandoverShort: '📜 Hand over now — short for /vigil-handover (context-vigil-mod)',
  cmdOverrides: '🔧 Thresholds per model or window — /vigil-overrides [add|rm|check]',
  overridesUsage: '🔧 /vigil-overrides lists and checks · /vigil-overrides add asks for an override · /vigil-overrides rm model=… window=… (either or both) · or edit overrides.json by hand',
  overridesNoOverride: (key: string) => `🔧 No override for ${key} — /vigil-overrides lists them`,
  overridesUnwritable: '🔧 Couldn\'t write overrides.json — nothing changed',
  overridesAdding: '🔧 Adding an override…',
  overridesStopped: '🔧 Override not added — nothing changed',
  overridesNothingSet: '🔧 Every value was left to inherit, so the override would set nothing — not added',
  overridesBadKey: (text: string) => `🔧 "${text}" is not an override key — try model=opus5.5 window=1m (either or both); nothing changed`,
  // Lists arrive as ready lines, one per entry, so every entry here takes strings and numbers only.
  overridesMigrated: (path: string, moved: string, kept: string, dropped: string) =>
    `🔧 Thresholds set with the old /vsetup models moved to ${path}:\n${moved || '  (none)'}${kept ? `\n  already in the file for the same key, which stays in force: ${kept}` : ''}${dropped ? `\n  not carried over: ${dropped}` : ''}\n/vigil-overrides lists them`,
  overridesFileFault: (path: string, fault: string, kept: string) =>
    `🔧 ${path} can't be read (${fault}); until it is fixed these stay in force:\n${kept}`,
  overridesFaults: (path: string, count: number, lines: string) =>
    `🔧 ${path} has ${count === 1 ? 'a fault' : `${count} faults`}; those overrides are ignored until fixed:\n${lines}`,
  overridesAmbiguous: (model: string, window: string, values: string, both: string) =>
    `🔧 ${model} and ${window} both match this session; the window wins (${values}). A ${both} override would settle it — /vigil-overrides add`,
  overridesList: (path: string, overrides: string, fallback: string, session: string, values: string, warnings: string) =>
    `🔧 Overrides${path ? ` (${path})` : ''}, tried most specific first:\n${overrides || '  (no overrides)'}\n  otherwise → ${fallback}\nThis session (${session}): ${values}${warnings ? `\n${warnings}` : ''}`,
}
