import { ApiEvidence, ApiPack, ApiPackItem, ApiPackSummary, ServerMessage } from './api';

export type Screen = 'landing' | 'briefing' | 'dashboard' | 'playback' | 'report' | 'history' | 'packs' | 'documents';
export type Mode = 'live' | 'text' | 'replay' | 'trace';
export function sessionScreen(mode: Mode): 'dashboard' | 'playback' { return mode === 'live' || mode === 'text' ? 'dashboard' : 'playback'; }
export type NavItem = '상담' | '리포트' | '기준 관리' | '규정 팩' | '문서' | '이력';
export type ReadyItem = { code: string; name: string; state: string; plain: string[]; missing: string[]; evidenceRef?: string; decidedBy?: string };
export type Intervention = { id: string; key: string; kind: string; text: string; evidenceRef?: string; said?: string; reference?: string; condition?: string; priority: number; alert: boolean };
export type LiveSession = {
  id: string; wsUrl: string; sourceSessionId?: string; mode: Mode; packVersion: string; status: 'connecting' | 'connected' | 'disconnected' | 'ended';
  seq: number; items: ReadyItem[]; transcript: { id: string; speaker: string; text: string; t_ms: number }[];
  partial: string; interventions: Intervention[]; versions: Record<string, number>; seen: string[];
  progress?: { met: number; partial: number; total: number; density?: string };
  error?: string; textFallback?: boolean; ending: boolean; reportUrl?: string; seconds: number;
  traceHasUtterances?: boolean;
  // TRACE only: alert event ids whose stored record is already acknowledged. Saves one REST read per alert.
  acknowledgedAlertIds?: string[];
  // Newest judgement that carried evidence. The guide panel shows it while no intervention is open.
  recentEvidence?: { ref: string; itemCode: string; name: string };
  query?: { question: string; answer?: string; evidenceRef?: string; pending: boolean };
  action?: { kind: string; itemCode?: string; ref?: string; pending: boolean; message: string; result?: { text: string; evidenceRef?: string } };
};

export const statusNames: Record<string, string> = { met: '고지', partial: '부분 고지', unmet: '미고지', waived: '제외', clean: '이상 없음', suspected: '검토 필요', violated: '위반', adopted: '채택', ignored: '미채택', pending: '대기', approved: '승인', rejected: '반려', running: '진행 중', ended: '종료', aborted: '중단', timeout: '시간 만료' };
export const itemTypeNames: Record<string, string> = { required: '필수 안내', forbidden: '금지 표현', reference: '참고', risk: '위험 신호' };
export const kindNames: Record<string, string> = { risk_signal: '위험 신호', forbidden_phrase: '금지 표현', number_mismatch: '숫자 확인', rephrase: '쉬운 말 안내', answer: '규정 답변', nudge: '미고지 안내', briefing: '상담 기준', documents: '필요 서류', term_density: '전문용어 밀도' };
// Format protocol metadata only; never rewrite quoted speech/evidence or numbers.
export const severityNames: Record<string, string> = { critical: '심각', high: '높음', medium: '보통', low: '낮음', info: '참고' };
// Modes are protocol values; tellers see Korean words, never the wire codes.
export const modeNames: Record<Mode, string> = { live: '실시간', text: '텍스트', replay: '음원 시연', trace: '기록 재생' };
const metadataNames: Record<string, string> = { ...statusNames, ...kindNames, ...severityNames, ...modeNames, confirmed: '이해 확인 신호', explained: '설명됨', teller: '상담원', customer: '고객', human: '상담원 수동 기록', L1: '규칙 판정', L2: '문맥 판정', L3: '추가 검토 판정', verdict: '판정', utterance: '발화', alert: '경보', assist: '상담 안내', session_started: '상담 시작', session_ended: '상담 종료', omission: '설명 이행', commission: '금지·숫자', comprehension: '이해 지원', low: '낮음', normal: '보통', high: '높음' };
export function displayValue(value: unknown, key = ''): string {
  if (Array.isArray(value)) return value.map(entry => displayValue(entry, key)).join('\n');
  if (value && typeof value === 'object') return Object.entries(value).map(([field, entry]) => `${displayField(field)}: ${displayValue(entry, field)}`).join('\n');
  if (value == null) return '미제공';
  if (typeof value === 'boolean') return key === 'acknowledged' ? (value ? '확인함' : '확인 안 함') : value ? '예' : '아니오';
  if (typeof value === 'number' && MS_FIELDS.includes(key)) return timeLabel(value / 1000);
  if (typeof value !== 'string') return String(value);
  if (TIME_FIELDS.includes(key)) return whenLabel(value);
  if (key === 'label') return value.replace(/^(teller|customer|rephrase|answer|nudge|briefing|documents|number_mismatch|forbidden_phrase|risk_signal|term_density):\s*/, (_, type) => `${metadataNames[type]}: `).replace(/(→\s*)(met|partial|unmet|waived|clean|suspected|violated|confirmed|explained|adopted|ignored)\b/g, (_, arrow, state) => `${arrow}${state === 'met' ? '고지 완료' : metadataNames[state]}`);
  if (['state', 'final_state', 'outcome', 'status', 'kind', 'type', 'axis', 'decided_by', 'speaker', 'assist_type', 'alert_type', 'severity', 'mode'].includes(key)) return metadataNames[value] ?? value;
  return value;
}
export function displayField(key: string) { return fieldNames[key] ?? key; }
export const whenLabel = (iso: string) => {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  // 날짜만 온 값에 오전 12시를 붙이면 없는 정보를 지어내는 것이다
  const withTime = /\d{2}:\d{2}/.test(iso);
  return date.toLocaleString('ko-KR', withTime ? { month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit' } : { year: 'numeric', month: 'long', day: 'numeric' });
};
// Server error strings are terse and lean on acronyms. Say the same thing the way the screen already does.
export const STT_UNCONFIGURED = '음성 전사 서버가 설정되지 않았습니다. 녹음은 되지만 전사·판정에는 STT(음성을 글자로 바꾸는 서비스) 설정이 필요합니다.';
export const friendlyError = (message?: string) => !message ? '' : /STT/.test(message) && /설정/.test(message) ? STT_UNCONFIGURED : message;
export const timeLabel = (seconds: number) => `${Math.floor(seconds / 60).toString().padStart(2, '0')}:${Math.floor(seconds % 60).toString().padStart(2, '0')}`;
export const errorText = (error: unknown) => error instanceof Error ? error.name === 'TimeoutError' || error.name === 'AbortError' ? '서버 응답이 지연되고 있습니다. 연결을 확인한 뒤 다시 시도해 주세요.' : error.message : '요청을 처리하지 못했습니다.';
export const textValue = (value: unknown): string => value == null ? '' : typeof value === 'object' ? Array.isArray(value) ? value.map(textValue).join(' · ') : Object.entries(value).map(([key, entry]) => `${fieldNames[key] ?? key}: ${textValue(entry)}`).join('\n') : String(value);
// 화면에 나가는 필드 이름은 여기 한 곳에서만 정한다. 사전이 갈리면 새 필드가 영문 그대로 샌다
export const fieldNames: Record<string, string> = { item_code: '항목 코드', name: '항목', state: '상태', final_state: '최종 상태', ver: '판정 버전', decided_by: '판정 출처', missing_elements: '미충족 요소', evidence: '근거', t_ms: '시각', text: '발화', message: '안내', reason: '사유', outcome: '결과', acknowledged: '확인 기록', alert_type: '경보 유형', assist_type: '안내 유형', type: '유형', met: '고지', partial: '부분 고지', unmet: '미고지', waived: '제외', violations: '위반', alerts: '경보', items_total: '필수 항목', total_utterances: '발화 수', duration_ms: '상담 시간', assist_adopted: '안내 채택', assists_adopted: '채택한 안내', started_at: '시작 시각', ended_at: '종료 시각', summary: '요약', status: '상태', page: '페이지', span: '인용 원문', doc_id: '문서', doc_title: '문서명', legal_basis: '법적 근거', severity: '중요도', comparison: '비교', said: '발화 값', reference: '기준 값', condition: '조건', count: '건수', timestamp: '시각', label: '변경 내용', kind: '기록 유형', axis: '검토 항목', speaker: '화자', title: '문서명', publisher: '발행 기관', snapshot_date: '기준일', url: '원문 주소', pack_version: '규정 팩 버전', session_id: '상담 번호', mode: '입력 방식', required: '필수 여부', trigger: '안내 계기', approved_at: '승인 시각', approved_by: '승인자', product_name: '상품', product: '상품', category: '분류', code: '항목 코드', item_count: '항목 수', published_at: '발행 시각', source_count: '원천 문서 수', waive_reason: '제외 사유' };
// 밀리초로 오는 값. 초 단위 mm:ss 로 바꿔 보여 준다
const MS_FIELDS = ['t_ms', 'duration_ms'];
// ISO 시각으로 오는 값. 은행원이 읽는 날짜·시각으로 바꾼다
const TIME_FIELDS = ['started_at', 'ended_at', 'published_at', 'approved_at', 'snapshot_date', 'timestamp', 'occurred_at'];
// 서버 내부 식별자. 화면에서 할 수 있는 일이 없으므로 기록 상세에 줄로 남기지 않는다
export const INTERNAL_FIELDS = ['event_id', 'evidence_ref', 'utterance_id', 'source_utterance_ref', 'supersedes'];

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
      if (message.axis === 'omission' && typeof message.evidence_ref === 'string') next.recentEvidence = { ref: message.evidence_ref, itemCode: String(message.item_code), name: current.items.find(item => item.code === message.item_code)?.name ?? String(message.item_code) };
      if (message.axis === 'omission') next.items = current.items.map(item => item.code === message.item_code ? { ...item, state: String(message.state), missing: Array.isArray(message.missing_elements) ? message.missing_elements.map(String) : [], evidenceRef: typeof message.evidence_ref === 'string' ? message.evidence_ref : item.evidenceRef, decidedBy: typeof message.decided_by === 'string' ? message.decided_by : undefined } : item);
      if (current.action?.pending && ['mark_met', 'mark_waived'].includes(current.action.kind) && current.action.itemCode === message.item_code && message.decided_by === 'human') next.action = { ...current.action, pending: false, message: '수동 변경이 서버에 저장됐습니다.' };
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
    if (current.action?.kind === 'rephrase' && kind === 'rephrase' && (current.action.itemCode == null || current.action.itemCode === message.item_code)) next.action = { ...current.action, pending: false, itemCode: typeof message.item_code === 'string' ? message.item_code : current.action.itemCode, message: current.action.itemCode == null ? '직전 발화를 쉬운 말로 바꿨습니다.' : '쉬운 말이 상담 기록에 남았습니다.', result: { text, evidenceRef: reference } };
    if (current.action?.kind === 'acknowledge' && message.acknowledged === true && current.action.pending && current.action.ref === message.acknowledged_ref) next.action = { ...current.action, pending: false, message: '확인 기록이 서버에 저장됐습니다.' };
  }
  if (message.t === 'progress') next.progress = { met: Number(message.met), partial: Number(message.partial ?? 0), total: Number(message.items_total), density: typeof message.term_density === 'string' ? message.term_density : undefined };
  if (message.t === 'error') {
    const reason = String(message.message ?? '서버 처리 오류');
    // 서버 오류에는 어느 요청에 대한 것인지가 없다. 배너에 반드시 남기고,
    // 기다리던 요청은 모두 함께 풀어 준다. 하나만 풀면 나머지가 15초 뒤 헛된
    // 지연 안내로 끝난다.
    next.error = reason;
    if (current.query?.pending) next.query = { ...current.query, pending: false, answer: reason };
    if (current.action?.pending) next.action = { ...current.action, pending: false, message: reason };
  }
  if (message.t === 'ended') { next.status = 'ended'; next.ending = false; next.reportUrl = typeof message.report_url === 'string' ? message.report_url : undefined; }
  return next;
}

// Catalogs show only the newest pack per product. Historical sessions retain their
// pinned version so original evidence and reports remain reproducible.
export function latestPacks<T extends ApiPackSummary>(packs: T[]): T[] {
  const newest = new Map<string, T>();
  for (const pack of packs) {
    const key = pack.product?.code ?? pack.product?.name ?? pack.pack_version;
    const current = newest.get(key);
    if (!current || comparePacks(pack, current) > 0) newest.set(key, pack);
  }
  return Array.from(newest.values());
}
function comparePacks(a: ApiPackSummary, b: ApiPackSummary) {
  const timestamp = (value?: string) => { const parsed = Date.parse(value ?? ''); return Number.isFinite(parsed) ? parsed : 0; };
  const byDate = timestamp(a.published_at) - timestamp(b.published_at);
  return byDate !== 0 ? byDate : a.pack_version.localeCompare(b.pack_version, undefined, { numeric: true });
}

export function evidenceForItem(pack: ApiPack, item: ApiPackItem): ApiEvidence | null {
  if (!item.evidence) return null;
  const source = pack.sources?.find(source => source.doc_id === item.evidence?.doc_id);
  return { ...item.evidence, source_url: source?.url, doc_title: source?.title, publisher: source?.publisher, snapshot_date: source?.snapshot_date, legal_basis: item.legal_basis?.map(value => `${value.law} ${value.article}`).join(' · '), page_image_url: `/api/documents/${encodeURIComponent(item.evidence.doc_id)}/pages/${item.evidence.page}.png` };
}
