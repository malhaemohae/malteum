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

export type ApiPackSummary = {
  pack_version: string;
  product?: { code?: string; name?: string; category?: 'deposit' | 'loan' };
  published_at?: string;
  item_count?: number;
  source_count?: number;
};

export type ApiEvidence = {
  doc_id: string;
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
  type?: 'required' | 'forbidden' | 'reference';
  requirement_elements?: string[];
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

export function apiUrl(path: string) {
  if (/^https?:\/\//.test(path)) return path;
  return `${apiBase}/${path.replace(/^\//, '')}`;
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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiUrl(path), {
    ...init,
    headers: { Accept: 'application/json', ...(init?.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }), ...init?.headers },
    cache: 'no-store',
  });
  const contentType = response.headers.get('content-type') || '';
  const payload = contentType.includes('application/json') ? await response.json() : await response.text();
  if (!response.ok) {
    const message = typeof payload === 'object' && payload && 'message' in payload ? String(payload.message) : `요청을 처리하지 못했습니다 (${response.status})`;
    throw new ApiError(message, response.status, payload);
  }
  return payload as T;
}

export const malteumApi = {
  health: () => request<ApiHealth>('/health'),
  presets: () => request<{ presets: Array<Record<string, unknown>> }>('/presets'),
  packs: (productCode?: string) => request<{ packs: ApiPackSummary[] }>(`/packs${productCode ? `?product_code=${encodeURIComponent(productCode)}` : ''}`),
  pack: (packVersion: string) => request<Record<string, unknown>>(`/packs/${encodeURIComponent(packVersion)}`),
  briefing: (packVersion: string, customerType: 'general' | 'professional' = 'general') => request<ApiBriefing>(`/packs/${encodeURIComponent(packVersion)}/briefing?customer_type=${customerType}`),
  createSession: (body: CreateSessionRequest) => request<CreateSessionResponse>('/sessions', { method: 'POST', body: JSON.stringify(body) }),
  sessions: (mode?: CreateSessionRequest['mode']) => request<{ sessions: ApiSessionSummary[]; next_cursor?: string | null }>(`/sessions?limit=100${mode ? `&mode=${mode}` : ''}`),
  session: (sessionId: string) => request<Record<string, unknown>>(`/sessions/${encodeURIComponent(sessionId)}`),
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
    return request<{ doc_id: string; status: 'extracting' }>('/documents', { method: 'POST', body: form });
  },
  extraction: (docId: string) => request<Record<string, unknown>>(`/documents/${encodeURIComponent(docId)}/extraction`),
  candidates: (docId: string) => request<{ candidates: ApiCandidate[] }>(`/documents/${encodeURIComponent(docId)}/candidates`),
  approveCandidate: (docId: string, candidateId: string, approvedBy: string) => request<Record<string, unknown>>(`/documents/${encodeURIComponent(docId)}/candidates/${encodeURIComponent(candidateId)}/approve`, { method: 'POST', body: JSON.stringify({ approved_by: approvedBy }) }),
};
