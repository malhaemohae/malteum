'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { ApiHealth, ApiPack, ApiPackItem, malteumApi } from '../lib/api';
import { kindNames, LiveSession, Mode, NavItem, ReadyItem, statusNames, timeLabel } from '../lib/workspace-model';
import { Empty, Modal, Notice, PagedList, Panel, Tabs, TextPages, useResource, Workbench } from './workspace';
import { speakerLabel, Transcript } from './transcript';
import { WorkspaceIcon, WorkspaceIconName } from './workspace-icons';

function QuickAction({ title, subtitle, icon, tone, onClick, disabled, pressed, label }: { title: string; subtitle: string; icon: WorkspaceIconName; tone: string; onClick: () => void; disabled?: boolean; pressed?: boolean; label?: string }) {
  return <button type="button" className={`wb-shortcut is-${tone}`} aria-label={label ?? title} aria-pressed={pressed} disabled={disabled} onClick={onClick}><span className="wb-shortcut-title"><strong>{title}</strong><span className="wb-shortcut-arrow"><WorkspaceIcon name="arrow" size={14} /></span></span><span className="wb-shortcut-bottom"><small>{subtitle}</small><span className="wb-shortcut-icon"><WorkspaceIcon name={icon} size={32} /></span></span></button>;
}

export function Briefing({ onStart, onNavigate, onNew, busy }: { onStart: (pack: ApiPack, mode: Mode, customer: 'general' | 'professional', preset?: { preset_id: string; audio_ref?: string }) => void; onNavigate: (nav: NavItem) => void; onNew: () => void; busy: boolean }) {
  const packs = useResource(() => malteumApi.packs()); const presets = useResource(() => malteumApi.presets());
  const [version, setVersion] = useState(''); const [mode, setMode] = useState<Mode>('live'); const [customer, setCustomer] = useState<'general' | 'professional'>('general');
  const [detail, setDetail] = useState<{ title: string; text: string } | null>(null);
  useEffect(() => { if (packs.data && !version) setVersion((packs.data.packs.find(pack => pack.product?.category === 'deposit') ?? packs.data.packs[0])?.pack_version ?? ''); }, [packs.data, version]);
  const pack = useResource(() => version ? malteumApi.pack(version) : Promise.resolve(null), [version]);
  const briefing = useResource(() => version ? malteumApi.briefing(version, customer) : Promise.resolve(null), [version, customer]);
  const replayPreset = presets.data?.presets.find(item => item.pack_version === version && item.mode === 'replay' && item.audio_ref);
  useEffect(() => { if (!presets.loading && mode === 'replay' && !replayPreset) setMode('live'); }, [version, mode, presets.loading, replayPreset]);
  const [pane, setPane] = useState<'items' | 'documents'>('items');
  return <Workbench screen="briefing" title="상담 준비" subtitle="상담 기준을 확인하고 녹음을 시작하세요." onNavigate={onNavigate} onNew={onNew}>
    <Notice action={<button onClick={() => { packs.refresh(); pack.refresh(); briefing.refresh(); }}>다시 불러오기</button>}>{packs.error || pack.error || briefing.error}</Notice>
    {!packs.loading && !packs.error && packs.data?.packs.length === 0 && <Notice action={<button onClick={() => onNavigate('기준 관리')}>기준 관리</button>}>서버에 발행된 규정 팩이 없습니다. 팩이 준비되면 상담을 시작할 수 있습니다.</Notice>}
    <Panel className="wb-briefing" title="상담 기준">
      <div className="wb-form"><label>상품·규정 팩<select aria-label="상품·규정 팩" value={version} disabled={busy || packs.loading || !packs.data?.packs.length} onChange={event => setVersion(event.target.value)}>{!version && <option value="">{packs.loading ? '불러오는 중' : packs.error ? '팩 조회 실패' : '발행된 팩 없음'}</option>}{packs.data?.packs.map(item => <option key={item.pack_version} value={item.pack_version}>{item.product?.name ?? item.pack_version} · {item.pack_version}</option>)}</select></label>
        <label>고객 유형<select aria-label="고객 유형" value={customer} disabled={busy} onChange={event => setCustomer(event.target.value as typeof customer)}><option value="general">일반금융소비자</option><option value="professional">전문금융소비자</option></select></label></div>
      <div className="wb-briefing-intro"><span className="wb-briefing-count">{briefing.data ? briefing.data.must_say.length : '—'}</span><div><h3>필수 안내 항목</h3><small>{briefing.data?.pack_version ?? '서버 기준을 확인하고 있습니다.'}</small></div></div>
      <Tabs value={pane} onChange={setPane} items={[{ value: 'items', label: '필수 안내' }, { value: 'documents', label: '필요 서류' }]} />
      {pane === 'items' ? <PagedList label="브리핑 항목" items={briefing.data?.must_say ?? []} empty={briefing.loading ? '브리핑을 불러오는 중입니다.' : briefing.error ? '브리핑을 확인하지 못했습니다.' : '필수 안내 항목이 없습니다.'} render={item => <button className="wb-row-button" onClick={() => setDetail({ title: item.name, text: `${item.name}\n\n${item.elements?.join('\n') ?? ''}\n\n${item.plain_language?.join('\n') ?? ''}` })}><span className="wb-row-copy"><strong>{item.name}</strong><small>{item.item_code}</small></span><span aria-hidden="true">›</span></button>} /> : <PagedList label="필요 서류" items={briefing.data?.documents_required ?? []} render={item => <button className="wb-row-button" onClick={() => setDetail({ title: '필요 서류', text: item })}><span className="wb-row-copy"><strong>{item}</strong></span><span>›</span></button>} />}
      <div className="wb-briefing-footer"><label className="wb-composer"><small>입력</small><select aria-label="입력 방식" value={mode} disabled={busy} onChange={event => setMode(event.target.value as Mode)}><option value="live">마이크 녹음</option><option value="text">텍스트 입력</option>{replayPreset && <option value="replay">준비된 녹취 재생</option>}</select></label><button className="wb-primary" disabled={busy || !pack.data || !briefing.data || briefing.loading || pack.loading || (mode === 'replay' && !replayPreset)} onClick={() => pack.data && onStart(pack.data, mode, customer, mode === 'replay' ? replayPreset : undefined)}>{busy ? '세션 연결 중…' : '상담 시작'} →</button></div>
    </Panel>
    {detail && <Modal title={detail.title} onClose={() => setDetail(null)}><TextPages text={detail.text} /></Modal>}
  </Workbench>;
}

type DashboardProps = { session: LiveSession; pack: ApiPack | null; health: ApiHealth | null; micActive: boolean; micPending: boolean; micError: string; onMic: () => void; onEnd: () => void; onRetry: () => void; onTextMode: () => void; onNavigate: (nav: NavItem) => void; onNew: () => void; onCommand: (value: Record<string, unknown>) => boolean; onDismiss: () => void; onEvidence: (ref: string) => void; onItemEvidence: (item: ApiPackItem) => void; onAsk: (question: string) => void };

export function Dashboard({ session, pack, health, micActive, micPending, micError, onMic, onEnd, onRetry, onTextMode, onNavigate, onNew, onCommand, onDismiss, onEvidence, onItemEvidence, onAsk }: DashboardProps) {
  const [pane, setPane] = useState<'attention' | 'conversation' | 'checks'>('conversation'); const [detail, setDetail] = useState<{ title: string; text: string; evidenceRef?: string } | null>(null);
  const [guidePane, setGuidePane] = useState<'attention' | 'checks'>('attention');
  const [filter, setFilter] = useState<'all' | 'customer' | 'teller'>('all'); const inputRef = useRef<HTMLInputElement>(null);
  const transcript = useMemo(() => filter === 'all' ? session.transcript : session.transcript.filter(row => row.speaker === filter), [filter, session.transcript]);
  function selectPane(value: typeof pane) { setPane(value); if (value !== 'conversation') setGuidePane(value); }
  function requestAssist(type: 'documents' | 'briefing') { if (onCommand({ t: 'assist_request', assist_type: type })) selectPane('attention'); }
  const [selected, setSelected] = useState<string | null>(null); const [manualTab, setManualTab] = useState<'detail' | 'waive'>('detail');
  const [reason, setReason] = useState(''); const [query, setQuery] = useState(''); const [text, setText] = useState(''); const [speaker, setSpeaker] = useState('teller');
  const item: ReadyItem | undefined = session.items.find(item => item.code === selected); const packItem = pack?.items.find(entry => entry.code === selected);
  const intervention = session.interventions[0]; const canWrite = session.status === 'connected' && session.mode !== 'trace' && !session.ending;
  const notice = micError || session.error || (session.mode === 'live' && !session.textFallback && health?.checks?.stt === 'unconfigured' ? '음성 전사 서버가 설정되지 않았습니다. 녹음은 가능하지만 전사·판정에는 STT 설정이 필요합니다.' : '');
  function resolve() { if (intervention?.alert) { onCommand({ t: 'acknowledge', alert_ref: intervention.id }); return; } onDismiss(); }
  const [manualPending, setManualPending] = useState(false);
  useEffect(() => { setManualPending(false); }, [selected, item?.state, session.error]);
  return <Workbench screen="dashboard" title="상담" subtitle={pack?.product?.name ?? session.packVersion} onNavigate={onNavigate} onNew={onNew} actions={<><span className="wb-badge">{session.status === 'connected' ? session.mode.toUpperCase() : session.status === 'connecting' ? '연결 중' : session.status === 'ended' ? '종료' : '연결 끊김'}</span><small>{timeLabel(session.seconds)}</small><button disabled={session.status !== 'connected' || session.ending} onClick={onEnd}>{session.ending ? '종료 확인 중…' : '상담 종료'}</button></>}>
    <Notice action={<><button onClick={() => setDetail({ title: '연결 상태', text: notice })}>상세</button>{session.status === 'disconnected' ? <button onClick={onRetry}>다시 연결</button> : session.mode === 'live' && !session.textFallback ? <button onClick={onTextMode}>텍스트 입력</button> : null}</>}>{notice}</Notice>
    <div className="wb-mobile-tabs"><Tabs value={pane} onChange={selectPane} items={[{ value: 'conversation', label: '상담 대화' }, { value: 'attention', label: intervention ? `현재 안내 · ${session.interventions.length}` : '현재 안내' }, { value: 'checks', label: '필수 안내' }]} /></div>
    <div className="wb-dashboard" data-pane={pane}>
      <div className="wb-shortcuts" aria-label="상담 주요 기능">
        {session.mode === 'live' ? <QuickAction title={micPending ? '마이크 연결 중' : micActive ? '녹음 중지' : '녹음 시작'} label={micPending ? '마이크 연결 중' : micActive ? '■ 녹음 중지' : '● 녹음 시작'} subtitle={micActive ? '실시간 전사 중' : '마이크로 상담 입력'} icon={micActive ? 'stop' : 'mic'} tone={micActive ? 'recording' : 'record'} pressed={micActive} disabled={!canWrite || micPending} onClick={onMic} /> : <QuickAction title={session.mode === 'text' ? '텍스트 입력' : '상담 대화'} subtitle={session.mode === 'text' ? '화자를 선택해 입력' : '저장된 상담 확인'} icon="conversation" tone="record" onClick={() => { selectPane('conversation'); requestAnimationFrame(() => inputRef.current?.focus()); }} />}
        <QuickAction title="필수 안내" subtitle={session.progress ? `${session.progress.met} / ${session.progress.total} 고지 완료` : '항목별 이행 확인'} icon="check" tone="checks" onClick={() => selectPane('checks')} />
        <QuickAction title="필요 서류" subtitle="서버 기준으로 확인" icon="folder" tone="documents" disabled={!canWrite} onClick={() => requestAssist('documents')} />
        <QuickAction title="기준 확인" subtitle="이번 상담의 안내 기준" icon="book" tone="briefing" disabled={!canWrite} onClick={() => requestAssist('briefing')} />
      </div>
      <div className="wb-conversation">
        <Panel title="상담 대화" className="wb-transcript" action={<small>{session.mode === 'live' && micActive ? '실시간 전사 중' : '고객 · 상담원'}</small>}>
          <div className="wb-conversation-filters" aria-label="대화 화자 필터"><Tabs value={filter} onChange={setFilter} items={[{ value: 'all', label: '전체' }, { value: 'customer', label: '고객' }, { value: 'teller', label: '상담원' }]} /></div>
          <Transcript key={filter} items={transcript} empty={filter === 'all' ? '첫 발화를 기다리고 있습니다.' : '이 화자의 발화가 아직 없습니다.'} onSelect={row => setDetail({ title: `${speakerLabel(row.speaker)} · ${timeLabel(row.t_ms / 1000)}`, text: row.text })} />
          {session.partial && <button className="wb-row-button wb-partial" onClick={() => setDetail({ title: '중간 전사', text: session.partial })}>듣는 중 · {session.partial}</button>}
          {session.mode === 'text' || session.textFallback ? <form className="wb-composer" onSubmit={event => { event.preventDefault(); if (text.trim() && onCommand({ t: 'text_utterance', text: text.trim(), speaker })) setText(''); }}><select aria-label="화자" value={speaker} onChange={event => setSpeaker(event.target.value)}><option value="teller">상담원</option><option value="customer">고객</option></select><input ref={inputRef} aria-label="상담 발화" value={text} maxLength={5000} onChange={event => setText(event.target.value)} placeholder="상담 발화 입력" /><button disabled={!canWrite || !text.trim()} type="submit">전송</button></form> : null}
        </Panel>
      </div>
      <div className="wb-guidance">
        <Panel title="상담 가이드" className="wb-guide-panel" action={intervention && <span className="wb-badge">{session.interventions.length}건</span>}>
        <div className="wb-guide-tabs"><Tabs value={guidePane} onChange={value => selectPane(value)} items={[{ value: 'attention', label: intervention ? `현재 안내 · ${session.interventions.length}` : '현재 안내' }, { value: 'checks', label: '필수 안내' }]} /></div>
        <div className="wb-guide-content" data-guide-pane={guidePane}>
        <Panel title={intervention ? kindNames[intervention.kind] ?? '현재 안내' : '현재 확인할 내용'} className={`wb-attention ${intervention?.kind === 'risk_signal' ? 'is-risk' : ''}`} action={intervention && <span className="wb-badge">{session.interventions.length > 1 ? `대기 ${session.interventions.length - 1}건` : '현재 1건'}</span>}>
          {intervention ? <><TextPages label="현재 안내" text={`${intervention.text}${intervention.said != null || intervention.reference != null ? `\n말씀: ${intervention.said ?? '미제공'}\n기준: ${intervention.reference ?? '미제공'}` : ''}${intervention.condition ? `\n${intervention.condition}` : ''}`} /><div className="wb-actions">{intervention.evidenceRef && <button onClick={() => onEvidence(intervention.evidenceRef!)}>근거 보기</button>}<button className="wb-primary" disabled={intervention.alert && !canWrite} onClick={resolve}>{intervention.alert ? '확인 기록' : '닫기'}</button></div></> : <Empty><span className="wb-guide-empty-icon"><WorkspaceIcon name="conversation" size={32} /></span><p>{micActive ? '대화를 듣고 있습니다.' : session.mode === 'live' && !session.transcript.length ? '녹음 시작 버튼을 눌러 상담을 시작하세요.' : '확인이 필요한 안내가 없습니다.'}</p></Empty>}
          {session.query?.pending ? <small>답변 요청 중</small> : session.query?.answer ? <button onClick={() => setDetail({ title: '규정 질의 답변', text: `${session.query?.question}\n\n${session.query?.answer}`, evidenceRef: session.query?.evidenceRef })}>답변 보기</button> : null}
          <form className="wb-composer" onSubmit={event => { event.preventDefault(); if (query.trim()) { onAsk(query.trim()); setQuery(''); } }}><input aria-label="규정 질문" value={query} maxLength={2000} onChange={event => setQuery(event.target.value)} placeholder="규정에 대해 물어보세요" /><button type="submit" disabled={!canWrite || !query.trim() || session.query?.pending}>질문</button></form>
        </Panel>
      <div className="wb-checks"><Panel title="필수 안내" action={<span className="wb-badge">{session.progress ? `${session.progress.met} / ${session.progress.total}` : '판정 대기'}</span>}>
        <PagedList label="필수 안내" items={session.items} empty={session.status === 'connecting' ? '기준을 연결하고 있습니다.' : '서버가 제공한 필수 항목이 없습니다.'} render={entry => <button className="wb-row-button" onClick={() => { setSelected(entry.code); setManualTab('detail'); setReason(''); }}><span className="wb-row-copy"><strong>{entry.name}</strong><small>{entry.missing.length ? `미충족 · ${entry.missing.join(', ')}` : entry.code}</small></span><span className="wb-badge" data-state={entry.state}>{statusNames[entry.state] ?? entry.state}</span><span aria-hidden="true">›</span></button>} />
        {session.progress?.density && <div className="wb-density"><span>전문용어 밀도</span><strong>{({ low: '낮음', normal: '보통', high: '높음' } as Record<string, string>)[session.progress.density] ?? session.progress.density}</strong></div>}
      </Panel></div>
        </div>
        </Panel>
      </div>
    </div>
    {item && <Modal title={item.name} onClose={() => setSelected(null)} actions={<>{item.evidenceRef ? <button onClick={() => onEvidence(item.evidenceRef!)}>근거 원문</button> : packItem?.evidence ? <button onClick={() => onItemEvidence(packItem)}>근거 원문</button> : null}{manualTab === 'detail' && <><button disabled={!canWrite || manualPending || ['met', 'waived'].includes(item.state)} onClick={() => { if (onCommand({ t: 'mark_met', item_code: item.code })) { setManualPending(true); setSelected(null); } }}>고지 완료 기록</button><button disabled={!canWrite || item.state === 'waived'} onClick={() => setManualTab('waive')}>범위에서 제외</button></>}</>}>
      {item.state === 'met' && item.decidedBy === 'human' && <button disabled={!canWrite || manualPending} onClick={() => { if (onCommand({ t: 'mark_met', item_code: item.code, undo: true })) { setManualPending(true); setSelected(null); } }}>수동 고지 기록 취소</button>}
      {manualTab === 'detail' ? <><span className="wb-badge" data-state={item.state}>{statusNames[item.state] ?? item.state}</span><TextPages text={`${item.name}\n\n${item.missing.length ? `미충족 요소\n${item.missing.join('\n')}\n\n` : ''}승인된 쉬운 말\n${item.plain.length ? item.plain.join('\n') : '서버에서 제공된 문장이 없습니다.'}`} /><button disabled={!canWrite} onClick={() => { if (onCommand({ t: 'assist_request', assist_type: 'rephrase', item_code: item.code })) setSelected(null); }}>쉬운 말로 재진술 요청</button></> : <form className="wb-form" onSubmit={event => { event.preventDefault(); if (reason.trim() && onCommand({ t: 'mark_waived', item_code: item.code, reason: reason.trim() })) setSelected(null); }}><label className="wb-wide">제외 사유<textarea aria-label="제외 사유" required maxLength={1000} value={reason} onChange={event => setReason(event.target.value)} /></label><button type="button" onClick={() => setManualTab('detail')}>취소</button><button className="wb-primary" disabled={!canWrite || !reason.trim()} type="submit">제외 사유 기록</button></form>}
    </Modal>}
    {detail && <Modal title={detail.title} onClose={() => setDetail(null)} actions={detail.evidenceRef && <button onClick={() => onEvidence(detail.evidenceRef!)}>근거 원문</button>}><TextPages text={detail.text} /></Modal>}
  </Workbench>;
}
