// TEMPORARY: exists only for the side-by-side run with classic context-vigil.
// Removed (with classicSessionPath in name.ts) when classic retires — spec §7.
// Keep in step with the grep -E pattern in scripts/install.sh (same match, bash form).
const CLASSIC = /\/scripts\/context-vigil"\s+hook\s/

export function classicHooksInstalled(settingsText: string | null): boolean {
  if (!settingsText) return false
  let data: unknown
  try { data = JSON.parse(settingsText) } catch { return false }
  const hooks = (data as { hooks?: unknown })?.hooks
  if (!hooks || typeof hooks !== 'object') return false
  for (const entries of Object.values(hooks as Record<string, unknown>)) {
    if (!Array.isArray(entries)) continue
    for (const entry of entries) {
      const list = (entry as { hooks?: unknown })?.hooks
      if (!Array.isArray(list)) continue
      for (const h of list) {
        const cmd = (h as { command?: unknown })?.command
        if (typeof cmd === 'string' && CLASSIC.test(cmd)) return true
      }
    }
  }
  return false
}
