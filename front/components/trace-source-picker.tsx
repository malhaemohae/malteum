'use client';

import { useState } from 'react';
import { ApiSessionSummary } from '../lib/api';
import { traceCandidates } from '../lib/trace-source';
import { Empty, Modal, Notice, PagedList, TextPages, useResource } from './workspace';

export function TraceSourcePicker({ trace, busy, error, onClose, onPlay }: { trace: ApiSessionSummary; busy: boolean; error: string; onClose: () => void; onPlay: (record: ApiSessionSummary) => void }) {
  const result = useResource(() => traceCandidates(trace), [trace.session_id]);
  const [query, setQuery] = useState(''); const [preview, setPreview] = useState<string | null>(null);
  const items = (result.data ?? []).filter(({ record, preview }) => `${record.product_name} ${record.mode} ${record.started_at} ${new Date(record.started_at).toLocaleString('ko-KR')} ${record.session_id} ${preview}`.toLowerCase().includes(query.trim().toLowerCase()));
  return <Modal title="재생할 상담 선택" onClose={() => { if (!busy) onClose(); }}>
    <div className="wb-trace-picker">
      <p>이 TRACE에는 원본 연결이 저장되지 않았습니다. 같은 상품의 저장된 상담을 선택하면 바로 재생합니다.</p>
      <Notice>{error || result.error}</Notice>
      <div className="wb-toolbar"><input type="search" aria-label="재생할 상담 검색" placeholder="날짜·발화·세션 ID 검색" value={query} onChange={event => setQuery(event.target.value)} /><button disabled={busy || result.loading} onClick={result.refresh}>새로고침</button></div>
      {result.loading ? <Empty>저장된 발화와 판정을 확인하고 있습니다.</Empty> : <PagedList key={query} label="재생할 상담" rowHeight={110} items={items} empty={result.error ? '저장 기록을 불러오지 못했습니다. 새로고침으로 다시 시도해 주세요.' : query ? '검색 결과가 없습니다.' : '같은 상품에 재생할 발화·판정이 없습니다.'} render={candidate => <div className="wb-trace-candidate" data-trace-candidate={candidate.record.session_id}><div><strong>{candidate.record.product_name ?? candidate.record.pack_version}</strong><small>{new Date(candidate.record.started_at).toLocaleString('ko-KR')} · {candidate.record.mode.toUpperCase()} · 발화 {candidate.utterances}개</small><button className="wb-trace-preview" disabled={!candidate.playable} onClick={() => setPreview(candidate.preview)} title="첫 발화 전체 보기">{candidate.error ?? candidate.preview}</button></div><button className="wb-primary" disabled={busy || !candidate.playable} onClick={() => onPlay(candidate.record)}>{busy ? '연결 중…' : '이 상담 재생'}</button></div>} />}
    </div>
    {preview !== null && <Modal title="첫 발화" onClose={() => setPreview(null)}><TextPages text={preview} /></Modal>}
  </Modal>;
}
