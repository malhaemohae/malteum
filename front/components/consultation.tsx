'use client';

import { ReactNode, useEffect, useMemo, useRef, useState } from 'react';
import { ApiBriefing, ApiHealth, ApiPack, ApiPackItem, malteumApi } from '../lib/api';
import { evidenceForItem, friendlyError, itemTypeNames, STT_UNCONFIGURED, kindNames, latestPacks, LiveSession, modeNames, NavItem, ReadyItem, sessionScreen, statusNames, timeLabel, withoutKindPrefix } from '../lib/workspace-model';
import { DetailSections, detailSections, Empty, Feedback, KeyValueList, Modal, Notice, PagedList, Panel, Tabs, TextPages, useResource, Workbench } from './workspace';
import { speakerLabel, Transcript } from './transcript';
import { WorkspaceIcon, WorkspaceIconName } from './workspace-icons';
import { waitingForTraceUtterance } from '../lib/trace-start';
import { TraceStart } from './trace-start';
import type { ReplayAudioState } from '../lib/replay-audio';
import { EvidenceCard } from './evidence';

function QuickAction({ title, subtitle, icon, tone, onClick, disabled, pressed, label }: { title: string; subtitle: string; icon: WorkspaceIconName; tone: string; onClick: () => void; disabled?: boolean; pressed?: boolean; label?: string }) {
  return <button type="button" className={`wb-shortcut is-${tone}`} aria-label={label ?? title} aria-pressed={pressed} disabled={disabled} onClick={onClick}><span className="wb-shortcut-title"><strong>{title}</strong><span className="wb-shortcut-arrow"><WorkspaceIcon name="arrow" size={14} /></span></span><span className="wb-shortcut-bottom"><small>{subtitle}</small><span className="wb-shortcut-icon"><WorkspaceIcon name={icon} size={32} /></span></span></button>;
}

// 전문용어 밀도는 상단 도구 줄의 상태 칩으로 나간다. 서버 enum → 은행원이 읽는 말
const densityNames: Record<string, string> = { low: '낮음', normal: '보통', high: '높음' };

// 브리핑 항목이 상세로 펼칠 값을 가졌는지. 펼칠 것이 없으면 행을 눌러도 빈 모달만 뜬다.
const briefingSections = (item: ApiBriefing['must_say'][number]) => detailSections([['확인해야 할 요소', item.elements], ['승인된 쉬운 말', item.plain_language]]);

export type Preparation = { packVersion?: string; mode: 'live' | 'text'; customer: 'general' | 'professional' };
export function Briefing({ onStart, onNavigate, onNew, onDemo, busy, defaults, health, onCheckHealth }: { onStart: (pack: ApiPack, mode: 'live' | 'text', customer: 'general' | 'professional') => void; onNavigate: (nav: NavItem) => void; onNew: () => void; onDemo: () => void; busy: boolean; defaults?: Preparation; health: ApiHealth | null; onCheckHealth: () => void }) {
  const packs = useResource(() => malteumApi.packs());
  const choices = useMemo(() => latestPacks(packs.data?.packs ?? []), [packs.data]);
  const [version, setVersion] = useState(defaults?.packVersion ?? ''); const [mode, setMode] = useState<'live' | 'text'>(defaults?.mode ?? 'live'); const [customer, setCustomer] = useState<'general' | 'professional'>(defaults?.customer ?? 'general');
  const [detail, setDetail] = useState<ApiBriefing['must_say'][number] | null>(null);
  useEffect(() => { if (packs.data && !choices.some(pack => pack.pack_version === version)) setVersion((choices.find(pack => pack.product?.category === 'deposit') ?? choices[0])?.pack_version ?? ''); }, [packs.data, choices, version]);
  const pack = useResource(() => version ? malteumApi.pack(version) : Promise.resolve(null), [version]);
  const briefing = useResource(() => version ? malteumApi.briefing(version, customer) : Promise.resolve(null), [version, customer]);
  const [pane, setPane] = useState<'items' | 'documents'>('items');
  // 서버가 임베딩 모델을 데우는 동안(첫 로딩 26초) 시작하면 그만큼 첫 판정이 늦다.
  // 준비되면 스스로 멈추고, 끝내 안 되면 1분 뒤 포기해 폴링이 남지 않게 한다.
  const warming = health?.checks?.embedding === 'fail';
  useEffect(() => {
    if (!warming) return;
    let left = 20; const timer = setInterval(() => { if (left-- <= 0) clearInterval(timer); else onCheckHealth(); }, 3000);
    return () => clearInterval(timer);
  }, [warming, onCheckHealth]);
  return <Workbench screen="briefing" title="상담 준비" subtitle="상담 기준을 확인하고 녹음을 시작하세요." onNavigate={onNavigate} onNew={onNew}>
    <Notice action={<button onClick={() => { packs.refresh(); pack.refresh(); briefing.refresh(); }}>다시 불러오기</button>}>{packs.error || pack.error || briefing.error}</Notice>
    {!packs.loading && !packs.error && packs.data?.packs.length === 0 && <Notice action={<button onClick={() => onNavigate('기준 관리')}>규정 관리</button>}>서버에 발행된 규정팩이 없습니다. 규정팩이 준비되면 상담을 시작할 수 있습니다.</Notice>}
    {warming && <Notice>판정 엔진이 아직 준비되지 않았습니다. 지금 시작해도 상담은 되지만 첫 판정이 늦게 올 수 있습니다.</Notice>}
    <Panel className="wb-briefing">
      <div className="wb-form"><label>상품·규정팩<select aria-label="상품·규정팩" value={version} disabled={busy || packs.loading || !packs.data?.packs.length} onChange={event => setVersion(event.target.value)}>{!packs.data?.packs.length && <option value={version}>{packs.loading ? '불러오는 중' : packs.error ? '규정팩 조회 실패' : '발행된 규정팩 없음'}</option>}{choices.map(item => <option key={item.pack_version} value={item.pack_version}>{item.product?.name ?? item.pack_version} · {item.pack_version}</option>)}</select></label>
        <label>고객 유형<select aria-label="고객 유형" value={customer} disabled={busy} onChange={event => setCustomer(event.target.value as typeof customer)}><option value="general">일반금융소비자</option><option value="professional">전문금융소비자</option></select></label></div>
      <div className="wb-briefing-intro"><span className="wb-briefing-count">{briefing.data ? briefing.data.must_say.length : '…'}</span><div><h3>필수 안내 항목</h3><small>{briefing.data?.pack_version ?? '서버 기준을 확인하고 있습니다.'}</small></div></div>
      <Tabs value={pane} onChange={setPane} items={[{ value: 'items', label: '필수 안내' }, { value: 'documents', label: '필요 서류' }]} />
      {pane === 'items' ? <PagedList label="브리핑 항목" items={briefing.data?.must_say ?? []} empty={briefing.loading ? '브리핑을 불러오는 중입니다.' : briefing.error ? '브리핑을 확인하지 못했습니다.' : '필수 안내 항목이 없습니다.'} render={item => {
        const sections = briefingSections(item);
        const copy = <span className="wb-row-copy"><strong>{item.name}</strong><small>{sections.length ? sections[0][1].join(' · ') : item.item_code}</small></span>;
        return sections.length ? <button className="wb-row-button" onClick={() => setDetail(item)}>{copy}<span aria-hidden="true">›</span></button> : <div className="wb-row-static">{copy}</div>;
      }} /> : <PagedList label="필요 서류" items={briefing.data?.documents_required ?? []} empty={briefing.loading ? '필요 서류를 불러오는 중입니다.' : '이 상품에 등록된 필요 서류가 없습니다.'} render={item => <div className="wb-row-static"><span className="wb-row-copy"><strong>{item}</strong></span></div>} />}
      <div className="wb-briefing-footer"><label className="wb-composer"><small>입력</small><select aria-label="입력 방식" value={mode} disabled={busy} onChange={event => setMode(event.target.value as 'live' | 'text')}><option value="live">마이크 녹음</option><option value="text">텍스트 입력</option></select></label><div className="wb-actions"><button disabled={busy} onClick={onDemo}>시연 음원으로 시작</button><button className="wb-primary" disabled={busy || packs.loading || Boolean(packs.error) || !choices.some(choice => choice.pack_version === version) || !pack.data || pack.data.pack_version !== version || !briefing.data || briefing.data.pack_version !== version || briefing.loading || pack.loading} onClick={() => pack.data && onStart(pack.data, mode, customer)}>{busy ? '세션 연결 중…' : '상담 시작'} →</button></div></div>
      <small className="wb-processing-notice">마이크가 없거나 STT 가 멈추면 텍스트 입력으로 같은 판정을 받을 수 있습니다. 시연 입력은 외부 STT·AI 서비스에서 처리됩니다. 실제 개인정보를 입력하지 마세요.</small>
    </Panel>
    {detail && <Modal title={detail.name} className="wb-compact" onClose={() => setDetail(null)}><DetailSections sections={briefingSections(detail)} /><small className="wb-muted">항목 코드 {detail.item_code}</small></Modal>}
  </Workbench>;
}

type DashboardProps = { session: LiveSession; pack: ApiPack | null; health: ApiHealth | null; micActive: boolean; micPending: boolean; micError: string; replaySound?: ReplayAudioState | null; onReplaySound?: () => void; onMic: () => void; onEnd: () => void; onRetry: () => void; onTextMode: () => void; onNavigate: (nav: NavItem) => void; onNew: () => void; onCommand: (value: Record<string, unknown>) => boolean; onDismiss: () => void; onEvidence: (ref: string) => void; onItemEvidence: (item: ApiPackItem) => void; onAsk: (question: string) => void };

export function Dashboard({ session, pack, health, micActive, micPending, micError, replaySound, onReplaySound, onMic, onEnd, onRetry, onTextMode, onNavigate, onNew, onCommand, onDismiss, onEvidence, onItemEvidence, onAsk }: DashboardProps) {
  const [pane, setPane] = useState<'attention' | 'conversation' | 'checks'>('conversation'); const [detail, setDetail] = useState<{ title: string; text?: string; sections?: [string, (string | undefined)[] | undefined][]; evidenceRef?: string } | null>(null);
  const [guidePane, setGuidePane] = useState<'attention' | 'checks'>('attention');
  const [filter, setFilter] = useState<'all' | 'customer' | 'teller'>('all'); const inputRef = useRef<HTMLInputElement>(null);
  const transcript = useMemo(() => filter === 'all' ? session.transcript : session.transcript.filter(row => row.speaker === filter), [filter, session.transcript]);
  const [reference, setReference] = useState<'documents' | 'briefing' | null>(null);
  const [rephraseOpen, setRephraseOpen] = useState(false);
  const [plainCode, setPlainCode] = useState<string | null>(null);
  function selectPane(value: typeof pane) { setPane(value); if (value !== 'conversation') setGuidePane(value); }
  function requestRephrase(code?: string) {
    if (code) { setPlainCode(code); setSelected(null); setRephraseOpen(true); return; }
    // 직전 발화 쉬운 말은 그 발화 아래에 붙는다. 어느 말을 바꾼 것인지 대조가 되어야 하므로 창을 띄우지 않는다
    if (onCommand({ t: 'assist_request', assist_type: 'rephrase' })) { closeDetails(); setPane('conversation'); }
  }
  const rephraseItem = plainCode ? pack?.items.find(entry => entry.code === plainCode) : undefined;
  const rephraseText = rephraseItem ? rephraseItem.plain_language?.join('\n') : session.action?.result?.text;
  function closeDetails() { setSelected(null); setReference(null); setRephraseOpen(false); setPlainCode(null); setDetail(null); }
  function showEvidence(ref: string) { closeDetails(); onEvidence(ref); }
  function showItemEvidence(entry: ApiPackItem) { closeDetails(); onItemEvidence(entry); }
  const [selected, setSelected] = useState<string | null>(null); const [manualTab, setManualTab] = useState<'detail' | 'waive'>('detail');
  const [reason, setReason] = useState(''); const [query, setQuery] = useState(''); const [text, setText] = useState(''); const [speaker, setSpeaker] = useState('teller');
  const item: ReadyItem | undefined = session.items.find(item => item.code === selected); const packItem = pack?.items.find(entry => entry.code === selected);
  // 근거는 판정이 실어 준 event_id 가 우선. 없으면 팩 항목에 걸린 원문 위치를 쓴다.
  const itemEvidence = pack && packItem ? evidenceForItem(pack, packItem) : null;
  const intervention = session.interventions[0]; const canWrite = session.status === 'connected' && session.mode !== 'trace' && !session.ending;
  // 숫자 확인 경보는 말한 값과 설명서 값의 비교가 전부다. 서버 문구가 기준 값을
  // 다시 말하고 있어 같은 숫자가 세 번 뜨던 것을 비교 표 하나로 바꾼다.
  // 직전 발화 쉬운 말은 그 발화 아래에 이미 떠 있다. 위쪽 알림 줄이 같은 말을 되풀이하지 않게 한다
  const inlineRephrase = session.action?.kind === 'rephrase' && Boolean(session.action.sourceUtteranceId);
  const compared = Boolean(intervention?.said && intervention?.reference);
  const notice = micError || friendlyError(session.error) || replaySound?.error || (session.mode === 'live' && !session.textFallback && health?.checks?.stt === 'unconfigured' ? STT_UNCONFIGURED : '');
  function resolve() { if (intervention?.alert) { onCommand({ t: 'acknowledge', alert_ref: intervention.id }); return; } onDismiss(); }
  const manualPending = Boolean(session.action?.pending);
  const screen = sessionScreen(session.mode); const playback = screen === 'playback';
  const title = playback ? '기록 재생' : '상담';
  if (waitingForTraceUtterance(session)) return <Workbench screen={screen} title={title} subtitle={pack?.product?.name ?? session.packVersion} onNavigate={onNavigate} onNew={onNew} actions={<span className="wb-badge">기록 재생</span>}><TraceStart session={session} onEnd={onEnd} onRetry={onRetry} onHistory={() => onNavigate('이력')} /></Workbench>;
  return <Workbench screen={screen} title={title} subtitle={pack?.product?.name ?? session.packVersion} onNavigate={onNavigate} onNew={onNew} actions={<><span className="wb-badge">{session.status === 'connected' ? modeNames[session.mode] : session.status === 'connecting' ? '연결 중' : session.status === 'ended' ? '종료' : '연결 끊김'}</span><small>{session.mode === 'text' ? `${session.transcript.length}개 발화` : timeLabel(session.seconds)}</small><button disabled={session.status !== 'connected' || session.ending} onClick={onEnd}>{session.ending ? '종료 확인 중…' : playback ? '재생 종료' : '상담 종료'}</button></>}>
    {session.mode === 'trace' && session.traceHasUtterances === false && <Notice>이 기록에는 발화 없이 판정·안내만 저장되어 있습니다.</Notice>}
    <Notice action={<><button onClick={() => setDetail({ title: '연결 상태', text: notice })}>상세</button>{session.status === 'disconnected' ? <button onClick={onRetry}>다시 연결</button> : session.mode === 'live' && !session.textFallback ? <button onClick={onTextMode}>텍스트 입력</button> : null}</>}>{notice}</Notice>
    <div className="wb-mobile-tabs"><Tabs value={pane} onChange={selectPane} items={[{ value: 'conversation', label: '상담 대화' }, { value: 'attention', label: intervention ? `현재 안내 · ${session.interventions.length}` : '현재 안내' }, { value: 'checks', label: '필수 안내' }]} /></div>
    <Feedback message={micPending ? '마이크를 연결하고 있습니다.' : inlineRephrase ? undefined : session.action?.message} pending={micPending || (!inlineRephrase && session.action?.pending)} action={!rephraseOpen && !inlineRephrase && session.action?.kind === 'rephrase' && (session.action.pending || session.action.result) ? <button onClick={() => { closeDetails(); setRephraseOpen(true); }}>쉬운 말 보기</button> : undefined} />
    <div className="wb-dashboard" data-pane={pane}>
      <div className="wb-shortcuts" aria-label="상담 주요 기능">
        {session.mode === 'live' ? <QuickAction title={micPending ? '연결 취소' : micActive ? '녹음 중지' : '녹음 시작'} label={micPending ? '마이크 연결 취소' : micActive ? '■ 녹음 중지' : '● 녹음 시작'} subtitle={micPending ? '권한 창을 확인하세요' : micActive ? '중지 후에도 상담은 유지' : '완료 시 상단 상담 종료'} icon={micActive ? 'stop' : 'mic'} tone={micActive ? 'recording' : 'record'} pressed={micActive} disabled={!canWrite} onClick={onMic} /> : <QuickAction title={session.mode === 'text' ? '텍스트 입력' : '상담 대화'} subtitle={session.mode === 'text' ? '화자를 선택해 입력' : '저장된 상담 확인'} icon="conversation" tone="record" onClick={() => { selectPane('conversation'); requestAnimationFrame(() => inputRef.current?.focus()); }} />}
        <QuickAction title="필요 서류" subtitle="서류 목록 열기" icon="folder" tone="documents" disabled={!pack} onClick={() => setReference('documents')} />
        <QuickAction title="규정팩 보기" subtitle="적용 중인 규정팩의 항목" icon="book" tone="briefing" disabled={!pack} onClick={() => setReference('briefing')} />
        <div className="wb-density-chip" data-density={session.progress?.density ?? 'none'} role="status" aria-label="전문용어 밀도"><strong>{session.progress?.density ? densityNames[session.progress.density] ?? session.progress.density : '측정 전'}</strong><span>전문용어 밀도</span></div>
      </div>
      <div className="wb-conversation">
        <Panel title="상담 대화" className="wb-transcript" action={replaySound ? <button type="button" className="wb-replay-sound" data-replay-sound={replaySound.status} aria-pressed={replaySound.enabled && replaySound.status !== 'blocked'} onClick={onReplaySound} disabled={replaySound.status === 'loading' || session.ending || session.status !== 'connected'}>{replaySound.status === 'loading' ? '음원 준비 중' : replaySound.status === 'unavailable' ? '소리 다시 시도' : replaySound.status === 'blocked' || !replaySound.enabled ? '소리 켜기' : '소리 끄기'}</button> : <small role="status">{session.mode === 'live' && micActive ? health?.checks?.stt === 'ok' ? '● 녹음 중 · 전사 대기' : '● 녹음 중 · 전사 연결 확인 필요' : '고객 · 상담원'}</small>}>
          <div className="wb-conversation-filters" aria-label="대화 화자 필터"><Tabs value={filter} onChange={setFilter} items={[{ value: 'all', label: '전체' }, { value: 'customer', label: '고객' }, { value: 'teller', label: '상담원' }]} /></div>
          <Transcript key={filter} items={transcript} rephrases={session.rephrases} onEvidence={showEvidence} empty={filter === 'all' ? '첫 발화를 기다리고 있습니다.' : '이 화자의 발화가 아직 없습니다.'} onSelect={row => setDetail({ title: `${speakerLabel(row.speaker)} · ${timeLabel(row.t_ms / 1000)}`, text: row.text })} />
          {session.partial && <button className="wb-row-button wb-partial" onClick={() => setDetail({ title: '중간 전사', text: session.partial })}>듣는 중 · {session.partial}</button>}
          {session.mode === 'text' || session.textFallback ? <form className="wb-composer" onSubmit={event => { event.preventDefault(); if (text.trim() && onCommand({ t: 'text_utterance', text: text.trim(), speaker })) setText(''); }}><select aria-label="화자" value={speaker} onChange={event => setSpeaker(event.target.value)}><option value="teller">상담원</option><option value="customer">고객</option></select><input ref={inputRef} aria-label="상담 발화" value={text} maxLength={5000} onChange={event => setText(event.target.value)} placeholder="상담 발화 입력" /><button disabled={!canWrite || !text.trim()} type="submit">전송</button></form> : null}
        </Panel>
      </div>
      <div className="wb-guidance">
        <Panel title="상담 가이드" className="wb-guide-panel" action={intervention && guidePane === 'checks' && <button className="wb-guide-notification" onClick={() => selectPane('attention')}>안내 {session.interventions.length}건 보기</button>}>
        <div className="wb-guide-tabs"><Tabs value={guidePane} onChange={value => selectPane(value)} items={[{ value: 'attention', label: intervention ? `현재 안내 · ${session.interventions.length}` : '현재 안내' }, { value: 'checks', label: '필수 안내' }]} /></div>
        <div className="wb-guide-content" data-guide-pane={guidePane}>
        <Panel title={intervention ? kindNames[intervention.kind] ?? '현재 안내' : '현재 확인할 내용'} className={`wb-attention ${intervention?.kind === 'risk_signal' ? 'is-risk' : ''}`} action={intervention && <span className="wb-badge">{session.interventions.length > 1 ? `대기 ${session.interventions.length - 1}건` : '현재 1건'}</span>}>
          {intervention ? <>{compared ? <KeyValueList className="wb-compare" rows={[{ label: '말씀하신 값', value: intervention.said }, { label: '설명서 값', value: intervention.reference }, ...(intervention.condition ? [{ label: '조건', value: intervention.condition as ReactNode }] : [])]} />
            : <TextPages label="현재 안내" text={`${withoutKindPrefix(intervention.text, intervention.kind)}${intervention.said != null || intervention.reference != null ? `\n말씀하신 값: ${intervention.said ?? '미제공'}\n설명서 값: ${intervention.reference ?? '미제공'}` : ''}${intervention.condition ? `\n${intervention.condition}` : ''}`} />}<div className="wb-actions">{intervention.evidenceRef && <button onClick={() => onEvidence(intervention.evidenceRef!)}>근거 보기</button>}<button className="wb-primary" disabled={intervention.alert && (!canWrite || manualPending)} onClick={resolve}>{intervention.alert ? session.action?.kind === 'acknowledge' && manualPending ? '확인 저장 중…' : '확인 기록' : '닫기'}</button></div></> : <Empty><span className="wb-guide-empty-icon"><WorkspaceIcon name="conversation" size={32} /></span><p>{micActive ? '대화를 듣고 있습니다.' : session.mode === 'live' && !session.transcript.length ? '녹음 시작 버튼을 눌러 상담을 시작하세요.' : '확인이 필요한 안내가 없습니다.'}</p></Empty>}
          {intervention?.evidenceRef ? <EvidenceCard title="이 안내의 근거" evidenceRef={intervention.evidenceRef} onOpen={() => onEvidence(intervention.evidenceRef!)} />
            : session.recentEvidence ? <EvidenceCard title={`최근 판정 근거 · ${session.recentEvidence.name}`} evidenceRef={session.recentEvidence.ref} onOpen={() => onEvidence(session.recentEvidence!.ref)} /> : null}
        </Panel>
      <div className="wb-checks"><Panel title="필수 안내" action={<span className="wb-badge">{session.progress ? `${session.progress.met} / ${session.progress.total}` : '판정 대기'}</span>}>
        <PagedList label="필수 안내" items={session.items} rowHeight={84} empty={session.status === 'connecting' ? '기준을 연결하고 있습니다.' : '서버가 제공한 필수 항목이 없습니다.'} render={entry => {
          const source = pack?.items.find(value => value.code === entry.code);
          const undo = entry.state === 'met' && entry.decidedBy === 'human';
          return <div className="wb-check-row" data-check-item={entry.code}>
            <button className="wb-row-button" aria-label={`${entry.name} 상세`} onClick={() => { setSelected(entry.code); setManualTab('detail'); setReason(''); }}><span className="wb-row-copy"><strong>{entry.name}</strong>{entry.missing.length > 0 && <small>미충족 · {entry.missing.join(', ')}</small>}</span><span className="wb-badge" data-state={entry.state}>{statusNames[entry.state] ?? entry.state}</span></button>
            <div className="wb-check-actions" role="group" aria-label={`${entry.name} 바로 실행`}>
              <button disabled={!source?.plain_language?.length || !source?.evidence} onClick={() => requestRephrase(entry.code)}>쉬운 말</button>
              <button disabled={!canWrite || manualPending || (['met', 'waived'].includes(entry.state) && !undo)} onClick={() => onCommand({ t: 'mark_met', item_code: entry.code, ...(undo ? { undo: true } : {}) })}>{undo ? '기록 취소' : '고지 기록'}</button>
              <button disabled={!entry.evidenceRef && !source?.evidence} onClick={() => entry.evidenceRef ? showEvidence(entry.evidenceRef) : source && showItemEvidence(source)}>근거</button>
            </div>
          </div>;
        }} />
      </Panel></div>
        <div className="wb-guide-ask" aria-label="규정 질의">
          {session.mode !== 'trace' && <button disabled={!canWrite || manualPending || !session.transcript.some(row => row.speaker === 'teller')} title="직전 상담원 발화를 고객이 알기 쉬운 말로 바꿔 줍니다" onClick={() => requestRephrase()}>직전 발화 쉬운 말로</button>}
          {session.query?.pending ? <small>답변 요청 중</small> : session.query?.answer ? <button onClick={() => setDetail({ title: '규정 질의 답변', sections: [['질문', [session.query?.question]], ['답변', [session.query?.answer]]], evidenceRef: session.query?.evidenceRef })}>답변 보기</button> : null}
          <form className="wb-composer" onSubmit={event => { event.preventDefault(); if (query.trim()) { onAsk(query.trim()); setQuery(''); } }}><input aria-label="규정 질문" value={query} maxLength={2000} onChange={event => setQuery(event.target.value)} placeholder="규정에 대해 물어보세요" /><button type="submit" disabled={!canWrite || !query.trim() || session.query?.pending}>질문</button></form>
        </div>
        </div>
        </Panel>
      </div>
    </div>
    {item && <Modal title={item.name} onClose={() => setSelected(null)} actions={<>{manualTab === 'detail' && <><button disabled={!canWrite || manualPending || ['met', 'waived'].includes(item.state)} onClick={() => { if (onCommand({ t: 'mark_met', item_code: item.code })) setSelected(null); }}>고지 기록</button><button disabled={!canWrite || manualPending || item.state === 'waived'} onClick={() => setManualTab('waive')}>범위에서 제외</button></>}</>}>
      {item.state === 'met' && item.decidedBy === 'human' && <button disabled={!canWrite || manualPending} onClick={() => { if (onCommand({ t: 'mark_met', item_code: item.code, undo: true })) setSelected(null); }}>기록 취소</button>}
      {manualTab === 'detail' ? <>
        <div className="wb-detail-head"><span className="wb-badge" data-state={item.state}>{statusNames[item.state] ?? item.state}</span>{packItem && <span className="wb-badge">{itemTypeNames[packItem.type] ?? packItem.type}</span>}{item.decidedBy === 'human' && <small>상담원이 직접 기록</small>}</div>
        {(item.evidenceRef || itemEvidence) && <EvidenceCard title="이 항목의 근거" evidenceRef={item.evidenceRef} evidence={item.evidenceRef ? undefined : itemEvidence} onOpen={() => item.evidenceRef ? showEvidence(item.evidenceRef) : packItem && showItemEvidence(packItem)} />}
        <DetailSections empty="이 항목에 등록된 상세 내용이 없습니다." sections={[['아직 확인되지 않은 요소', item.missing], ['승인된 쉬운 말', item.plain.length ? item.plain : packItem?.plain_language], ['필수 안내 요소', packItem?.requirement_elements], ['필요 서류', packItem?.documents_required], ['금지 표현 예시', packItem?.forbidden_examples]]} />
      </> : <form className="wb-form" onSubmit={event => { event.preventDefault(); if (reason.trim() && onCommand({ t: 'mark_waived', item_code: item.code, reason: reason.trim() })) setSelected(null); }}><label className="wb-wide">제외 사유<textarea aria-label="제외 사유" required maxLength={1000} value={reason} onChange={event => setReason(event.target.value)} /></label><button type="button" onClick={() => setManualTab('detail')}>취소</button><button className="wb-primary" disabled={!canWrite || manualPending || !reason.trim()} type="submit">제외 사유 기록</button></form>}
    </Modal>}
    {reference && pack && <Modal title={reference === 'documents' ? '필요 서류' : '적용 중인 규정팩'} className="wb-modal-tall" onClose={() => setReference(null)}>
      <small>{pack.product?.name} · {pack.pack_version}</small>
      {reference === 'documents' ? <PagedList label="상담 필요 서류" items={Array.from(new Set(pack.items.flatMap(entry => entry.documents_required ?? [])))} empty="현재 규정팩에 등록된 필요 서류가 없습니다." render={document => <strong>{document}</strong>} /> : <PagedList label="상담 기준 항목" items={pack.items.filter(entry => entry.type === 'required')} render={entry => <button className="wb-row-button" onClick={() => { setReference(null); setSelected(entry.code); setManualTab('detail'); setReason(''); }}><span className="wb-row-copy"><strong>{entry.name}</strong><small>기준·승인된 쉬운 말 보기</small></span><span>›</span></button>} />}
    </Modal>}
    {rephraseOpen && <Modal title={rephraseItem ? `쉬운 말 · ${rephraseItem.name}` : '직전 발화 쉬운 말'} onClose={() => setRephraseOpen(false)} actions={<>{(rephraseItem ? rephraseItem.evidence : session.action?.result?.evidenceRef) && <button onClick={() => rephraseItem ? showItemEvidence(rephraseItem) : session.action?.result?.evidenceRef && showEvidence(session.action.result.evidenceRef)}>근거 원문</button>}{!rephraseItem && <button disabled={!canWrite || manualPending} onClick={() => requestRephrase()}>{manualPending ? '요청 중…' : '다시 요청'}</button>}</>}>
      {!rephraseItem && <Feedback message={session.action?.message} pending={session.action?.pending} />}
      {rephraseText ? <TextPages text={rephraseText} label="쉬운 말 안내" /> : <Empty>{session.action?.pending ? '직전 상담원 발화를 쉬운 말로 바꾸고 있습니다.' : '이 항목에는 승인된 쉬운 말이 없습니다.'}</Empty>}
      {rephraseItem && <small className="wb-muted">규정팩에서 검수·승인된 문장입니다. 그대로 읽어 주셔도 됩니다.</small>}
    </Modal>}
    {detail && <Modal title={detail.title} onClose={() => setDetail(null)} actions={detail.evidenceRef && <button onClick={() => showEvidence(detail.evidenceRef!)}>근거 원문</button>} className="wb-compact">{detail.sections ? <DetailSections sections={detail.sections} /> : <TextPages text={detail.text ?? ''} />}</Modal>}
  </Workbench>;
}
