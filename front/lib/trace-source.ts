import { ApiError, ApiSessionSummary, apiUrl, malteumApi, wsUrl } from './api';
import { rememberedSessionIds } from './session-index';
import { isPlayableEvent, sessionEvents } from './session-recovery';

// Only exact IDs from a successful TRACE creation are retained. No transcript,
// judgement or guessed relationship is stored, and this is NOT a DB repair.
const memory = new Map<string, string>();
function sourceKey(id: string) { return `malteum.trace-source.v1:${apiUrl('')}:${wsUrl()}:${id}`; }
export function rememberTraceSource(traceId: string, sourceId: string) {
  if (!traceId || !sourceId || traceId === sourceId) return;
  const key = sourceKey(traceId); memory.set(key, sourceId);
  try { localStorage.setItem(key, sourceId); } catch { /* Still usable in this tab. */ }
}
export function rememberedTraceSource(traceId: string) {
  const key = sourceKey(traceId);
  try { return localStorage.getItem(key) || memory.get(key); } catch { return memory.get(key); }
}

export async function resolveTraceSource(record: ApiSessionSummary): Promise<ApiSessionSummary | null> {
  let current = record; const visited = new Set<string>();
  for (let depth = 0; depth < 20; depth++) {
    if (visited.has(current.session_id)) return null;
    visited.add(current.session_id);
    if (current.mode !== 'trace') return current;
    const sourceId = rememberedTraceSource(current.session_id);
    if (sourceId) {
      try { current = await malteumApi.session(sourceId); continue; }
      catch (reason) { if (!(reason instanceof ApiError) || reason.status !== 404) throw reason; }
    }
    // A TRACE with its own persisted content is valid too; mode alone is no gate.
    if ((await sessionEvents(current.session_id, true)).some(isPlayableEvent)) return current;
    return null;
  }
  return null;
}

export async function serverHistory() {
  const records = new Map<string, ApiSessionSummary>(); const seen = new Set<string>(); let cursor: string | undefined;
  do {
    const page = await malteumApi.sessions(undefined, cursor);
    for (const record of page.sessions) records.set(record.session_id, record);
    cursor = page.next_cursor ?? undefined;
    if (cursor && seen.has(cursor)) throw new Error('이력 페이지 연결이 반복됩니다. 다시 불러와 주세요.');
    if (cursor) seen.add(cursor);
  } while (cursor);
  const recovered = await Promise.allSettled(rememberedSessionIds().filter(id => !records.has(id)).map(id => malteumApi.session(id)));
  for (const result of recovered) if (result.status === 'fulfilled') records.set(result.value.session_id, result.value);
  return Array.from(records.values()).sort((a, b) => b.started_at.localeCompare(a.started_at));
}

export type TraceCandidate = { record: ApiSessionSummary; preview: string; utterances: number; playable: boolean; error?: string };
export async function traceCandidates(trace: ApiSessionSummary): Promise<TraceCandidate[]> {
  const records = (await serverHistory()).filter(record => record.mode !== 'trace' && record.status !== 'running' && record.pack_version === trace.pack_version);
  const result: TraceCandidate[] = []; let cursor = 0;
  // Bound concurrent reads, and do not silently call a failed request an empty record.
  await Promise.all(Array.from({ length: Math.min(4, records.length) }, async () => {
    while (cursor < records.length) {
      const record = records[cursor++];
      try {
        const events = await sessionEvents(record.session_id);
        const utterances = events.filter(event => event.kind === 'utterance');
        const first = utterances[0]?.utterance as { text?: string } | undefined;
        result.push({ record, preview: first?.text ?? '저장된 판정·안내 기록', utterances: utterances.length, playable: events.some(isPlayableEvent) });
      } catch { result.push({ record, preview: '', utterances: 0, playable: false, error: '기록 조회 실패 · 새로고침으로 재시도' }); }
    }
  }));
  return result.filter(candidate => candidate.playable || candidate.error).sort((a, b) => b.record.started_at.localeCompare(a.record.started_at));
}
