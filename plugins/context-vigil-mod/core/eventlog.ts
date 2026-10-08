import type { EventKind, EventRecord } from '../types'

export function dayKey(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10)
}

export function makeRecord(ms: number, session: string, kind: EventKind, fields: Record<string, unknown>): EventRecord {
  return { ...fields, ts: new Date(ms).toISOString(), session, kind }
}

export function appendLine(existing: string, rec: EventRecord): string {
  const base = existing === '' || existing.endsWith('\n') ? existing : `${existing}\n`
  return `${base}${JSON.stringify(rec)}\n`
}
