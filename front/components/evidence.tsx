'use client';

import { CSSProperties, PointerEvent, ReactNode, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { ApiEvidence, apiUrl, malteumApi } from '../lib/api';
import { Empty } from './workspace';

// The document viewer: opens on the cited page zoomed to the highlighted span, then lets the
// reader zoom out to the whole page and walk to neighbouring pages of the same document.
// Nothing here judges or rewrites evidence; it only shows what the server returned.

const ZOOM_MAX = 4, ZOOM_STEP = 1.3;
type Rect = { x: number; y: number; w: number; h: number };

export function sourceUrl(value?: string) { try { const parsed = new URL(value ?? ''); return ['https:', 'http:'].includes(parsed.protocol) ? parsed.href : undefined; } catch { return undefined; } }

// PDF bboxes use points with the origin at the bottom-left; the page image has its origin at the
// top-left. Everything is expressed as a fraction of the page so it survives any render scale.
export function highlightRect(evidence: Pick<ApiEvidence, 'bbox' | 'page_size'>, fallbackSize?: [number, number]): Rect | null {
  const size = evidence.page_size ?? fallbackSize; const box = evidence.bbox;
  if (!size || !box || size[0] <= 0 || size[1] <= 0) return null;
  const [x1, y1, x2, y2] = box; const [pw, ph] = size;
  return { x: x1 / pw, y: (ph - y2) / ph, w: Math.max((x2 - x1) / pw, 0.002), h: Math.max((y2 - y1) / ph, 0.002) };
}
function pageRatio(evidence: Pick<ApiEvidence, 'page_size'>, natural: { width: number; height: number } | null) {
  if (natural && natural.width > 0) return natural.height / natural.width;
  if (evidence.page_size && evidence.page_size[0] > 0) return evidence.page_size[1] / evidence.page_size[0];
  return Math.SQRT2; // A4 until the image tells us otherwise
}
function pageImageUrl(docId: string, page: number, scale: number, retry = 0) { const base = apiUrl(`/documents/${encodeURIComponent(docId)}/pages/${page}.png${scale === 2 ? "" : `?scale=${scale}`}`); return retry ? `${base}${base.includes("?") ? "&" : "?"}retry=${retry}` : base; }
// The canvas width is `zoom` times the viewport width, so a whole page fits only when the
// resulting height also fits. Anything larger crops the page and calling that "whole page" lies.
function fitZoom(viewport: { width: number; height: number }, ratio: number) {
  if (viewport.width <= 0 || viewport.height <= 0 || ratio <= 0) return 1;
  return Math.min(1, viewport.height / (viewport.width * ratio));
}
// Zoom so the highlighted span fills about half of the viewport width without cutting its height.
function focusZoom(rect: Rect | null, viewport: { width: number; height: number }, ratio: number) {
  // Never zoom out past a whole page: below that the reader loses the sheet and gains nothing.
  const floor = fitZoom(viewport, ratio);
  if (!rect || viewport.width <= 0 || viewport.height <= 0) return Math.max(floor, 1.6);
  const byWidth = 0.55 / rect.w; const byHeight = (0.45 * viewport.height) / (rect.h * viewport.width * ratio);
  return Math.min(ZOOM_MAX, Math.max(floor, Math.min(byWidth, byHeight)));
}

// --- shared caches: evidence by ref, page counts by document --------------------------------
const EVIDENCE_CACHE_LIMIT = 256;
const evidenceCache = new Map<string, Promise<ApiEvidence>>();
export function loadEvidence(ref: string) {
  const existing = evidenceCache.get(ref);
  if (existing) { evidenceCache.delete(ref); evidenceCache.set(ref, existing); return existing; }
  let pending: Promise<ApiEvidence>;
  pending = malteumApi.evidence(ref).catch(error => { if (evidenceCache.get(ref) === pending) evidenceCache.delete(ref); throw error; });
  evidenceCache.set(ref, pending);
  while (evidenceCache.size > EVIDENCE_CACHE_LIMIT) {
    const oldest = evidenceCache.keys().next().value;
    if (typeof oldest !== 'string') break;
    evidenceCache.delete(oldest);
  }
  return pending;
}
export function useEvidence(ref?: string) {
  const [state, setState] = useState<{ ref?: string; loading: boolean; value?: ApiEvidence; error?: string }>({ ref, loading: Boolean(ref) });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!ref) { setState({ ref, loading: false }); return; }
    let active = true; setState({ ref, loading: true });
    loadEvidence(ref).then(value => { if (active) setState({ ref, loading: false, value }); }).catch(error => { if (active) setState({ ref, loading: false, error: error instanceof Error ? error.message : '근거를 불러오지 못했습니다.' }); });
    return () => { active = false; };
  }, [ref, attempt]);
  const current = state.ref === ref ? state : { ref, loading: Boolean(ref) };
  return { ...current, retry: () => setAttempt(value => value + 1) };
}
let pageCounts: Promise<Map<string, number>> | null = null;
function loadPageCounts() {
  if (!pageCounts) pageCounts = malteumApi.documents().then(result => new Map(result.documents.filter(doc => typeof doc.page_count === 'number').map(doc => [doc.doc_id, doc.page_count as number]))).catch(() => { pageCounts = null; return new Map<string, number>(); });
  return pageCounts;
}
function usePageCount(docId: string) {
  const [count, setCount] = useState<number | undefined>();
  useEffect(() => { let active = true; setCount(undefined); loadPageCounts().then(map => { if (active) setCount(map.get(docId)); }); return () => { active = false; }; }, [docId]);
  return count;
}

// --- the page canvas: one image, one highlight, arbitrary zoom ------------------------------
function PageCanvas({ docId, page, zoom, rect, ratio, onNatural, onError, retry = 0, interactive = true, viewportRef, children }: { docId: string; page: number; zoom: number; rect: Rect | null; ratio: number; onNatural?: (size: { width: number; height: number; scale: number }) => void; onError?: () => void; retry?: number; interactive?: boolean; viewportRef: React.RefObject<HTMLDivElement>; children?: ReactNode }) {
  const scale = zoom >= 2.4 ? 4 : zoom >= 1.4 ? 3 : 2;
  const drag = useRef<{ x: number; y: number; left: number; top: number } | null>(null);
  function down(event: PointerEvent<HTMLDivElement>) { if (!interactive || event.button !== 0) return; const host = viewportRef.current; if (!host) return; drag.current = { x: event.clientX, y: event.clientY, left: host.scrollLeft, top: host.scrollTop }; host.setPointerCapture(event.pointerId); host.dataset.dragging = 'true'; }
  function move(event: PointerEvent<HTMLDivElement>) { const host = viewportRef.current; const start = drag.current; if (!host || !start) return; host.scrollLeft = start.left - (event.clientX - start.x); host.scrollTop = start.top - (event.clientY - start.y); }
  function up(event: PointerEvent<HTMLDivElement>) { const host = viewportRef.current; drag.current = null; if (host) { delete host.dataset.dragging; if (host.hasPointerCapture(event.pointerId)) host.releasePointerCapture(event.pointerId); } }
  return <div className="wb-ev-viewport" ref={viewportRef} data-interactive={interactive} onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up}>
    <div className="wb-ev-canvas" style={{ width: `${zoom * 100}%`, aspectRatio: `1 / ${ratio}` } as CSSProperties}>
      <img src={pageImageUrl(docId, page, scale, retry)} alt={`${docId} ${page}페이지`} draggable={false} onLoad={event => onNatural?.({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight, scale })} onError={onError} />
      {rect && <span className="wb-ev-highlight" style={{ left: `${rect.x * 100}%`, top: `${rect.y * 100}%`, width: `${rect.w * 100}%`, height: `${rect.h * 100}%` }} />}
      {children}
    </div>
  </div>;
}

// --- full viewer (modal body) ----------------------------------------------------------------
export function EvidenceView({ value }: { value: ApiEvidence }) {
  const viewport = useRef<HTMLDivElement>(null);
  const [page, setPage] = useState(value.page);
  const [zoom, setZoom] = useState(1);
  // width: the default. The sheet fits side to side, so nothing scrolls horizontally.
  // focus: zoom into the highlight. page: the whole sheet. free: whatever the buttons left.
  const [mode, setMode] = useState<'width' | 'focus' | 'page' | 'free'>('width');
  const [natural, setNatural] = useState<{ width: number; height: number; scale: number } | null>(null);
  const [imageError, setImageError] = useState(false);
  const [imageRetry, setImageRetry] = useState(0);
  const [viewportSize, setViewportSize] = useState({ width: 0, height: 0 });
  const pageCount = usePageCount(value.doc_id);
  const ratio = pageRatio(value, natural);
  const renderScale = zoom >= 2.4 ? 4 : zoom >= 1.4 ? 3 : 2;
  const rect = useMemo(() => highlightRect(value, natural ? [natural.width / natural.scale, natural.height / natural.scale] : undefined), [value, natural, renderScale]);
  const onEvidencePage = page === value.page;
  useEffect(() => { setPage(value.page); setMode('width'); setImageError(false); }, [value]);
  useEffect(() => { setImageError(false); }, [page]);
  useLayoutEffect(() => {
    const host = viewport.current; if (!host) return;
    // The dialog lays out after this effect runs, so a one-off read returns 0 and every
    // zoom mode below bails out. Observe the element itself instead of the window.
    const observer = new ResizeObserver(([entry]) => setViewportSize(current =>
      current.width === entry.contentRect.width && current.height === entry.contentRect.height
        ? current : { width: entry.contentRect.width, height: entry.contentRect.height }));
    observer.observe(host); return () => observer.disconnect();
  }, []);
  // Focus centres the highlight; page fits one sheet in the viewport. Both need a measured host.
  useLayoutEffect(() => {
    const host = viewport.current; if (!host || viewportSize.width === 0) return;
    if (mode === 'width') {
      setZoom(1);
      // Width already fits; only the vertical position has to find the quote.
      const canvasHeight = viewportSize.width * ratio;
      const centre = rect && onEvidencePage ? rect.y + rect.h / 2 : 0;
      host.scrollTo({ left: 0, top: Math.max(0, centre * canvasHeight - viewportSize.height / 2), behavior: 'auto' });
    }
    if (mode === 'focus' && onEvidencePage) {
      const next = focusZoom(rect, viewportSize, ratio); setZoom(next);
      const canvasWidth = viewportSize.width * next; const canvasHeight = canvasWidth * ratio;
      const centre = rect ? { x: rect.x + rect.w / 2, y: rect.y + rect.h / 2 } : { x: 0.5, y: 0.2 };
      host.scrollTo({ left: Math.max(0, centre.x * canvasWidth - viewportSize.width / 2), top: Math.max(0, centre.y * canvasHeight - viewportSize.height / 2), behavior: 'auto' });
    }
    if (mode === 'page') { setZoom(fitZoom(viewportSize, ratio)); host.scrollTo({ left: 0, top: 0 }); }
  }, [mode, onEvidencePage, rect, ratio, viewportSize, page]);
  function stepZoom(direction: 1 | -1) {
    const host = viewport.current;
    const floor = fitZoom(viewportSize, ratio);
    const next = Math.min(ZOOM_MAX, Math.max(floor, direction > 0 ? zoom * ZOOM_STEP : zoom / ZOOM_STEP));
    if (host && viewportSize.width > 0) {
      // Keep the point at the centre of the viewport where it is while the canvas grows.
      const factor = next / zoom; const cx = host.scrollLeft + viewportSize.width / 2; const cy = host.scrollTop + viewportSize.height / 2;
      requestAnimationFrame(() => host.scrollTo({ left: cx * factor - viewportSize.width / 2, top: cy * factor - viewportSize.height / 2 }));
    }
    setZoom(next); setMode('free');
  }
  // 페이지 수를 아직 모르면 다음 장이 있는지도 모른다. 앞으로는 못 가게 막는다.
  function go(next: number) { if (next < 1 || (pageCount ? next > pageCount : next > page)) return; setPage(next); if (next !== value.page) { setMode('page'); } else setMode('focus'); }
  const url = sourceUrl(value.source_url);
  return <div className="wb-ev" onKeyDown={event => { if (event.key === 'ArrowLeft') go(page - 1); if (event.key === 'ArrowRight') go(page + 1); }}>
    <aside className="wb-ev-side">
      <div className="wb-ev-doc"><strong>{value.doc_title ?? value.doc_id}</strong><small>{[value.publisher, value.snapshot_date ? `${value.snapshot_date} 기준` : null].filter(Boolean).join(' · ')}</small></div>
      <div className="wb-ev-quote"><span className="wb-ev-label">근거 문장 · p.{value.page}</span><blockquote>{value.span}</blockquote>
        {value.legal_basis && <><span className="wb-ev-label">법적 근거</span><p>{value.legal_basis}</p></>}
        {value.context && <><span className="wb-ev-label">문맥</span><p>{value.context}</p></>}
      </div>
      {url && <a className="wb-ev-source" href={url} target="_blank" rel="noopener noreferrer">출처 원문 열기 ↗</a>}
    </aside>
    <section className="wb-ev-main" aria-label="원문 페이지">
      <div className="wb-ev-toolbar">
        <div className="wb-ev-pager" role="group" aria-label="페이지 이동">
          <button type="button" aria-label="이전 페이지" disabled={page <= 1} onClick={() => go(page - 1)}>‹</button>
          <span>p.{page}{pageCount ? ` / ${pageCount}` : ''}</span>
          <button type="button" aria-label="다음 페이지" disabled={!pageCount || page >= pageCount} onClick={() => go(page + 1)}>›</button>
          {!onEvidencePage && <button type="button" className="wb-ev-back" onClick={() => go(value.page)}>근거 위치로 (p.{value.page})</button>}
        </div>
        <div className="wb-ev-zoom" role="group" aria-label="확대">
          <button type="button" aria-pressed={mode === 'width'} onClick={() => setMode('width')}>폭 맞춤</button>
          <button type="button" aria-pressed={mode === 'focus'} disabled={!onEvidencePage} onClick={() => setMode('focus')}>근거 확대</button>
          <button type="button" aria-pressed={mode === 'page'} onClick={() => setMode('page')}>전체 페이지</button>
          <button type="button" aria-label="축소" disabled={zoom <= fitZoom(viewportSize, ratio) + 0.001} onClick={() => stepZoom(-1)}>－</button>
          <span>{Math.round(zoom * 100)}%</span>
          <button type="button" aria-label="확대" disabled={zoom >= ZOOM_MAX} onClick={() => stepZoom(1)}>＋</button>
        </div>
      </div>
      <div className="wb-ev-stage" onDoubleClick={() => setMode(mode === 'focus' ? 'width' : 'focus')}>
      {imageError ? <div className="wb-ev-image-error"><Empty>p.{page} 이미지를 불러오지 못했습니다. 인용 문장은 왼쪽에서 계속 확인할 수 있습니다.<button type="button" onClick={() => { setImageError(false); setImageRetry(value => value + 1); }}>이미지 다시 불러오기</button></Empty></div>
        : <PageCanvas docId={value.doc_id} page={page} zoom={zoom} rect={onEvidencePage ? rect : null} ratio={ratio} viewportRef={viewport} onNatural={setNatural} retry={imageRetry} onError={() => setImageError(true)} />}
      </div>
      <small className="wb-ev-hint">{onEvidencePage ? '형광펜이 근거 문장입니다. 두 번 누르면 그 자리를 확대하고, 끌어서 주변을 봅니다.' : '근거가 아닌 페이지입니다. 원문 문맥 확인용으로만 보세요.'}</small>
    </section>
  </div>;
}

// --- compact card for the guide panel --------------------------------------------------------
export function EvidenceCard({ title, evidenceRef, evidence, onOpen }: { title?: string; evidenceRef?: string; evidence?: ApiEvidence | null; onOpen: () => void }) {
  const fetched = useEvidence(evidence ? undefined : evidenceRef);
  const value = evidence ?? (fetched.ref === evidenceRef ? fetched.value : undefined);
  const viewport = useRef<HTMLDivElement>(null);
  const [natural, setNatural] = useState<{ width: number; height: number; scale: number } | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [failed, setFailed] = useState(false);
  const [imageRetry, setImageRetry] = useState(0);
  const ratio = value ? pageRatio(value, natural) : Math.SQRT2;
  const rect = value ? highlightRect(value, natural ? [natural.width / natural.scale, natural.height / natural.scale] : undefined) : null;
  const zoom = focusZoom(rect, size, ratio);
  // A stale page from the previous evidence must not decide this card's aspect ratio.
  useEffect(() => { setNatural(null); setFailed(false); }, [value?.doc_id, value?.page]);
  // Without a measured viewport the zoom stays at its default and the card shows the page top.
  useLayoutEffect(() => {
    const host = viewport.current; if (!host) return;
    const observer = new ResizeObserver(([entry]) => setSize(current => current.width === entry.contentRect.width && current.height === entry.contentRect.height ? current : { width: entry.contentRect.width, height: entry.contentRect.height }));
    observer.observe(host); return () => observer.disconnect();
  }, [value]);
  useLayoutEffect(() => {
    const host = viewport.current; if (!host || size.width === 0) return;
    const canvasWidth = size.width * zoom; const canvasHeight = canvasWidth * ratio;
    const centre = rect ? { x: rect.x + rect.w / 2, y: rect.y + rect.h / 2 } : { x: 0.5, y: 0.15 };
    host.scrollTo({ left: Math.max(0, centre.x * canvasWidth - size.width / 2), top: Math.max(0, centre.y * canvasHeight - size.height / 2) });
  }, [rect, ratio, size, zoom, value]);
  if (!evidenceRef && !evidence) return null;
  if (fetched.loading && !value) return <div className="wb-ev-card is-loading"><span className="wb-ev-label">{title ?? '근거'}</span><Empty>근거를 불러오고 있습니다.</Empty></div>;
  if (!value) return <div className="wb-ev-card is-loading"><span className="wb-ev-label">{title ?? '근거'}</span><Empty>{fetched.error ? <>{fetched.error}<button type="button" onClick={fetched.retry}>근거 다시 불러오기</button></> : '이 안내에는 연결된 근거가 없습니다.'}</Empty></div>;
  if (failed) return <div className="wb-ev-card is-error" role="button" tabIndex={0} onClick={onOpen} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') onOpen(); }}><span className="wb-ev-card-head"><span className="wb-ev-label">{title ?? '근거'}</span><small>{value.doc_title ?? value.doc_id} · p.{value.page}</small></span><Empty>페이지 이미지를 불러오지 못했습니다.<button type="button" onClick={event => { event.stopPropagation(); setFailed(false); setImageRetry(value => value + 1); }}>이미지 다시 불러오기</button></Empty><span className="wb-ev-card-quote">{value.span}</span></div>;
  return <button type="button" className="wb-ev-card" onClick={onOpen} aria-label={`근거 원문 열기 · ${value.doc_title ?? value.doc_id} ${value.page}페이지`}>
    <span className="wb-ev-card-head"><span className="wb-ev-label">{title ?? '근거'}</span><small>{value.doc_title ?? value.doc_id} · p.{value.page}</small></span>
    <span className="wb-ev-card-preview">{failed ? <Empty>페이지 이미지를 불러오지 못했습니다.</Empty> : <PageCanvas docId={value.doc_id} page={value.page} zoom={zoom} rect={rect} ratio={ratio} viewportRef={viewport} interactive={false} retry={imageRetry} onNatural={setNatural} onError={() => setFailed(true)} />}</span>
    <span className="wb-ev-card-quote">{value.span}</span>
    <span className="wb-ev-card-cta">원문에서 주변 문맥 보기 →</span>
  </button>;
}
