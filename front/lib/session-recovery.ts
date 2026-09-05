import { ApiEvent, ApiPack, ApiSessionDetail, ApiSessionSummary, malteumApi, ServerMessage } from './api';
import { LiveSession, newLiveSession } from './workspace-model';

export type HistoryAction = 'report' | 'resume' | 'trace';

// hello binds a new transport to an existing ID. resume is only sent AFTER ready.
// A replayed ready must not recursively trigger another resume.
export function sessionHandshake(active: Pick<LiveSession, 'id' | 'mode' | 'seq'>, recover: boolean, customer: 'general' | 'professional') {
  let pending = recover || active.seq >= 0;
  return {
    hello: { t: 'hello', session_id: active.id, mode: active.mode, ...(!pending ? { customer_profile: { type: customer, tags: [] } } : {}) },
    ready(message: ServerMessage) {
      if (!pending || message.t !== 'ready') return { message, resume: undefined };
      pending = false;
      return {
        message: { ...message, seq: undefined },
        resume: { t: 'resume', session_id: active.id, from_seq: Math.max(0, active.seq) },
      };
    },
  };
}

export function traceBlockedReason(record: ApiSessionSummary) {
  if (record.status === 'running') return '상담을 종료하면 TRACE를 재생할 수 있습니다.';
  if (record.mode === 'trace') return 'TRACE 이력이 아닌 원본 상담에서 재생해 주세요.';
  return '';
}

export async function sessionEvents(sessionId: string, stopWhenPlayable = false): Promise<ApiEvent[]> {
  const events = new Map<string, ApiEvent>(); let cursor = 0;
  for (;;) {
    const page = await malteumApi.events(sessionId, cursor);
    for (const event of page.events) events.set(String(event.event_id ?? event.seq_in_session), event);
    if (!page.truncated || (stopWhenPlayable && page.events.some(isPlayableEvent))) return Array.from(events.values());
    const next = Math.max(...page.events.map(event => Number(event.seq_in_session)));
    if (!Number.isFinite(next) || next <= cursor) throw new Error('저장 이벤트의 다음 페이지를 확인하지 못했습니다.');
    cursor = next;
  }
}

export function isPlayableEvent(event: ApiEvent) {
  return ['utterance', 'verdict', 'alert', 'assist'].includes(String(event.kind));
}

// Restore only server-provided judgements and verbatim transcript records.
// Persisted event sequence numbers are NOT WebSocket resume sequence numbers.
export function recoveredSession(detail: ApiSessionDetail, pack: ApiPack, events: ApiEvent[]) {
  const active = newLiveSession(detail.session_id, '/ws', detail.mode, detail.pack_version);
  active.items = (detail.items ?? []).filter(item => item.axis === 'omission').map(item => ({
    code: item.item_code, name: item.name, state: item.state, missing: item.missing_elements ?? [],
    evidenceRef: item.evidence_ref, decidedBy: item.decided_by,
    plain: pack.items.find(entry => entry.code === item.item_code)?.plain_language ?? [],
  }));
  active.transcript = events.filter(event => event.kind === 'utterance').flatMap(event => {
    const value = event.utterance as { speaker?: string; text?: string; t_ms?: number } | undefined;
    return value && typeof value.text === 'string' && typeof value.t_ms === 'number'
      ? [{ id: String(event.event_id), speaker: String(value.speaker), text: value.text, t_ms: value.t_ms }] : [];
  });
  active.seen = active.transcript.map(entry => entry.id);
  active.seconds = Math.max(0, (detail.duration_ms ?? 0) / 1000, ...active.transcript.map(entry => entry.t_ms / 1000));
  return active;
}
