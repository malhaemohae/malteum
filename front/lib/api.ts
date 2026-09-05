export type ApiHealth = {
  status: 'ok' | 'degraded';
  version?: string;
  checks?: Record<string, 'ok' | 'fail' | 'unconfigured'>;
};

export type ApiBriefing = {
  pack_version: string;
  must_say: Array<{ item_code: string; name: string; elements?: string[]; plain_language?: string[] }>;
  must_not_say: Array<{ item_code: string; name: string; examples?: string[] }>;
  documents_required?: string[];
  generated_at: string;
  cached?: boolean;
};

export type ApiSessionSummary = {
  session_id: string;
  mode: 'live' | 'replay' | 'trace' | 'text';
  pack_version: string;
  product_name?: string;
  started_at: string;
  ended_at?: string | null;
  status: 'running' | 'ended' | 'aborted' | 'timeout';
  met?: number;
  items_total?: number;
  violations?: number;
};

export type ApiSessionDetail = ApiSessionSummary & {
  duration_ms?: number;
  items?: Array<{ item_code: string; name: string; axis: string; state: string; decided_by?: string; missing_elements?: string[]; evidence_ref?: string }>;
};

export type ApiPreset = {
  preset_id: string;
  label: string;
  mode: 'live' | 'replay' | 'trace' | 'text';
  product_code: string;
  pack_version: string;
  customer_profile?: { type?: 'general' | 'professional'; tags?: string[] };
  expected_highlights?: string[];
  audio_ref?: string;
  description?: string;
};

export type ApiPackSummary = {
  pack_version: string;
  product?: { code?: string; name?: string; category?: 'deposit' | 'loan' };
  published_at?: string;
  item_count?: number;
  source_count?: number;
};

export type ApiEvidence = {
  doc_id: string;
  source_url?: string;
  doc_title?: string;
  publisher?: string;
  snapshot_date?: string;
  page: number;
  span: string;
  bbox?: [number, number, number, number];
  legal_basis?: string;
  page_image_url?: string;
  page_size?: [number, number];
  context?: string;
};

export type ApiReport = {
  session_id: string;
  pack_version: string;
  generated_at: string;
  sources?: Array<{ doc_id?: string; title?: string; publisher?: string; snapshot_date?: string }>;
  sections?: {
    summary?: Record<string, unknown>;
    omission?: Array<Record<string, unknown>>;
    commission?: Array<Record<string, unknown>>;
    comprehension?: Array<Record<string, unknown>>;
    risk_signals?: Array<Record<string, unknown>>;
    timeline?: Array<{ t_ms?: number; kind?: string; label?: string; evidence_ref?: string }>;
  };
  disclaimer?: string;
};

export type ApiDocument = {
  doc_id: string;
  title: string;
  publisher: string;
  snapshot_date: string;
  url?: string;
  page_count?: number;
  status: 'extracting' | 'ready' | 'failed';
  candidate_count?: number;
  approved_count?: number;
};

export type ApiCandidate = {
  candidate_id: string;
  suggested_code?: string;
  name: string;
  type?: 'required' | 'forbidden' | 'reference' | 'risk';
  requirement_elements?: string[];
  plain_language?: string[];
  evidence?: { page?: number; span?: string; bbox?: number[] };
  span_verified?: boolean;
  status?: 'pending' | 'approved' | 'rejected';
};

export type CreateSessionRequest = {
  mode: 'live' | 'replay' | 'trace' | 'text';
  preset_id?: string;
  product_code?: string;
  pack_version?: string;
  customer_profile?: { type?: 'general' | 'professional'; tags?: string[] };
  source_session_id?: string;
  audio_ref?: string;
};

export type CreateSessionResponse = {
  session_id: string;
  pack_version: string;
  ws_url: string;
};

export type ApiPackItem = {
  code: string; name: string; type: 'required' | 'forbidden' | 'reference' | 'risk';
  plain_language?: string[]; requirement_elements?: string[]; documents_required?: string[];
  forbidden_examples?: string[]; risk_examples?: string[];
  evidence?: { doc_id: string; page: number; span: string; bbox?: [number, number, number, number] };
  legal_basis?: { law: string; article: string }[];
  approved_by?: string; approved_at?: string;
};
export type ApiPack = ApiPackSummary & {
  items: ApiPackItem[];
  sources?: { doc_id: string; title: string; publisher: string; snapshot_date: string; url?: string }[];
};

export type AudioUploadResponse = {
  audio_ref: string;
  duration_ms: number;
};

export type PublishPackResponse = {
  pack_version: string;
  item_count: number;
  embedding_indexed?: number;
};

export type ApiEvent = Record<string, unknown> & {
  event_id?: string;
  seq_in_session?: number;
  kind?: string;
};

export type ServerMessage = {
  t: 'ready' | 'partial' | 'utterance' | 'verdict' | 'alert' | 'assist' | 'progress' | 'ended' | 'error' | 'ping';
  seq?: number;
  session_id?: string;
  pack_version?: string;
  mode?: 'live' | 'replay' | 'trace' | 'text';
  [key: string]: unknown;
};

export class ApiError extends Error {
  status: number;
  payload: unknown;

  constructor(message: string, status: number, payload?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.payload = payload;
  }
}

const apiBase = (process.env.NEXT_PUBLIC_MALTEUM_API_BASE_URL || '/api').replace(/\/$/, '');
// Runtime-only credential: never embed an administrator secret in a public JS bundle.
let runtimeAdminToken = '';
let credentialVersion = 0;
const pendingReads = new Map<string, Promise<unknown>>();
export function setAdminToken(value: string) { runtimeAdminToken = value.trim(); credentialVersion++; }
export function hasAdminToken() { return Boolean(runtimeAdminToken); }

export function apiUrl(path: string) {
  if (/^https?:\/\//.test(path)) return path;
  return `${apiBase}/${path.replace(/^\/api(?=\/)/, '').replace(/^\//, '')}`;
}

export function wsUrl(explicitUrl?: string) {
  const configured = process.env.NEXT_PUBLIC_MALTEUM_WS_URL;
  if (explicitUrl && /^wss?:\/\//.test(explicitUrl)) return explicitUrl;
  if (configured) {
    const base = configured.replace(/\/ws\/?$/, '');
    const path = explicitUrl || '/ws';
    return `${base}${path.startsWith('/') ? path : `/${path}`}`;
  }
  if (explicitUrl && typeof window !== 'undefined') return `${window.location.origin.replace(/^http/, 'ws')}${explicitUrl.startsWith('/') ? explicitUrl : `/${explicitUrl}`}`;
  if (typeof window === 'undefined') return '';
  return `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`;
}

function request<T>(path: string, init?: RequestInit, admin = false): Promise<T> {
  // Share only simultaneous, identical reads. Never cache results, share credentials,
  // coalesce mutations, or make one caller's AbortSignal cancel another caller.
  const share = (!init?.method || init.method === 'GET') && !init?.signal && !init?.headers && !init?.body;
  if (!share) return performRequest<T>(path, init, admin);
  const key = `${admin ? credentialVersion : 'public'}:${path}`;
  const pending = pendingReads.get(key);
  if (pending) return pending as Promise<T>;
  const operation = performRequest<T>(path, init, admin).finally(() => { pendingReads.delete(key); });
  pendingReads.set(key, operation);
  return operation;
}

async function performRequest<T>(path: string, init?: RequestInit, admin = false): Promise<T> {
  const response = await fetch(apiUrl(path), {
    ...init,
    signal: init?.signal ?? AbortSignal.timeout(15000),
    headers: {
      Accept: 'application/json',
      ...(init?.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...(admin && runtimeAdminToken ? { Authorization: `Bearer ${runtimeAdminToken}` } : {}),
      ...init?.headers,
    },
    cache: 'no-store',
  });
  const contentType = response.headers.get('content-type') || '';
  const payload = contentType.includes('application/json') ? await response.json() : await response.text();
  if (!response.ok) {
    const message = typeof payload === 'object' && payload && ('message' in payload || typeof payload.detail === 'string') ? String(payload.message ?? payload.detail) : `요청을 처리하지 못했습니다 (${response.status})`;
    throw new ApiError(message, response.status, payload);
  }
  return payload as T;
}

export const malteumApi = {
  health: () => request<ApiHealth>('/health'),
  presets: () => request<{ presets: ApiPreset[] }>('/presets'),
  packs: (productCode?: string) => request<{ packs: ApiPackSummary[] }>(`/packs${productCode ? `?product_code=${encodeURIComponent(productCode)}` : ''}`),
  pack: (packVersion: string) => request<ApiPack>(`/packs/${encodeURIComponent(packVersion)}`),
  briefing: (packVersion: string, customerType: 'general' | 'professional' = 'general') => request<ApiBriefing>(`/packs/${encodeURIComponent(packVersion)}/briefing?customer_type=${customerType}`),
  createSession: (body: CreateSessionRequest) => request<CreateSessionResponse>('/sessions', { method: 'POST', body: JSON.stringify(body) }),
  uploadAudio: (sessionId: string, file: File) => {
    const form = new FormData();
    form.append('file', file, file.name);
    return request<AudioUploadResponse>(`/sessions/${encodeURIComponent(sessionId)}/audio`, { method: 'POST', body: form });
  },
  sessions: (mode?: CreateSessionRequest['mode'], cursor?: string) => request<{ sessions: ApiSessionSummary[]; next_cursor?: string | null }>(`/sessions?limit=100${mode ? `&mode=${mode}` : ''}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`),
  session: (sessionId: string) => request<ApiSessionDetail>(`/sessions/${encodeURIComponent(sessionId)}`),
  events: (sessionId: string, fromSeq = 0) => request<{ session_id: string; events: ApiEvent[]; truncated?: boolean }>(`/sessions/${encodeURIComponent(sessionId)}/events?from_seq=${fromSeq}`),
  report: (sessionId: string) => request<ApiReport>(`/sessions/${encodeURIComponent(sessionId)}/report`),
  reportPdfUrl: (sessionId: string) => apiUrl(`/sessions/${encodeURIComponent(sessionId)}/report.pdf`),
  evidence: (evidenceRef: string) => request<ApiEvidence>(`/evidence/${encodeURIComponent(evidenceRef)}`),
  documents: () => request<{ documents: ApiDocument[] }>('/documents'),
  uploadDocument: (file: File, metadata: { docId: string; title?: string; publisher: string; snapshotDate: string }) => {
    const form = new FormData();
    form.append('file', file);
    form.append('doc_id', metadata.docId);
    form.append('title', metadata.title || file.name);
    form.append('publisher', metadata.publisher);
    form.append('snapshot_date', metadata.snapshotDate);
    return request<{ doc_id: string; status: 'extracting' }>('/documents', { method: 'POST', body: form }, true);
  },
  extraction: (docId: string) => request<Record<string, unknown>>(`/documents/${encodeURIComponent(docId)}/extraction`, undefined, true),
  candidates: (docId: string) => request<{ candidates: ApiCandidate[] }>(`/documents/${encodeURIComponent(docId)}/candidates`),
  approveCandidate: (docId: string, candidateId: string, approvedBy: string, edits?: { name?: string; requirement_elements?: string[]; plain_language?: string[] }) => request<Record<string, unknown>>(`/documents/${encodeURIComponent(docId)}/candidates/${encodeURIComponent(candidateId)}/approve`, { method: 'POST', body: JSON.stringify({ approved_by: approvedBy, ...(edits ? { edits } : {}) }) }, true),
  publishPack: (pack: Record<string, unknown>) => request<PublishPackResponse>('/packs/publish', { method: 'POST', body: JSON.stringify(pack) }, true),
};

export async function findSessionEvent(sessionId: string, eventId: string) {
  let cursor = 0;
  for (;;) {
    const page = await malteumApi.events(sessionId, cursor);
    const match = page.events.find(event => event.event_id === eventId);
    if (match || !page.truncated) return match;
    const next = Math.max(...page.events.map(event => Number(event.seq_in_session)));
    if (!Number.isFinite(next) || next <= cursor) throw new Error('저장 이벤트의 다음 페이지를 확인하지 못했습니다.');
    cursor = next;
  }
}
