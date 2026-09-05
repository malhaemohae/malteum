// Retain identifiers only. Displayed summaries are always fetched from the server.
const storageKey = 'malteum.server-session-ids';
export function rememberedSessionIds(): string[] {
  try { const value: unknown = JSON.parse(localStorage.getItem(storageKey) ?? '[]'); return Array.isArray(value) ? value.filter((id): id is string => typeof id === 'string') : []; } catch { return []; }
}
export function rememberSession(id: string) {
  try { localStorage.setItem(storageKey, JSON.stringify([id, ...rememberedSessionIds().filter(value => value !== id)].slice(0,100))); } catch { /* Private storage can be unavailable; the server list remains usable. */ }
}
