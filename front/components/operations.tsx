'use client';

import { useEffect, useState } from 'react';
import { ApiDocument, ApiPackItem, ApiPreset, ApiSessionSummary, malteumApi } from '../lib/api';
import { displayField, displayValue, errorText, evidenceForItem, INTERNAL_FIELDS, itemTypeNames, labelState, latestPacks, modeNames, NavItem, statusNames, textValue, timeLabel, whenLabel, withoutKindPrefix, withoutStateArrow } from '../lib/workspace-model';
import { EvidenceCard } from './evidence';
import { rememberedSessionIds } from '../lib/session-index';
import { HistoryAction, traceBlockedReason } from '../lib/session-recovery';
import { exportReport } from '../lib/report-print';
import { DetailSections, Empty, EvidenceView, Feedback, KeyValueList, Modal, Notice, PagedList, Panel, ScrollList, Tabs, TextPages, useResource, Workbench } from './workspace';

type Navigation = { onNavigate: (nav: NavItem) => void; onNew: () => void };
function Failure({ error, retry }: { error: string; retry: () => void }) { return <Notice action={<button onClick={retry}>다시 불러오기</button>}>{error}</Notice>; }
const labelFor = displayField;
// 요약 수치 중 큰 타일로 나간 것을 뺀 나머지(필수 항목 수·제외·채택한 안내 등)만 표로.
// 같은 값을 타일과 표에 두 번 싣지 않는다
function summaryRows(summary: Record<string, unknown> | undefined, shown: string[]) {
  return Object.entries(summary ?? {})
    .filter(([key, value]) => !shown.includes(key) && value != null && value !== '')
    .map(([key, value]) => ({ label: displayField(key), value: <span className="wb-kv-text">{displayValue(value, key)}</span> }));
}
// One row per field; nested values keep their readable text form.
// `message` 는 이미 `설명서 기준 15.4% (조건)` 처럼 reference·condition 을 문장으로 담고
// 있다. comparison 을 그대로 펼치면 그 두 값이 한 번 더 줄로 뜬다. 새 정보인 said 만 남긴다.
function recordRows(row: Record<string, unknown>) {
  const comparison = row.comparison as { said?: unknown } | undefined;
  const trimmed = comparison?.said != null ? { ...row, comparison: { said: comparison.said } } : row;
  return Object.entries(trimmed)
    .filter(([key, value]) => value != null && value !== '' && !INTERNAL_FIELDS.includes(key) && !(Array.isArray(value) && value.length === 0))
    .map(([key, value]) => ({ label: displayField(key), value: <span className="wb-kv-text">{displayValue(value, key)}</span> }));
}
type ReportTab = 'omission' | 'commission' | 'comprehension' | 'risk_signals' | 'timeline';
// 탭 이름이 이미 유형을 말한다. 위험 신호 행은 `alert_type` 없이 오고 유형이 문구
// 앞에 붙어 있어, 탭에서 유형을 받아 그 머리말을 화면에서만 뗀다
const tabKind: Partial<Record<ReportTab, string>> = { risk_signals: 'risk_signal' };
const reportTabs: { value: ReportTab; label: string }[] = [{ value: 'omission', label: '설명 이행' }, { value: 'commission', label: '금지·숫자' }, { value: 'comprehension', label: '이해 지원' }, { value: 'risk_signals', label: '위험 신호' }, { value: 'timeline', label: '타임라인' }];

export function ReportScreen({ sessionId, onEvidence, onResume, onTrace, busy, error, ...navigation }: Navigation & { sessionId: string | null; onEvidence: (ref: string) => void; onResume: (record: ApiSessionSummary) => void; onTrace: (record: ApiSessionSummary) => void; busy: boolean; error: string }) {
  const result = useResource(async () => sessionId ? { report: await malteumApi.report(sessionId), session: await malteumApi.session(sessionId) } : null, [sessionId]);
  const report = { ...result, data: result.data?.report };
  const running = result.data?.session.status === 'running';
  const [tab, setTab] = useState<ReportTab>('omission'); const [detail, setDetail] = useState<Record<string, unknown> | null>(null);
  const sections = report.data?.sections; const rows = (sections?.[tab] ?? []) as Record<string, unknown>[];
  const summary = sections?.summary;
  // 타임라인은 시간 순서로 쭉 읽는 목록이라 스크롤로 둔다. 나머지 탭은 항목 수가 적어
  // 페이지 목록이 한 화면에 정돈돼 보인다
  const RecordList: typeof ScrollList = tab === 'timeline' ? ScrollList : PagedList;
  const [summaryOpen, setSummaryOpen] = useState(false);
  const [printError, setPrintError] = useState('');
  const [printing, setPrinting] = useState(false);
  async function savePdf() { if (!report.data || printing) return; setPrinting(true); setPrintError('서버 PDF를 요청하고 있습니다.'); try { setPrintError(await exportReport(report.data)); } catch (error) { setPrintError(errorText(error)); } finally { setPrinting(false); } }
  const shownSummary = ['met', 'partial', 'unmet', 'violations', 'alerts'].filter(key => typeof summary?.[key] === 'number');
  return <Workbench screen="report" title={running ? '중간 리포트' : '종료 리포트'} subtitle={running ? '종료 전 저장 기록 · 최종 결과가 아닙니다' : undefined} {...navigation} actions={report.data && <><span className="wb-report-version" aria-label="규정팩 버전">{report.data.pack_version}</span>{running ? <><button onClick={report.refresh} disabled={report.loading}>새로고침</button><button className="wb-primary" disabled={busy} onClick={() => result.data && onResume(result.data.session)}>상담 열기</button></> : <><button disabled={busy || !result.data || Boolean(result.data && traceBlockedReason(result.data.session))} onClick={() => result.data && onTrace(result.data.session)}>{busy ? '재생 준비 중…' : '기록 재생'}</button><button className="wb-primary" disabled={printing} onClick={savePdf}>{printing ? 'PDF 준비 중…' : 'PDF 저장'}</button></>}</>}>
    <Failure error={report.error || error} retry={report.refresh} />
    <Feedback message={printError} pending={printing} />
    {!sessionId ? <Panel><Empty><h2>이력에서 상담을 선택해 주세요.</h2><button onClick={() => navigation.onNavigate('이력')}>세션 이력 보기</button></Empty></Panel> : report.loading ? <Panel><Empty>리포트를 불러오고 있습니다.</Empty></Panel> : !report.data ? <Panel><Empty>리포트를 불러오지 못했습니다.</Empty></Panel> : <>
      {shownSummary.length > 0 && <div className="wb-summary">{shownSummary.map(key => <div key={key}><strong>{String(summary?.[key])}</strong><span>{labelFor(key)}</span></div>)}</div>}
      <div className="wb-toolbar"><Tabs value={tab} onChange={setTab} items={reportTabs} /><label className="wb-report-tab-select">항목<select aria-label="리포트 항목" value={tab} onChange={event => setTab(event.target.value as ReportTab)}>{reportTabs.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label><button onClick={() => setSummaryOpen(true)}>요약·출처</button></div>
      <Panel title={tab === 'comprehension' ? '이해 지원 기록 · 판정 증빙 아님' : '항목별 기록'}><RecordList key={tab} label="리포트" items={rows} empty="이 항목에 대한 서버 기록이 없습니다." render={row => {
        // 경보 전용 표기는 `alert_type` 을 싣고 오는 행(금지·숫자·위험 신호 탭)에만 쓴다.
        // 타임라인의 경보 행은 그 필드가 없고 유형이 `label` 안에 있어, 그대로 태우면
        // 제목이 `미제공 · ` 로 시작했다
        const alert = row.kind === 'alert' && typeof row.alert_type === 'string';
        // 타임라인 행만 상태를 라벨 끝(`<항목> → met`)에 실어 보낸다. 배지로 옮겨 색으로
        // 읽히게 하고, 제목에서는 그 화살표를 떼 같은 말이 두 번 나오지 않게 한다
        const state = alert ? (row.acknowledged ? 'met' : 'violated') : String(row.state ?? row.final_state ?? row.outcome ?? labelState(row.label));
        const label = typeof row.label === 'string' ? withoutStateArrow(row.label) : undefined;
        const kind = typeof row.alert_type === 'string' ? row.alert_type : tabKind[tab];
        const title = alert ? `${displayValue(row.alert_type, 'alert_type')} · ${displayValue(row.name ?? row.item_code ?? '', 'name')}`
          : withoutKindPrefix(displayValue(row.name ?? label ?? row.message ?? row.item_code ?? row.assist_type ?? row.alert_type ?? '기록 상세', label ? 'label' : row.assist_type ? 'assist_type' : row.alert_type ? 'alert_type' : 'name'), kind);
        const badge = alert ? (row.acknowledged ? '확인 기록' : '미확인 경보') : state ? displayValue(state, 'state') : '';
        const note = alert ? `${timeLabel(Number(row.t_ms ?? 0) / 1000)} · ${withoutKindPrefix(textValue(row.message), kind)}` : typeof row.t_ms === 'number' ? timeLabel(row.t_ms / 1000) : textValue(row.item_code ?? row.event_id ?? '');
        return <><button className="wb-row-button" onClick={() => setDetail(row)}><span className="wb-row-copy"><strong>{title}</strong><small>{note}</small></span>{badge && <span className="wb-badge" data-state={state}>{badge}</span>}<span>›</span></button>{typeof row.evidence_ref === 'string' && <button onClick={() => onEvidence(String(row.evidence_ref))}>근거</button>}</>;
      }} /></Panel>
    </>}
    {summaryOpen && report.data && <Modal title="리포트 요약과 출처" className="wb-report-summary" onClose={() => setSummaryOpen(false)}>
      <div className="wb-report-summary-grid">
        <section className="wb-report-summary-main">
          <h3>판정 요약</h3>
          {shownSummary.length > 0 ? <div className="wb-summary">{shownSummary.map(key => <div key={key}><strong>{String(summary?.[key])}</strong><span>{labelFor(key)}</span></div>)}</div> : <Empty>서버가 보낸 요약 수치가 없습니다.</Empty>}
          <KeyValueList rows={summaryRows(summary, shownSummary)} />
          {report.data.disclaimer && <div className="wb-report-disclaimer"><h3>유의사항</h3><p>{report.data.disclaimer}</p></div>}
        </section>
        <section className="wb-report-sources">
          <h3>근거 문서 {(report.data.sources ?? []).length}건</h3>
          <div className="wb-report-source-list">
            {(report.data.sources ?? []).length > 0 ? (report.data.sources ?? []).map((source, index) => <article className="wb-report-source" key={source.doc_id ?? index}>
              <strong>{source.title ?? source.doc_id ?? '문서명 미제공'}</strong>
              <dl>
                <div><dt>발행 기관</dt><dd>{source.publisher ?? '미제공'}</dd></div>
                <div><dt>기준일</dt><dd>{source.snapshot_date ? whenLabel(source.snapshot_date) : '미제공'}</dd></div>
                {source.doc_id && <div><dt>문서 코드</dt><dd>{source.doc_id}</dd></div>}
              </dl>
            </article>) : <Empty>이 리포트에 연결된 근거 문서가 없습니다.</Empty>}
          </div>
        </section>
      </div>
    </Modal>}
    {detail && <Modal title="리포트 기록 상세" className="wb-compact" onClose={() => setDetail(null)} actions={typeof detail.evidence_ref === 'string' && <button onClick={() => { setDetail(null); onEvidence(String(detail.evidence_ref)); }}>근거 원문</button>}><KeyValueList rows={recordRows(detail)} empty="이 기록에 저장된 항목이 없습니다." /></Modal>}
  </Workbench>;
}

export function HistoryScreen({ onOpen, onStartPreset, busy, error, initialView = 'sessions', packVersion = '', ...navigation }: Navigation & { onOpen: (record: ApiSessionSummary, action: HistoryAction) => void; onStartPreset: (preset: ApiPreset) => void; busy: boolean; error: string; initialView?: 'sessions' | 'presets'; packVersion?: string }) {
  const [mode, setMode] = useState('');
  const [view, setView] = useState<'sessions' | 'presets'>(initialView);
  // 상담 준비에서 시연 음원을 바로 부르면 그 탭으로 연다.
  useEffect(() => { setView(initialView); }, [initialView]);
  const presets = useResource(() => malteumApi.presets());
  const packCatalog = useResource(() => malteumApi.packs());
  const latestPackVersions = new Set(latestPacks(packCatalog.data?.packs ?? []).map(pack => pack.pack_version));
  // 상담 준비에서 고른 규정팩의 음원을 앞에 세운다. 시연 음원은 상품 시나리오가 정해져
  // 있어 규정팩과 짝이 맞아야 하고, 목록이 섞여 있으면 어느 것을 골라야 하는지 알 수 없다
  const playablePresets = (presets.data?.presets.filter(preset => preset.mode === 'replay' && preset.audio_ref && latestPackVersions.has(preset.pack_version)) ?? [])
    .sort((a, b) => Number(b.pack_version === packVersion) - Number(a.pack_version === packVersion));
  const refreshPresets = () => { presets.refresh(); packCatalog.refresh(); };
  const records = useResource(async () => {
    const all: ApiSessionSummary[] = []; let cursor: string | undefined; const seen = new Set<string>();
    do { const result = await malteumApi.sessions(mode ? mode as ApiSessionSummary['mode'] : undefined, cursor); all.push(...result.sessions); cursor = result.next_cursor ?? undefined; if (cursor && seen.has(cursor)) throw new Error('이력 페이지 연결이 반복됩니다. 다시 불러와 주세요.'); if (cursor) seen.add(cursor); } while (cursor);
    const known = rememberedSessionIds().filter(id => !all.some(record => record.session_id === id));
    const recovered = await Promise.allSettled(known.map(id => malteumApi.session(id)));
    for (const result of recovered) if (result.status === 'fulfilled' && (!mode || result.value.mode === mode)) all.push(result.value);
    return all.sort((a,b) => b.started_at.localeCompare(a.started_at));
  }, [mode]);
  const [detail, setDetail] = useState<ApiSessionSummary | null>(null);
  return <Workbench screen="history" title="세션 이력" subtitle="저장된 상담과 시연 음원" {...navigation} actions={busy ? <span className="wb-badge" role="status">상담 확인 중…</span> : <button onClick={view === 'sessions' ? records.refresh : refreshPresets} disabled={view === 'sessions' ? records.loading : presets.loading || packCatalog.loading}>새로고침</button>}>
    <Failure error={(view === 'sessions' ? records.error : presets.error || packCatalog.error) || error} retry={view === 'sessions' ? records.refresh : refreshPresets} />
    <div className="wb-toolbar"><Tabs value={view} onChange={setView} items={[{ value: 'sessions', label: '저장된 상담' }, { value: 'presets', label: '시연 음원' }]} />{view === 'sessions' && <label>입력 방식<select aria-label="이력 입력 방식" value={mode} onChange={event => setMode(event.target.value)}><option value="">전체 (재생 기록 제외)</option>{(['live', 'text', 'replay', 'trace'] as const).map(value => <option key={value} value={value}>{modeNames[value]}</option>)}</select></label>}</div>
    {view === 'presets' ? <><Notice>{packVersion ? `상담 준비에서 고른 규정팩 ${packVersion} 의 음원이 위에 옵니다. 다른 규정팩 음원을 시작하면 그 규정팩 기준으로 판정됩니다.` : ''}</Notice>
    <Panel className="wb-history-list"><PagedList label="시연 음원" items={playablePresets} rowHeight={100} empty={presets.loading || packCatalog.loading ? '시연 음원을 불러오는 중입니다.' : presets.error || packCatalog.error ? '음원을 확인하지 못했습니다.' : '최신 규정팩에 연결된 시연 음원이 없습니다.'} render={preset => {
      const catalog = packCatalog.data?.packs.find(entry => entry.pack_version === preset.pack_version);
      const matched = Boolean(packVersion) && preset.pack_version === packVersion;
      return <><div className="wb-row-button" data-preset-id={preset.preset_id}><span className="wb-row-copy"><strong>{preset.label}</strong><small>{[catalog?.product?.name ?? preset.product_code, preset.pack_version, preset.description].filter(Boolean).join(' · ')}</small></span></div><div className="wb-actions">{packVersion && <span className="wb-badge" data-state={matched ? 'met' : 'waived'}>{matched ? '고른 규정팩' : '다른 규정팩'}</span>}<button className="wb-primary" disabled={busy} onClick={() => onStartPreset(preset)}>시연 시작</button></div></>;
    }} /></Panel></> : <>
    <Panel className="wb-history-list"><PagedList label="세션 이력" items={(records.data ?? []).filter(record => mode || record.mode !== 'trace')} rowHeight={100} empty={records.loading ? '이력을 불러오고 있습니다.' : records.error ? '이력을 확인하지 못했습니다.' : '아직 저장된 세션이 없습니다.'} render={record => <><button className="wb-row-button" data-session-id={record.session_id} onClick={() => setDetail(record)}><span className="wb-row-copy"><strong>{record.product_name ?? record.pack_version}</strong><small>{whenLabel(record.started_at)} · {modeNames[record.mode]} · {statusNames[record.status] ?? record.status}</small>{traceBlockedReason(record) && <small className="wb-history-hint">{traceBlockedReason(record)}</small>}</span></button><div className="wb-actions"><button disabled={busy} onClick={() => onOpen(record, 'report')}>{record.status === 'running' ? '중간 리포트' : '리포트'}</button>{record.status === 'running' ? <button className="wb-primary" disabled={busy} onClick={() => onOpen(record, 'resume')}>{record.mode === 'trace' || record.mode === 'replay' ? '재생 이어보기' : '상담 열기'}</button> : <button disabled={busy || Boolean(traceBlockedReason(record))} title={traceBlockedReason(record) || undefined} onClick={() => onOpen(record, 'trace')}>기록 재생</button>}</div></>} /></Panel>
    </>}
    {detail && <Modal title="세션 정보" className="wb-compact" onClose={() => setDetail(null)} actions={<><button disabled={busy} onClick={() => { onOpen(detail, 'report'); setDetail(null); }}>{detail.status === 'running' ? '중간 리포트' : '리포트'}</button>{detail.status === 'running' && <button className="wb-primary" disabled={busy} onClick={() => { onOpen(detail, 'resume'); setDetail(null); }}>{detail.mode === 'trace' || detail.mode === 'replay' ? '재생 이어보기' : '상담 열기'}</button>}</>}><KeyValueList rows={recordRows(detail)} empty="이 기록에 저장된 항목이 없습니다." /></Modal>}
  </Workbench>;
}

function ManagementTabs({ value, onNavigate }: { value: 'packs' | 'documents'; onNavigate: (nav: NavItem) => void }) {
  return <div className="wb-toolbar"><Tabs value={value} onChange={value => onNavigate(value === 'packs' ? '규정팩' : '문서')} items={[{ value: 'packs', label: '최신 규정팩' }, { value: 'documents', label: '근거 문서' }]} /></div>;
}

export function PackScreen(navigation: Navigation) {
  const packs = useResource(() => malteumApi.packs());
  const choices = latestPacks(packs.data?.packs ?? []);
  const [selected, setSelected] = useState('');
  const pack = useResource(() => selected ? malteumApi.pack(selected) : Promise.resolve(null), [selected]);
  const [item, setItem] = useState<ApiPackItem | null>(null);
  const [sourceOpen, setSourceOpen] = useState(false);
  useEffect(() => {
    if (packs.data && selected && !latestPacks(packs.data.packs).some(value => value.pack_version === selected)) { setSelected(''); setItem(null); }
  }, [packs.data, selected]);
  const evidence = item && pack.data ? evidenceForItem(pack.data, item) : null;
  return <Workbench screen="packs" title="규정 관리" subtitle="상품별 최신 규정과 승인된 설명을 확인하세요." {...navigation} actions={<button onClick={() => { packs.refresh(); pack.refresh(); }}>새로고침</button>}>
    <ManagementTabs value="packs" onNavigate={navigation.onNavigate} />
    <Failure error={packs.error || pack.error} retry={() => { packs.refresh(); pack.refresh(); }} />
    {!selected ? <Panel title="최신 규정팩"><PagedList label="규정팩" items={choices} rowHeight={76} empty={packs.loading ? '규정팩 목록을 불러오고 있습니다.' : '발행된 규정팩이 없습니다.'} render={value => <button className="wb-row-button" onClick={() => setSelected(value.pack_version)}><span className="wb-row-copy"><strong>{value.product?.name ?? value.pack_version}</strong><small>{value.pack_version} · {value.published_at ? new Date(value.published_at).toLocaleDateString('ko-KR') : ''}</small></span><span className="wb-badge">{value.item_count == null ? '최신 버전' : `${value.item_count}개 항목`}</span><span>›</span></button>} /></Panel>
      : <Panel title={pack.data?.product?.name ?? selected} action={<button onClick={() => { setSelected(''); setItem(null); }}>규정팩 목록</button>}><PagedList key={selected} label="규정팩 항목" items={pack.data?.items ?? []} empty={pack.loading ? '규정팩 항목을 불러오고 있습니다.' : '항목이 없습니다.'} render={value => <button className="wb-row-button" onClick={() => { setItem(value); setSourceOpen(false); }}><span className="wb-row-copy"><strong>{value.name}</strong><small>{value.evidence ? `근거 문서 ${value.evidence.page}페이지` : '연결된 근거 없음'}</small></span><span className="wb-badge">{itemTypeNames[value.type] ?? value.type}</span><span>›</span></button>} /></Panel>}
    {item && <Modal title={item.name} className={sourceOpen ? 'wb-modal-wide' : ''} onClose={() => setItem(null)} actions={sourceOpen && <button onClick={() => setSourceOpen(false)}>규정 설명으로</button>}>
      {sourceOpen && evidence ? <EvidenceView value={evidence} /> : <>
        {evidence && <EvidenceCard evidence={evidence} title="이 규정의 근거" onOpen={() => setSourceOpen(true)} />}
        <DetailSections empty="이 항목에 등록된 상세 내용이 없습니다." sections={[['필수 안내 요소', item.requirement_elements], ['승인된 쉬운 말', item.plain_language], ['필요 서류', item.documents_required], ['금지 표현 예시', item.forbidden_examples], ['위험 신호 예시', item.risk_examples]]} />
        <small className="wb-muted">{item.code} · {itemTypeNames[item.type] ?? item.type} · 승인: {item.approved_by ?? '미제공'}{item.approved_at ? ` · ${whenLabel(item.approved_at)}` : ''}</small>
      </>}
    </Modal>}
  </Workbench>;
}

export function DocumentsScreen(navigation: Navigation) {
  const documents = useResource(() => malteumApi.documents());
  const [doc, setDoc] = useState<ApiDocument | null>(null);
  return <Workbench screen="documents" title="근거 문서" subtitle="현재 규정팩에 연결된 원문을 페이지별로 살펴보세요." {...navigation} actions={<button onClick={documents.refresh} disabled={documents.loading}>새로고침</button>}>
    <ManagementTabs value="documents" onNavigate={navigation.onNavigate} />
    <Failure error={documents.error} retry={documents.refresh} />
    <Panel title="문서 목록"><PagedList label="문서 목록" items={documents.data?.documents ?? []} rowHeight={78} empty={documents.loading ? '문서를 불러오고 있습니다.' : '등록된 문서가 없습니다.'} render={value => <button className="wb-row-button" onClick={() => setDoc(value)}><span className="wb-row-copy"><strong>{value.title}</strong><small>{value.publisher} · {value.snapshot_date}</small></span><span className="wb-badge">{value.page_count ? `${value.page_count}페이지` : '원문 보기'}</span><span>›</span></button>} /></Panel>
    {doc && <Modal title={doc.title} className="wb-modal-wide" onClose={() => setDoc(null)}><EvidenceView key={doc.doc_id} value={{ doc_id: doc.doc_id, doc_title: doc.title, publisher: doc.publisher, snapshot_date: doc.snapshot_date, source_url: doc.url, page: 1, span: '' }} /></Modal>}
  </Workbench>;
}
