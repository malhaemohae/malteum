'use client';

import { DependencyList, ReactNode, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { ApiEvidence, apiUrl } from '../lib/api';
import { errorText, NavItem, Screen } from '../lib/workspace-model';
import { WorkspaceIcon, WorkspaceIconName } from './workspace-icons';

export function Workbench({ screen, title, subtitle, actions, onNavigate, onNew, children }: { screen: Screen; title: string; subtitle?: string; actions?: ReactNode; onNavigate: (nav: NavItem) => void; onNew: () => void; children: ReactNode }) {
  const links: { label: NavItem; active: boolean; icon: WorkspaceIconName }[] = [
    { label: '상담', active: ['briefing', 'dashboard'].includes(screen), icon: 'conversation' },
    { label: '리포트', active: screen === 'report', icon: 'document' },
    { label: '이력', active: screen === 'history', icon: 'history' },
    { label: '기준 관리', active: ['packs', 'documents'].includes(screen), icon: 'book' },
  ];
  return <div className="wb wb-service" data-workspace={screen}>
    <aside className="wb-sidebar"><a href="#" className="wb-brand" aria-label="말틈 홈" onClick={event => { event.preventDefault(); onNew(); }}><img src="/assets/malteum-logo.png" alt="말틈" /></a>
      <nav aria-label="주 메뉴">{links.map(link => <button key={link.label} type="button" aria-current={link.active ? 'page' : undefined} onClick={() => onNavigate(link.label)}><span aria-hidden="true"><WorkspaceIcon name={link.icon} /></span>{link.label}</button>)}</nav>
      <button className="wb-new" type="button" onClick={onNew}>＋ 새 상담</button>
    </aside>
    <main className="wb-main"><header className="wb-heading"><div><h1>{title}</h1>{subtitle && <p title={subtitle}>{subtitle}</p>}</div><div className="wb-actions">{actions}</div></header><div className="wb-body">{children}</div></main>
  </div>;
}

export function Panel({ title, action, className = '', children }: { title?: string; action?: ReactNode; className?: string; children: ReactNode }) {
  return <section className={`wb-panel ${className}`}>{(title || action) && <header className="wb-panel-head"><h2>{title}</h2>{action}</header>}<div className="wb-panel-body">{children}</div></section>;
}
export function Empty({ children }: { children: ReactNode }) { return <div className="wb-empty">{children}</div>; }
export function Notice({ children, action }: { children?: ReactNode; action?: ReactNode }) { return children ? <div className="wb-notice" role="status"><span>{children}</span>{action}</div> : null; }
export function Tabs<T extends string>({ value, items, onChange }: { value: T; items: { value: T; label: string }[]; onChange: (value: T) => void }) {
  return <div className="wb-tabs" role="group" aria-label="화면 선택">{items.map(item => <button type="button" key={item.value} aria-pressed={value === item.value} onClick={() => onChange(item.value)}>{item.label}</button>)}</div>;
}

export function useResource<T>(loader: () => Promise<T>, dependencies: DependencyList = []) {
  const [data, setData] = useState<T | null>(null); const [error, setError] = useState(''); const [loading, setLoading] = useState(true); const [version, refresh] = useState(0);
  useEffect(() => { let active = true; setLoading(true); setData(null); setError(''); loader().then(value => { if (active) setData(value); }).catch(reason => { if (active) setError(errorText(reason)); }).finally(() => { if (active) setLoading(false); }); return () => { active = false; }; }, [...dependencies, version]); // Each caller supplies all loader inputs.
  return { data, error, loading, refresh: () => refresh(value => value + 1) };
}

function Pager({ page, count, onChange, label }: { page: number; count: number; onChange: (page: number) => void; label: string }) {
  return <div className="wb-pager" aria-label={`${label} 페이지`}><button type="button" aria-label={`${label} 이전 페이지`} disabled={page <= 0} onClick={() => onChange(page - 1)}>‹</button><span>{page + 1} / {Math.max(1, count)}</span><button type="button" aria-label={`${label} 다음 페이지`} disabled={page >= count - 1} onClick={() => onChange(page + 1)}>›</button></div>;
}

// The capacity follows the available pane, not an arbitrary breakpoint or hidden overflow.
export function PagedList<T>({ items, render, label, empty = '표시할 항목이 없습니다.', rowHeight = 66, followLatest = false }: { items: T[]; render: (item: T, index: number) => ReactNode; label: string; empty?: string; rowHeight?: number; followLatest?: boolean }) {
  const ref = useRef<HTMLDivElement>(null); const [capacity, setCapacity] = useState(1); const [height, setHeight] = useState(rowHeight); const [page, setPage] = useState(0); const following = useRef(followLatest);
  useLayoutEffect(() => { if (!ref.current) return; const observer = new ResizeObserver(([entry]) => { const effective = rowHeight + (entry.contentRect.width < 520 ? 16 : 0); setHeight(effective); setCapacity(Math.max(1, Math.floor((entry.contentRect.height - 38) / effective))); }); observer.observe(ref.current); return () => observer.disconnect(); }, [rowHeight]);
  const count = Math.max(1, Math.ceil(items.length / capacity)); const visiblePage = Math.min(page, count - 1);
  useEffect(() => { if (followLatest && following.current) setPage(count - 1); else setPage(value => Math.min(value, count - 1)); }, [count, items.length, followLatest]);
  return <div className="wb-list" ref={ref} data-paged-list={label}><div className="wb-list-rows">{items.length ? items.slice(visiblePage * capacity, (visiblePage + 1) * capacity).map((item, index) => <div className="wb-list-row" style={{ height, minHeight: height }} key={visiblePage * capacity + index}>{render(item, visiblePage * capacity + index)}</div>) : <Empty>{empty}</Empty>}</div><div className="wb-list-bottom"><small>{items.length}개</small>{followLatest && !following.current && <button type="button" onClick={() => { following.current = true; setPage(count - 1); }}>최신 발화</button>}<Pager label={label} page={visiblePage} count={count} onChange={value => { following.current = value === count - 1; setPage(value); }} /></div></div>;
}

// Paginate exact text using its rendered dimensions. Nothing is silently truncated.
export function TextPages({ text, label = '내용' }: { text: string; label?: string }) {
  const container = useRef<HTMLDivElement>(null); const probe = useRef<HTMLDivElement>(null);
  const [pages, setPages] = useState<string[]>([text]); const [page, setPage] = useState(0);
  useLayoutEffect(() => {
    if (!container.current || !probe.current) return;
    const measure = () => {
      const host = container.current; const node = probe.current; if (!host || !node || host.clientWidth === 0 || host.clientHeight < 20) return;
      node.style.width = `${host.clientWidth}px`; const available = host.clientHeight;
      const parts: string[] = []; let rest = text;
      while (rest.length) {
        let lo = 1, hi = rest.length, fits = 1;
        while (lo <= hi) { const mid = Math.floor((lo + hi) / 2); node.textContent = rest.slice(0, mid); if (node.scrollHeight <= available) { fits = mid; lo = mid + 1; } else hi = mid - 1; }
        if (fits < rest.length) { const boundary = Math.max(rest.lastIndexOf(' ', fits - 1), rest.lastIndexOf('\n', fits - 1)); if (boundary > fits * .6) fits = boundary + 1; }
        parts.push(rest.slice(0, fits)); rest = rest.slice(fits);
      }
      setPages(parts.length ? parts : ['']); setPage(value => Math.min(value, Math.max(0, parts.length - 1)));
    };
    const observer = new ResizeObserver(measure); observer.observe(container.current); measure(); document.fonts.ready.then(measure); return () => observer.disconnect();
  }, [text]);
  useEffect(() => setPage(0), [text]);
  return <div className="wb-reader"><div className="wb-reader-area" ref={container}><div className="wb-reader-copy" data-reader-copy>{pages[Math.min(page, pages.length - 1)]}</div><div className="wb-reader-copy wb-probe" ref={probe} aria-hidden="true" /></div><Pager label={label} page={Math.min(page, pages.length - 1)} count={pages.length} onChange={setPage} /></div>;
}

export function Modal({ title, onClose, children, actions }: { title: string; onClose: () => void; children: ReactNode; actions?: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { const node = ref.current; const previous = document.activeElement as HTMLElement | null; node?.showModal(); return () => { node?.close(); if (previous?.isConnected) previous.focus(); }; }, []);
  return <dialog ref={ref} className="wb-modal" onCancel={event => { event.preventDefault(); onClose(); }} onClick={event => { if (event.target === event.currentTarget) onClose(); }} aria-label={title}><div className="wb-modal-frame"><header className="wb-panel-head"><h2>{title}</h2><button type="button" autoFocus aria-label="닫기" onClick={onClose}>✕</button></header><div className="wb-modal-body">{children}</div>{actions && <footer className="wb-actions">{actions}</footer>}</div></dialog>;
}

export function EvidenceView({ value }: { value: ApiEvidence }) {
  const [tab, setTab] = useState<'quote' | 'page'>('quote'); const [imageError, setImageError] = useState(false); const [natural, setNatural] = useState<{ width: number; height: number } | null>(null);
  const imageUrl = value.page_image_url ?? `/api/documents/${encodeURIComponent(value.doc_id)}/pages/${value.page}.png`;
  useEffect(() => { setTab('quote'); setImageError(false); setNatural(null); }, [value]);
  const size = value.page_size ?? (natural ? [natural.width / 2, natural.height / 2] : undefined);
  return <><div className="wb-evidence-meta"><strong>{value.doc_title ?? value.doc_id}</strong><span>p.{value.page}{value.publisher ? ` · ${value.publisher}` : ''}{value.snapshot_date ? ` · ${value.snapshot_date}` : ''}</span></div><Tabs value={tab} onChange={setTab} items={[{ value: 'quote', label: '인용 원문' }, { value: 'page', label: 'PDF 페이지' }]} />{tab === 'quote' ? <TextPages text={`${value.span}${value.legal_basis ? `\n\n법적 근거\n${value.legal_basis}` : ''}${value.context ? `\n\n문맥\n${value.context}` : ''}`} /> : imageError ? <Empty>원문 페이지 이미지를 불러오지 못했습니다. 인용 원문 탭에서 서버가 제공한 구절을 확인할 수 있습니다.</Empty> : <div className="wb-page-image"><div className="wb-page-canvas" style={natural ? { aspectRatio: `${natural.width} / ${natural.height}` } : undefined}><img src={apiUrl(imageUrl)} alt={`${value.doc_title ?? value.doc_id} ${value.page}페이지`} onError={() => setImageError(true)} onLoad={event => setNatural({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight })} />{value.bbox && size && <span className="wb-highlight" style={{ left: `${value.bbox[0] / size[0] * 100}%`, top: `${(size[1] - value.bbox[3]) / size[1] * 100}%`, width: `${(value.bbox[2] - value.bbox[0]) / size[0] * 100}%`, height: `${(value.bbox[3] - value.bbox[1]) / size[1] * 100}%` }} />}</div></div>}</>;
}
