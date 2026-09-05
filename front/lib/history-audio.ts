import type { ApiEvent, ApiSessionSummary } from './api';
import { rememberedReplayPreset } from './session-index';

// The existing public session_started event is the persisted source of identity.
// A product/pack or matching sentence alone is not proof of a recording's origin.
export function historyAudioPreset(record: ApiSessionSummary, events: ApiEvent[]): string | null {
  if (record.mode !== 'replay') return null;
  const ids = new Set<string>();
  for (const event of events) {
    if (event.kind !== 'session_started') continue;
    const body = event.session_started as { preset_id?: unknown } | undefined;
    if (typeof body?.preset_id === 'string' && body.preset_id.trim()) ids.add(body.preset_id);
  }
  if (ids.size > 1) return null;
  return ids.size === 1 ? Array.from(ids)[0] : rememberedReplayPreset(record.session_id) ?? null;
}
