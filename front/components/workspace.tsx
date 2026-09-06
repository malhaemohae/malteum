'use client';

import { DependencyList, KeyboardEvent, ReactNode, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { errorText, NavItem, Screen } from '../lib/workspace-model';
import { WorkspaceIcon, WorkspaceIconName } from './workspace-icons';

export function Workbench({ screen, title, subtitle, actions, onNavigate, onNew, children }: { screen: Screen; title: string; subtitle?: string; actions?: ReactNode; onNavigate: (nav: NavItem) => void; onNew: () => void; children: ReactNode }) {
  const links: { label: NavItem; text?: string; active: boolean; icon: WorkspaceIconName }[] = [
    { label: '상담', active: ['briefing', 'dashboard'].includes(screen), icon: 'conversation' },
    { label: '리포트', active: screen === 'report', icon: 'document' },
    { label: '이력', active: ['history', 'playback'].includes(screen), icon: 'history' },
    { label: '기준 관리', text: '규정 관리', active: ['packs', 'documents'].includes(screen), icon: 'book' },
  ];
  return <div className="wb wb-service" data-workspace={screen}>
    <aside className="wb-sidebar"><a href="#" className="wb-brand" aria-label="말틈 홈" onClick={event => { event.preventDefault(); onNew(); }}><img src="/assets/malteum-logo.png" alt="말틈" /></a>
      <nav aria-label="주 메뉴">{links.map(link => <button key={link.label} type="button" aria-current={link.active ? 'page' : undefined} onClick={() => onNavigate(link.label)}><span aria-hidden="true"><WorkspaceIcon name={link.icon} /></span>{link.text ?? link.label}</button>)}</nav>
      <button className="wb-new" type="button" onClick={onNew}>＋ 새 상담</button>
    </aside>
    <main className="wb-main"><header className="wb-heading"><div><h1>{title}</h1>{subtitle && <p title={subtitle}>{subtitle}</p>}</div><div className="wb-actions">{actions}{['report', 'history', 'playback'].includes(screen) && <button className="wb-mobile-new" onClick={onNew}>새 상담</button>}</div></header><div className="wb-body">{children}</div></main>
  </div>;
}

export function Feedback({ message, pending = false, action }: { message?: string; pending?: boolean; action?: ReactNode }) {
  return message ? <div className="wb-feedback" role="status" aria-live="polite" aria-atomic="true" data-pending={pending}><span aria-hidden="true">{pending ? '◌' : '•'}</span><span>{message}</span>{action}</div> : null;
}
export function Panel({ title, action, className = '', children }: { title?: string; action?: ReactNode; className?: string; children: ReactNode }) {
  return <section className={`wb-panel ${className}`}>{(title || action) && <header className="wb-panel-head"><h2>{title}</h2>{action}</header>}<div className="wb-panel-body">{children}</div></section>;
}
export function Empty({ children }: { children: ReactNode }) { return <div className="wb-empty">{children}</div>; }
// Structured record view for report rows, session details and summaries: a label column and a value column.
export function KeyValueList({ rows, empty, className }: { rows: { label: string; value: ReactNode }[]; empty?: string; className?: string }) {
  if (!rows.length) return empty ? <Empty>{empty}</Empty> : null;
  return <dl className={className ? `wb-kv ${className}` : 'wb-kv'}>{rows.map((row, index) => <div key={`${row.label}-${index}`}><dt>{row.label}</dt><dd>{row.value}</dd></div>)}</dl>;
}
// A record reads as labelled groups, never as one run of text. Empty groups never render.
export function detailSections(sections: [string, (string | undefined)[] | undefined][]) {
  return sections.map(([title, values]) => [title, (values ?? []).filter((value): value is string => Boolean(value && value.trim()))] as [string, string[]]).filter(([, values]) => values.length);
}
export function DetailSections({ sections, empty }: { sections: [string, (string | undefined)[] | undefined][]; empty?: string }) {
  const shown = detailSections(sections);
  if (!shown.length) return empty ? <Empty>{empty}</Empty> : null;
  return <div className="wb-rule-details wb-reader-copy">{shown.map(([title, values]) => <section key={title}><h3>{title}</h3>{values.length === 1 ? <p>{values[0]}</p> : <ul>{values.map((value, index) => <li key={index}>{value}</li>)}</ul>}</section>)}</div>;
}
export function Notice({ children, action }: { children?: ReactNode; action?: ReactNode }) { return children ? <div className="wb-notice" role="status"><span>{children}</span>{action}</div> : null; }
export function Tabs<T extends string>({ value, items, onChange }: { value: T; items: { value: T; label: string }[]; onChange: (value: T) => void }) {
  return <div className="wb-tabs" role="group" aria-label="화면 선택">{items.map(item => <button type="button" key={item.value} aria-pressed={value === item.value} onClick={() => onChange(item.value)}>{item.label}</button>)}</div>;
}

// 다시 불러오는 동안 화면이 깜빡이지 않게 하는 두 가지 규칙.
//
//   이전 값 유지    새 값이 올 때까지 먼저 받은 값을 그대로 둔다. 예전에는 의존값이
//                   바뀔 때마다 값을 비워, 고객 유형만 바꿔도 목록이 한 번 사라졌다
//   로딩 문구 지연   이만큼 넘게 걸릴 때만 `loading` 을 켠다. 30ms 에 끝나는 조회에
//                   '불러오고 있습니다' 를 내면 글자가 한 프레임 스쳤다 사라진다
//
// `settled` 는 한 번이라도 결론(값 또는 오류)이 난 뒤에만 참이다. 부르는 쪽은 이 값이
// 거짓인 동안 '없습니다' 같은 확정 문구를 내지 않는다. 아직 없는 것이 아니라 모르는 것이다.
const SLOW_LOAD_MS = 300;
export function useResource<T>(loader: () => Promise<T>, dependencies: DependencyList = []) {
  const [state, setState] = useState<{ data: T | null; error: string; slow: boolean; settled: boolean }>({ data: null, error: '', slow: false, settled: false });
  const [version, refresh] = useState(0);
  useEffect(() => { // Each caller supplies all loader inputs.
    let active = true; let done = false;
    // `settled` 도 여기서 되접는다. 안 접으면 이전 의존값(흔히 빈 문자열)이 즉시
    // 끝나 settled 를 한 번 켠 뒤, 진짜 요청이 300ms 안에 끝나는 흔한 경우
    // '없습니다' 문구가 실제로 값이 있는데도 한 프레임 스친다(매 첫 선택마다 재현)
    setState(previous => ({ ...previous, error: '', slow: false, settled: false }));
    const slow = setTimeout(() => { if (active && !done) setState(previous => ({ ...previous, slow: true })); }, SLOW_LOAD_MS);
    loader()
      .then(value => { if (active) setState({ data: value, error: '', slow: false, settled: true }); })
      .catch(reason => { if (active) setState(previous => ({ ...previous, error: errorText(reason), slow: false, settled: true })); })
      .finally(() => { done = true; clearTimeout(slow); });
    return () => { active = false; clearTimeout(slow); };
  }, [...dependencies, version]);
  return { data: state.data, error: state.error, loading: state.slow, settled: state.settled, refresh: () => refresh(value => value + 1) };
}

function Pager({ page, count, onChange, label }: { page: number; count: number; onChange: (page: number) => void; label: string }) {
  if (count <= 1) return null;
  return <div className="wb-pager" aria-label={`${label} 페이지`}><button type="button" aria-label={`${label} 이전 페이지`} disabled={page <= 0} onClick={() => onChange(page - 1)}>‹</button><span>{page + 1} / {Math.max(1, count)}</span><button type="button" aria-label={`${label} 다음 페이지`} disabled={page >= count - 1} onClick={() => onChange(page + 1)}>›</button></div>;
}

// 목록 위에 놓인 것만 빼면 아래에 놓인 것들(브리핑 푸터, 안내 문구, 질문 입력줄)의 높이가
// 그대로 가용 높이에 남아 행이 그만큼 더 그려진다. 넘친 행은 페이지 번호와 개수 표시를 덮어
// 두 겹으로 보였다. 목록에서 `.wb-body` 까지 올라가며 각 단계마다 목록보다 아래에 놓인 형제와
// 그 사이 간격, 부모의 아래 여백을 함께 뺀다. 가로로 나란한 칸은 위쪽 좌표가 목록과 같거나
// 앞서므로 걸러진다.
function spaceBelow(host: HTMLElement, body: Element) {
  const top = host.getBoundingClientRect().top;
  let total = 0;
  for (let node: HTMLElement | null = host; node && node !== body; node = node.parentElement) {
    const parent = node.parentElement; if (!parent) break;
    const style = getComputedStyle(parent);
    const gap = parseFloat(style.rowGap) || 0;
    for (let sibling = node.nextElementSibling; sibling; sibling = sibling.nextElementSibling) {
      const rect = sibling.getBoundingClientRect();
      if (rect.top > top) total += rect.height + gap;
    }
    total += (parseFloat(style.paddingBottom) || 0) + (parseFloat(style.borderBottomWidth) || 0);
  }
  return total;
}

// The capacity follows the available pane, not an arbitrary breakpoint or hidden overflow.
export function PagedList<T>({ items, render, label, empty = '표시할 항목이 없습니다.', rowHeight = 66, followLatest = false }: { items: T[]; render: (item: T, index: number) => ReactNode; label: string; empty?: string; rowHeight?: number; followLatest?: boolean }) {
  const ref = useRef<HTMLDivElement>(null); const [capacity, setCapacity] = useState(1); const [height, setHeight] = useState(rowHeight); const [page, setPage] = useState(0); const following = useRef(followLatest);
  // 패널이 내용만큼 줄어들 수 있으므로 목록 자기 높이로 용량을 재면 둘이 서로를 물고
  // 늘어진다(줄면 용량이 줄고, 용량이 줄면 또 준다). 목록 위에 놓인 것들의 높이는 내용에
  // 매여 있어 흔들리지 않으므로, 본문 높이에서 그만큼을 뺀 값을 쓸 수 있는 높이로 본다.
  useLayoutEffect(() => {
    const host = ref.current; if (!host) return;
    const body = host.closest('.wb-body');
    const measure = () => {
      const effective = rowHeight + (host.clientWidth < 520 ? 16 : 0);
      const above = body ? host.getBoundingClientRect().top - body.getBoundingClientRect().top : 0;
      const available = body ? body.clientHeight - above - spaceBelow(host, body) : host.clientHeight;
      setHeight(effective);
      setCapacity(Math.max(1, Math.floor((available - 38) / effective)));
    };
    const observer = new ResizeObserver(measure);
    observer.observe(host); if (body) observer.observe(body);
    return () => observer.disconnect();
  }, [rowHeight]);
  const count = Math.max(1, Math.ceil(items.length / capacity)); const visiblePage = Math.min(page, count - 1);
  useEffect(() => { if (followLatest && following.current) setPage(count - 1); else setPage(value => Math.min(value, count - 1)); }, [count, items.length, followLatest]);
  return <div className="wb-list" ref={ref} data-paged-list={label}><div className="wb-list-rows">{items.length ? items.slice(visiblePage * capacity, (visiblePage + 1) * capacity).map((item, index) => <div className="wb-list-row" style={{ height, minHeight: height }} key={visiblePage * capacity + index}>{render(item, visiblePage * capacity + index)}</div>) : <Empty>{empty}</Empty>}</div><div className="wb-list-bottom"><small>{items.length}개</small>{followLatest && !following.current && <button type="button" onClick={() => { following.current = true; setPage(count - 1); }}>최신 발화</button>}<Pager label={label} page={visiblePage} count={count} onChange={value => { following.current = value === count - 1; setPage(value); }} /></div></div>;
}

// 시간 순서로 쭉 읽는 목록(리포트 타임라인)은 페이지를 넘기지 않는다. 상담 대화와 같은
// 스크롤 방식이다. 앞뒤 맥락을 이어 보려는 목록에서 페이지 경계는 방해가 된다.
// 행 높이를 고정하지 않으므로 라벨이 길어도 잘리지 않는다.
export function ScrollList<T>({ items, render, label, empty = '표시할 항목이 없습니다.' }: { items: T[]; render: (item: T, index: number) => ReactNode; label: string; empty?: string }) {
  return <div className="wb-list wb-scroll-list" data-paged-list={label}>
    <div className="wb-scroll-rows" role="list">{items.length ? items.map((item, index) => <div className="wb-list-row" role="listitem" key={index}>{render(item, index)}</div>) : <Empty>{empty}</Empty>}</div>
    <div className="wb-list-bottom"><small>{items.length}개</small></div>
  </div>;
}

// Exact source text stays continuous and selectable; reading never needs a page turn.
export function TextPages({ text, label = '내용' }: { text: string; label?: string }) {
  const area = useRef<HTMLDivElement>(null);
  useEffect(() => { if (area.current) area.current.scrollTop = 0; }, [text]);
  return <div className="wb-reader"><div className="wb-reader-area" ref={area} role="region" aria-label={label} tabIndex={0}><div className="wb-reader-copy" data-reader-copy>{text}</div></div></div>;
}

export function Modal({ title, onClose, children, actions, className = '', trapFocus = false }: { title: string; onClose: () => void; children: ReactNode; actions?: ReactNode; className?: string; trapFocus?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { const node = ref.current; const previous = document.activeElement as HTMLElement | null; node?.showModal(); return () => { node?.close(); if (previous?.isConnected) previous.focus(); }; }, []);
  function keepFocus(event: KeyboardEvent<HTMLDialogElement>) {
    if (!trapFocus || event.key !== 'Tab') return;
    const elements = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('button,a[href],input,select,textarea,[tabindex]')).filter(node => node.tabIndex >= 0 && !node.matches(':disabled') && node.getClientRects().length > 0);
    const first = elements[0], last = elements[elements.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  }
  return <dialog ref={ref} className={`wb-modal ${className}`} onKeyDown={keepFocus} onCancel={event => { event.preventDefault(); onClose(); }} onClick={event => { if (event.target === event.currentTarget) onClose(); }} aria-label={title}><div className="wb-modal-frame"><header className="wb-panel-head"><h2>{title}</h2><button type="button" autoFocus aria-label="닫기" onClick={onClose}>✕</button></header><div className="wb-modal-body">{children}</div>{actions && <footer className="wb-actions">{actions}</footer>}</div></dialog>;
}

export { EvidenceView, sourceUrl } from './evidence';
