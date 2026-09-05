'use client';

import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { LiveSession, timeLabel } from '../lib/workspace-model';
import { Empty } from './workspace';

type Utterance = LiveSession['transcript'][number];
export const speakerLabel = (speaker: string) => ({ customer: '고객', teller: '상담원', system: '시스템' }[speaker] ?? '화자 미확인');

function Bubble({ row, onSelect }: { row: Utterance; onSelect: (row: Utterance) => void }) {
  return <article className="wb-chat-entry" data-speaker={row.speaker}>
    <div className="wb-chat-meta"><strong>{speakerLabel(row.speaker)}</strong><time>{timeLabel(row.t_ms / 1000)}</time></div>
    <button type="button" className="wb-chat-bubble" aria-label={`${speakerLabel(row.speaker)} 발화 전체 보기 · ${timeLabel(row.t_ms / 1000)}`} onClick={() => onSelect(row)}><span className="wb-chat-text">{row.text}</span></button>
  </article>;
}

// The transcript scrolls like a chat window: it follows the newest utterance until the
// reader scrolls up, then holds still and offers a jump back to the latest message.
const FOLLOW_THRESHOLD = 32;
const SETTLE_FRAMES = 60;
export function Transcript({ items, onSelect, empty = '첫 발화를 기다리고 있습니다.' }: { items: Utterance[]; onSelect: (row: Utterance) => void; empty?: string }) {
  const area = useRef<HTMLDivElement>(null);
  const [following, setFollowing] = useState(true);
  const [unread, setUnread] = useState(0);
  const suppressScroll = useRef(false);
  const settleFrame = useRef<number | undefined>(undefined);
  const seen = useRef(items.length);
  // 부드러운 스크롤이 끝날 때까지만 스크롤 이벤트를 무시한다. 읽는 사람이 도중에
  // 위로 올려 애니메이션이 취소되면 끝에 닿지 못하므로, 프레임 수로 반드시 풀어 준다.
  const scrollToEnd = (behavior: ScrollBehavior) => {
    const host = area.current; if (!host) return;
    suppressScroll.current = true;
    host.scrollTo({ top: host.scrollHeight, behavior });
    if (settleFrame.current !== undefined) cancelAnimationFrame(settleFrame.current);
    let framesLeft = SETTLE_FRAMES;
    const settle = () => {
      const current = area.current;
      const atEnd = !!current && current.scrollHeight - current.scrollTop - current.clientHeight <= FOLLOW_THRESHOLD;
      if (!current || atEnd) { suppressScroll.current = false; settleFrame.current = undefined; return; }
      if (framesLeft-- <= 0) {
        // 끝까지 못 갔다는 것은 읽는 사람이 도중에 스크롤을 잡았다는 뜻이다. 스크롤
        // 이벤트는 손을 뗀 뒤로 더 오지 않으므로 여기서 따라가기를 놓아 준다.
        suppressScroll.current = false; settleFrame.current = undefined; setFollowing(false); return;
      }
      settleFrame.current = requestAnimationFrame(settle);
    };
    settleFrame.current = requestAnimationFrame(settle);
  };
  useEffect(() => () => { if (settleFrame.current !== undefined) cancelAnimationFrame(settleFrame.current); }, []);
  useLayoutEffect(() => {
    if (following) { scrollToEnd(items.length - seen.current > 1 ? 'auto' : 'smooth'); setUnread(0); }
    else setUnread(value => value + Math.max(0, items.length - seen.current));
    seen.current = items.length;
  }, [items, following]);
  useEffect(() => {
    const host = area.current; if (!host) return;
    // Keep the newest message in view when the pane itself changes size (responsive layout, fonts).
    const observer = new ResizeObserver(() => { if (following) scrollToEnd('auto'); });
    observer.observe(host); return () => observer.disconnect();
  }, [following]);
  function onScroll() {
    const host = area.current; if (!host) return;
    const atEnd = host.scrollHeight - host.scrollTop - host.clientHeight <= FOLLOW_THRESHOLD;
    if (suppressScroll.current) {
      if (atEnd) { suppressScroll.current = false; setFollowing(true); setUnread(0); }
      return;
    }
    if (atEnd !== following) { setFollowing(atEnd); if (atEnd) setUnread(0); }
  }
  return <div className="wb-list wb-chat" data-paged-list="상담 전사" data-following={following}>
    <div className="wb-chat-rows" ref={area} onScroll={onScroll} role="log" aria-live="polite" aria-relevant="additions">{items.length ? items.map(row => <Bubble key={row.id} row={row} onSelect={onSelect} />) : <Empty>{empty}</Empty>}</div>
    <div className="wb-list-bottom"><small>{items.length}개 발화 · 선택하면 전체 보기</small>{!following && <button type="button" className="wb-chat-jump" onClick={() => { setFollowing(true); scrollToEnd('smooth'); }}>{unread > 0 ? `새 발화 ${unread}개 · 최신으로` : '최신 발화로'} ↓</button>}</div>
  </div>;
}
