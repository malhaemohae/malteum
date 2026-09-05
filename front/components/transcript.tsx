'use client';

import { CSSProperties, useLayoutEffect, useRef, useState } from 'react';
import { LiveSession, timeLabel } from '../lib/workspace-model';
import { Empty } from './workspace';

type Utterance = LiveSession['transcript'][number];
export const speakerLabel = (speaker: string) => ({ customer: '고객', teller: '상담원', system: '시스템' }[speaker] ?? '화자 미확인');

function Bubble({ row, onSelect, probe = false }: { row: Utterance; onSelect: (row: Utterance) => void; probe?: boolean }) {
  return <article className="wb-chat-entry" data-speaker={row.speaker}>
    <div className="wb-chat-meta"><strong>{speakerLabel(row.speaker)}</strong><time>{timeLabel(row.t_ms / 1000)}</time></div>
    <button type="button" className="wb-chat-bubble" tabIndex={probe ? -1 : undefined} aria-label={`${speakerLabel(row.speaker)} 발화 전체 보기 · ${timeLabel(row.t_ms / 1000)}`} onClick={() => onSelect(row)}><span className="wb-chat-text">{row.text}</span></button>
  </article>;
}

// Measure actual bubble heights rather than allocating a fixed-height slot to every sentence.
// Pagination replaces inner scrolling; the full original utterance remains available on selection.
export function Transcript({ items, onSelect, empty = '첫 발화를 기다리고 있습니다.' }: { items: Utterance[]; onSelect: (row: Utterance) => void; empty?: string }) {
  const area = useRef<HTMLDivElement>(null); const probe = useRef<HTMLDivElement>(null);
  const [pages, setPages] = useState<Utterance[][]>([[]]); const [page, setPage] = useState(0);
  const [following, setFollowing] = useState(true); const [lines, setLines] = useState(4);
  const [history, setHistory] = useState<Utterance[] | null>(null);
  const shownItems = following ? items : history ?? items;
  useLayoutEffect(() => {
    if (!area.current || !probe.current) return;
    let active = true;
    const measure = () => {
      const host = area.current; const sample = probe.current;
      if (!active || !host || !sample || host.clientWidth < 1 || host.clientHeight < 1) return;
      const lineCount = Math.max(1, Math.min(4, Math.floor((host.clientHeight - 50) / 23)));
      sample.style.width = `${host.clientWidth}px`; sample.style.setProperty('--chat-lines', String(lineCount));
      setLines(lineCount);
      const gap = 14; const available = host.clientHeight;
      const result: Utterance[][] = []; let batch: Utterance[] = []; let used = 0;
      const children = Array.from(sample.children);
      for (let index = children.length - 1; index >= 0; index--) {
        const height = children[index].getBoundingClientRect().height;
        if (batch.length && used + gap + height > available) { result.unshift(batch); batch = []; used = 0; }
        used += (batch.length ? gap : 0) + height; batch.unshift(shownItems[index]);
      }
      if (batch.length) result.unshift(batch);
      setPages(result.length ? result : [[]]);
    };
    const observer = new ResizeObserver(measure); observer.observe(area.current); measure();
    document.fonts.ready.then(measure);
    return () => { active = false; observer.disconnect(); };
  }, [shownItems]);
  const current = following ? pages.length - 1 : Math.min(page, pages.length - 1);
  function selectPage(value: number) {
    // Freeze the viewed history while newer utterances arrive; keep the latest page full otherwise.
    if (following && value < pages.length - 1) setHistory(items);
    if (value === pages.length - 1) setHistory(null);
    setPage(value); setFollowing(value === pages.length - 1);
  }
  return <div className="wb-list wb-chat" data-paged-list="상담 전사" style={{ '--chat-lines': lines } as CSSProperties}>
    <div className="wb-chat-rows" ref={area}>{items.length ? pages[current].map((row, index) => <Bubble key={`${row.id}-${index}`} row={row} onSelect={onSelect} />) : <Empty>{empty}</Empty>}</div>
    <div className="wb-list-bottom"><small>{items.length}개 발화 · 선택하면 전체 보기</small>{!following && <button type="button" onClick={() => { setHistory(null); setFollowing(true); }}>최신 발화</button>}<div className="wb-pager" aria-label="상담 전사 페이지"><button type="button" aria-label="상담 전사 이전 페이지" disabled={current === 0} onClick={() => selectPage(current - 1)}>‹</button><span>{current + 1} / {pages.length}</span><button type="button" aria-label="상담 전사 다음 페이지" disabled={current === pages.length - 1} onClick={() => selectPage(current + 1)}>›</button></div></div>
    <div ref={probe} className="wb-chat-probe wb-probe" aria-hidden="true">{shownItems.map((row, index) => <Bubble key={`${row.id}-${index}`} row={row} onSelect={onSelect} probe />)}</div>
  </div>;
}
