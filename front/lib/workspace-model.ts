import { ApiEvidence, ApiPack, ApiPackItem, ServerMessage } from './api';

export type Screen = 'landing' | 'briefing' | 'dashboard' | 'report' | 'history' | 'packs' | 'documents';
export type Mode = 'live' | 'text' | 'replay' | 'trace';
export type NavItem = '상담' | '리포트' | '기준 관리' | '규정 팩' | '문서' | '이력';
export type ReadyItem = { code: string; name: string; state: string; plain: string[]; missing: string[]; evidenceRef?: string; decidedBy?: string };
export type Intervention = { id: string; key: string; kind: string; text: string; evidenceRef?: string; said?: string; reference?: string; condition?: string; priority: number; alert: boolean };
export type LiveSession = {
  id: string; wsUrl: string; sourceSessionId?: string; mode: Mode; packVersion: string; status: 'connecting' | 'connected' | 'disconnected' | 'ended';
  seq: number; items: ReadyItem[]; transcript: { id: string; speaker: string; text: string; t_ms: number }[];
  partial: string; interventions: Intervention[]; versions: Record<string, number>; seen: string[];
  progress?: { met: number; partial: number; total: number; density?: string };
  error?: string; textFallback?: boolean; ending: boolean; reportUrl?: string; seconds: number;
  query?: { question: string; answer?: string; evidenceRef?: string; pending: boolean };
};

export const statusNames: Record<string, string> = { met: '고지', partial: '부분 고지', unmet: '미고지', waived: '제외', clean: '이상 없음', suspected: '검토 필요', violated: '위반', adopted: '채택', ignored: '미채택', pending: '대기', approved: '승인', rejected: '반려', running: '진행 중', ended: '종료', aborted: '중단', timeout: '시간 만료' };
export const kindNames: Record<string, string> = { risk_signal: '위험 신호', forbidden_phrase: '금지 표현', number_mismatch: '숫자 확인', rephrase: '쉬운 말 안내', answer: '규정 답변', nudge: '미고지 안내', briefing: '상담 기준', documents: '필요 서류', term_density: '전문용어 밀도' };
export const timeLabel = (seconds: number) => `${Math.floor(seconds / 60).toString().padStart(2, '0')}:${Math.floor(seconds % 60).toString().padStart(2, '0')}`;
export const errorText = (error: unknown) => error instanceof Error ? error.name === 'TimeoutError' || error.name === 'AbortError' ? '서버 응답이 지연되고 있습니다. 연결을 확인한 뒤 다시 시도해 주세요.' : error.message : '요청을 처리하지 못했습니다.';
export const textValue = (value: unknown): string => value == null ? '' : typeof value === 'object' ? Array.isArray(value) ? value.map(textValue).join(' · ') : Object.entries(value).map(([key, entry]) => `${fieldNames[key] ?? key}: ${textValue(entry)}`).join('\n') : String(value);
export const fieldNames: Record<string, string> = { item_code: '항목 코드', name: '항목', state: '상태', final_state: '최종 상태', ver: '판정 버전', decided_by: '판정 출처', missing_elements: '미충족 요소', evidence_ref: '근거 참조', evidence: '근거', t_ms: '시각(ms)', text: '발화', message: '안내', reason: '사유', outcome: '결과', acknowledged: '확인 기록', alert_type: '경보 유형', assist_type: '안내 유형', utterance_id: '발화 참조', type: '유형', met: '고지', partial: '부분 고지', unmet: '미고지', waived: '제외', violations: '위반', alerts: '경보', items_total: '필수 항목', total_utterances: '발화 수', duration_ms: '상담 시간(ms)', assist_adopted: '안내 채택', started_at: '시작 시각', ended_at: '종료 시각', summary: '요약', status: '상태', page: '페이지', span: '인용 원문', doc_id: '문서', doc_title: '문서명', legal_basis: '법적 근거', severity: '중요도', comparison: '비교', said: '발화 값', reference: '기준 값', condition: '조건', event_id: '이벤트 참조', count: '건수', timestamp: '시각' };

export function newLiveSession(id: string, wsUrl: string, mode: Mode, packVersion: string): LiveSession {
  return { id, wsUrl, mode, packVersion, status: 'connecting', seq: -1, items: [], transcript: [], partial: '', interventions: [], versions: {}, seen: [], ending: false, seconds: 0 };
}

// Only server events change judgements. No local keyword scoring or synthetic fallback.
export function reduceServer(current: LiveSession, message: ServerMessage): LiveSession {
  if (typeof message.seq === 'number' && message.seq <= current.seq && !['ready', 'verdict', 'assist'].includes(message.t)) return current;
  const eventId = String(message.event_id ?? '');
  if (eventId && current.seen.includes(eventId)) return current;
  const next = { ...current, seq: Math.max(current.seq, message.seq ?? -1), seen: eventId ? [...current.seen, eventId] : current.seen };
  if (message.t === 'ready') {
    next.status = 'connected'; next.error = undefined;
    next.packVersion = String(message.pack_version ?? current.packVersion);
    next.items = (Array.isArray(message.items) ? message.items as Record<string, unknown>[] : []).filter(item => item.required !== false && item.axis === 'omission').map(item => {
      const previous = current.items.find(entry => entry.code === item.item_code);
      return { ...previous, code: String(item.item_code), name: String(item.name ?? item.item_code), state: String(item.state ?? previous?.state ?? 'unmet'), plain: Array.isArray(item.plain_language) ? item.plain_language.map(String) : previous?.plain ?? [], missing: previous?.missing ?? [] };
    });
  }
  if (message.t === 'partial') next.partial = String(message.text ?? '');
  if (message.t === 'utterance') {
    next.partial = ''; const t_ms = Number(message.t_ms ?? 0);
    next.seconds = Math.max(current.seconds, t_ms / 1000);
    next.transcript = [...current.transcript, { id: eventId, speaker: String(message.speaker), text: String(message.text ?? ''), t_ms }];
  }
  if (message.t === 'verdict') {
    const key = `${message.item_code}:${message.axis}`; const ver = Number(message.ver ?? 0);
    if (ver > (current.versions[key] ?? -1)) {
      next.versions = { ...current.versions, [key]: ver };
      if (message.axis === 'omission') next.items = current.items.map(item => item.code === message.item_code ? { ...item, state: String(message.state), missing: Array.isArray(message.missing_elements) ? message.missing_elements.map(String) : [], evidenceRef: typeof message.evidence_ref === 'string' ? message.evidence_ref : item.evidenceRef, decidedBy: typeof message.decided_by === 'string' ? message.decided_by : undefined } : item);
    }
  }
  if (message.t === 'alert' || message.t === 'assist') {
    const kind = String(message.alert_type ?? message.assist_type); const key = `${kind}:${message.item_code ?? ''}`;
    const ver = Number(message.ver ?? 0); const versionKey = `assist:${key}`;
    if (message.t === 'assist' && ver <= (current.versions[versionKey] ?? -1)) return next;
    if (message.t === 'assist') next.versions = { ...current.versions, [versionKey]: ver };
    const remaining = current.interventions.filter(item => item.key !== key);
    const reference = typeof message.evidence_ref === 'string' ? message.evidence_ref : undefined;
    // Answer text without an evidence reference is never presented as a grounded answer.
    const text = kind === 'answer' && !reference ? '연결된 근거가 없어 답변을 표시할 수 없습니다.' : String(message.message ?? message.text ?? '');
    if (message.acknowledged === true || message.outcome === 'adopted' || message.outcome === 'ignored') next.interventions = remaining;
    else if (kind !== 'term_density') {
      const comparison = (message.comparison ?? {}) as Record<string, unknown>;
      const priority = ({ risk_signal: 0, forbidden_phrase: 1, number_mismatch: 2, rephrase: 3, answer: 4, nudge: 5, documents: 6, briefing: 6 } as Record<string, number>)[kind] ?? 7;
      const intervention: Intervention = { id: eventId, key, kind, text, priority, alert: message.t === 'alert', evidenceRef: reference, said: typeof comparison.said === 'string' ? comparison.said : undefined, reference: typeof comparison.reference === 'string' ? comparison.reference : undefined, condition: typeof comparison.condition === 'string' ? comparison.condition : undefined };
      next.interventions = [...remaining, intervention].sort((a, b) => a.priority - b.priority);
    }
    if (kind === 'answer') next.query = { question: current.query?.question ?? '', answer: text, evidenceRef: reference, pending: false };
  }
  if (message.t === 'progress') next.progress = { met: Number(message.met), partial: Number(message.partial ?? 0), total: Number(message.items_total), density: typeof message.term_density === 'string' ? message.term_density : undefined };
  if (message.t === 'error') { next.error = String(message.message ?? '서버 처리 오류'); next.query = current.query?.pending ? { ...current.query, pending: false, answer: '요청을 처리하지 못했습니다. 다시 요청해 주세요.' } : current.query; }
  if (message.t === 'ended') { next.status = 'ended'; next.ending = false; next.reportUrl = typeof message.report_url === 'string' ? message.report_url : undefined; }
  return next;
}

export function evidenceForItem(pack: ApiPack, item: ApiPackItem): ApiEvidence | null {
  if (!item.evidence) return null;
  const source = pack.sources?.find(source => source.doc_id === item.evidence?.doc_id);
  return { ...item.evidence, doc_title: source?.title, publisher: source?.publisher, snapshot_date: source?.snapshot_date, legal_basis: item.legal_basis?.map(value => `${value.law} ${value.article}`).join(' · '), page_image_url: `/api/documents/${encodeURIComponent(item.evidence.doc_id)}/pages/${item.evidence.page}.png` };
}
