'use client';

import { useEffect, useState } from 'react';
import { ApiDocument, ApiPackItem, ApiPreset, ApiSessionSummary, malteumApi } from '../lib/api';
import { displayField, displayValue, errorText, evidenceForItem, itemTypeNames, latestPacks, modeNames, NavItem, statusNames, textValue, timeLabel, whenLabel } from '../lib/workspace-model';
import { EvidenceCard } from './evidence';
import { rememberedSessionIds } from '../lib/session-index';
import { HistoryAction, traceBlockedReason } from '../lib/session-recovery';
import { exportReport } from '../lib/report-print';
import { DetailSections, Empty, EvidenceView, Feedback, KeyValueList, Modal, Notice, PagedList, Panel, Tabs, TextPages, useResource, Workbench } from './workspace';

type Navigation = { onNavigate: (nav: NavItem) => void; onNew: () => void };
function Failure({ error, retry }: { error: string; retry: () => void }) { return <Notice action={<button onClick={retry}>다시 불러오기</button>}>{error}</Notice>; }
const labelFor = displayField;
// One row per field; nested values keep their readable text form.
function recordRows(row: Record<string, unknown>) { return Object.entries(row).filter(([, value]) => value != null && value !== '').map(([key, value]) => ({ label: displayField(key), value: <span className="wb-kv-text">{displayValue(value, key)}</span> })); }
type ReportTab = 'omission' | 'commission' | 'comprehension' | 'risk_signals' | 'timeline';
const reportTabs: { value: ReportTab; label: string }[] = [{ value: 'omission', label: '설명 이행' }, { value: 'commission', label: '금지·숫자' }, { value: 'comprehension', label: '이해 지원' }, { value: 'risk_signals', label: '위험 신호' }, { value: 'timeline', label: '타임라인' }];

export function ReportScreen({ sessionId, onEvidence, onResume, onTrace, busy, error, ...navigation }: Navigation & { sessionId: string | null; onEvidence: (ref: string) => void; onResume: (record: ApiSessionSummary) => void; onTrace: (record: ApiSessionSummary) => void; busy: boolean; error: string }) {
  const result = useResource(async () => sessionId ? { report: await malteumApi.report(sessionId), session: await malteumApi.session(sessionId) } : null, [sessionId]);
  const report = { ...result, data: result.data?.report };
  const running = result.data?.session.status === 'running';
  const [tab, setTab] = useState<ReportTab>('omission'); const [detail, setDetail] = useState<Record<string, unknown> | null>(null);
  const sections = report.data?.sections; const rows = (sections?.[tab] ?? []) as Record<string, unknown>[];
  const summary = sections?.summary;
  const [printError, setPrintError] = useState('');
  const [printing, setPrinting] = useState(false);
  async function savePdf() { if (!report.data || printing) return; setPrinting(true); setPrintError('서버 PDF를 요청하고 있습니다.'); try { setPrintError(await exportReport(report.data)); } catch (error) { setPrintError(errorText(error)); } finally { setPrinting(false); } }
  const shownSummary = ['met', 'partial', 'unmet', 'violations', 'alerts'].filter(key => typeof summary?.[key] === 'number');
  return <Workbench screen="report" title={running ? '중간 리포트' : '종료 리포트'} subtitle={running ? '종료 전 저장 기록 · 최종 결과가 아닙니다' : undefined} {...navigation} actions={report.data && <><span className="wb-report-version" aria-label="규정 팩 버전">{report.data.pack_version}</span>{running ? <><button onClick={report.refresh} disabled={report.loading}>새로고침</button><button className="wb-primary" disabled={busy} onClick={() => result.data && onResume(result.data.session)}>상담 열기</button></> : <><button disabled={busy || !result.data || Boolean(result.data && traceBlockedReason(result.data.session))} onClick={() => result.data && onTrace(result.data.session)}>{busy ? '재생 준비 중…' : '기록 재생'}</button><button className="wb-primary" disabled={printing} onClick={savePdf}>{printing ? 'PDF 준비 중…' : 'PDF 저장'}</button></>}</>}>
    <Failure error={report.error || error} retry={report.refresh} />
    <Feedback message={printError} pending={printing} />
    {!sessionId ? <Panel><Empty><h2>이력에서 상담을 선택해 주세요.</h2><button onClick={() => navigation.onNavigate('이력')}>세션 이력 보기</button></Empty></Panel> : report.loading ? <Panel><Empty>리포트를 불러오고 있습니다.</Empty></Panel> : !report.data ? <Panel><Empty>리포트를 불러오지 못했습니다.</Empty></Panel> : <>
      {shownSummary.length > 0 && <div className="wb-summary">{shownSummary.map(key => <div key={key}><strong>{String(summary?.[key])}</strong><span>{labelFor(key)}</span></div>)}</div>}
      <div className="wb-toolbar"><Tabs value={tab} onChange={setTab} items={reportTabs} /><label className="wb-report-tab-select">항목<select aria-label="리포트 항목" value={tab} onChange={event => setTab(event.target.value as ReportTab)}>{reportTabs.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label><button onClick={() => setDetail({ ...(summary ?? {}), ...(report.data?.sources ? { '출처': report.data.sources } : {}), ...(report.data?.disclaimer ? { '유의사항': report.data.disclaimer } : {}) })}>요약·출처</button></div>
      <Panel title={tab === 'comprehension' ? '이해 지원 기록 · 판정 증빙 아님' : '항목별 기록'}><PagedList key={tab} label="리포트" items={rows} empty="이 항목에 대한 서버 기록이 없습니다." render={row => <><button className="wb-row-button" onClick={() => setDetail(row)}><span className="wb-row-copy"><strong>{row.kind === 'alert' ? `${displayValue(row.alert_type, 'alert_type')} · ${displayValue(row.name ?? row.item_code ?? '', 'name')}` : displayValue(row.name ?? row.label ?? row.message ?? row.item_code ?? row.assist_type ?? row.alert_type ?? '기록 상세', row.label ? 'label' : row.assist_type ? 'assist_type' : row.alert_type ? 'alert_type' : 'name')}</strong><small>{row.kind === 'alert' ? `${timeLabel(Number(row.t_ms ?? 0) / 1000)} · ${textValue(row.message)}` : typeof row.t_ms === 'number' ? timeLabel(row.t_ms / 1000) : textValue(row.item_code ?? row.event_id ?? '')}</small></span><span className="wb-badge" data-state={row.kind === 'alert' ? (row.acknowledged ? 'met' : 'violated') : String(row.state ?? row.final_state ?? row.outcome ?? '')}>{row.kind === 'alert' ? (row.acknowledged ? '확인 기록' : '미확인 경보') : displayValue(row.state ?? row.final_state ?? row.outcome ?? '', 'state')}</span><span>›</span></button>{typeof row.evidence_ref === 'string' && <button onClick={() => onEvidence(String(row.evidence_ref))}>근거</button>}</>} /></Panel>
    </>}
    {detail && <Modal title="리포트 기록 상세" className="wb-compact" onClose={() => setDetail(null)} actions={typeof detail.evidence_ref === 'string' && <button onClick={() => { setDetail(null); onEvidence(String(detail.evidence_ref)); }}>근거 원문</button>}><KeyValueList rows={recordRows(detail)} empty="이 기록에 저장된 항목이 없습니다." /></Modal>}
  </Workbench>;
}

export function HistoryScreen({ onOpen, onStartPreset, busy, error, initialView = 'sessions', ...navigation }: Navigation & { onOpen: (record: ApiSessionSummary, action: HistoryAction) => void; onStartPreset: (preset: ApiPreset) => void; busy: boolean; error: string; initialView?: 'sessions' | 'presets' }) {
  const [mode, setMode] = useState('');
  const [view, setView] = useState<'sessions' | 'presets'>(initialView);
  // 상담 준비에서 시연 음원을 바로 부르면 그 탭으로 연다.
  useEffect(() => { setView(initialView); }, [initialView]);
  const presets = useResource(() => malteumApi.presets());
  const packCatalog = useResource(() => malteumApi.packs());
  const latestPackVersions = new Set(latestPacks(packCatalog.data?.packs ?? []).map(pack => pack.pack_version));
  const playablePresets = presets.data?.presets.filter(preset => preset.mode === 'replay' && preset.audio_ref && latestPackVersions.has(preset.pack_version)) ?? [];
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
    {view === 'presets' ? <Panel className="wb-history-list"><PagedList label="시연 음원" items={playablePresets} rowHeight={100} empty={presets.loading || packCatalog.loading ? '시연 음원을 불러오는 중입니다.' : presets.error || packCatalog.error ? '음원을 확인하지 못했습니다.' : '최신 규정 팩에 연결된 시연 음원이 없습니다.'} render={preset => <><div className="wb-row-button" data-preset-id={preset.preset_id}><span className="wb-row-copy"><strong>{preset.label}</strong><small>{preset.description ?? preset.pack_version}</small></span></div><div className="wb-actions"><button className="wb-primary" disabled={busy} onClick={() => onStartPreset(preset)}>시연 시작</button></div></>} /></Panel> : <>
    <Panel className="wb-history-list"><PagedList label="세션 이력" items={(records.data ?? []).filter(record => mode || record.mode !== 'trace')} rowHeight={100} empty={records.loading ? '이력을 불러오고 있습니다.' : records.error ? '이력을 확인하지 못했습니다.' : '아직 저장된 세션이 없습니다.'} render={record => <><button className="wb-row-button" data-session-id={record.session_id} onClick={() => setDetail(record)}><span className="wb-row-copy"><strong>{record.product_name ?? record.pack_version}</strong><small>{whenLabel(record.started_at)} · {modeNames[record.mode]} · {statusNames[record.status] ?? record.status}</small>{traceBlockedReason(record) && <small className="wb-history-hint">{traceBlockedReason(record)}</small>}</span></button><div className="wb-actions"><button disabled={busy} onClick={() => onOpen(record, 'report')}>{record.status === 'running' ? '중간 리포트' : '리포트'}</button>{record.status === 'running' ? <button className="wb-primary" disabled={busy} onClick={() => onOpen(record, 'resume')}>{record.mode === 'trace' || record.mode === 'replay' ? '재생 이어보기' : '상담 열기'}</button> : <button disabled={busy || Boolean(traceBlockedReason(record))} title={traceBlockedReason(record) || undefined} onClick={() => onOpen(record, 'trace')}>기록 재생</button>}</div></>} /></Panel>
    </>}
    {detail && <Modal title="세션 정보" className="wb-compact" onClose={() => setDetail(null)} actions={<><button disabled={busy} onClick={() => { onOpen(detail, 'report'); setDetail(null); }}>{detail.status === 'running' ? '중간 리포트' : '리포트'}</button>{detail.status === 'running' && <button className="wb-primary" disabled={busy} onClick={() => { onOpen(detail, 'resume'); setDetail(null); }}>{detail.mode === 'trace' || detail.mode === 'replay' ? '재생 이어보기' : '상담 열기'}</button>}</>}><KeyValueList rows={recordRows(detail)} empty="이 기록에 저장된 항목이 없습니다." /></Modal>}
  </Workbench>;
}

function ManagementTabs({ value, onNavigate }: { value: 'packs' | 'documents'; onNavigate: (nav: NavItem) => void }) {
  return <div className="wb-toolbar"><Tabs value={value} onChange={value => onNavigate(value === 'packs' ? '규정 팩' : '문서')} items={[{ value: 'packs', label: '최신 규정 팩' }, { value: 'documents', label: '근거 문서' }]} /></div>;
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
    {!selected ? <Panel title="최신 규정 팩"><PagedList label="규정 팩" items={choices} rowHeight={76} empty={packs.loading ? '팩 목록을 불러오고 있습니다.' : '발행된 팩이 없습니다.'} render={value => <button className="wb-row-button" onClick={() => setSelected(value.pack_version)}><span className="wb-row-copy"><strong>{value.product?.name ?? value.pack_version}</strong><small>{value.pack_version} · {value.published_at ? new Date(value.published_at).toLocaleDateString('ko-KR') : ''}</small></span><span className="wb-badge">{value.item_count == null ? '최신 버전' : `${value.item_count}개 항목`}</span><span>›</span></button>} /></Panel>
      : <Panel title={pack.data?.product?.name ?? selected} action={<button onClick={() => { setSelected(''); setItem(null); }}>팩 목록</button>}><PagedList key={selected} label="팩 항목" items={pack.data?.items ?? []} empty={pack.loading ? '팩 항목을 불러오고 있습니다.' : '항목이 없습니다.'} render={value => <button className="wb-row-button" onClick={() => { setItem(value); setSourceOpen(false); }}><span className="wb-row-copy"><strong>{value.name}</strong><small>{value.evidence ? `근거 문서 ${value.evidence.page}페이지` : '연결된 근거 없음'}</small></span><span className="wb-badge">{itemTypeNames[value.type] ?? value.type}</span><span>›</span></button>} /></Panel>}
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
  return <Workbench screen="documents" title="근거 문서" subtitle="현재 규정 팩에 연결된 원문을 페이지별로 살펴보세요." {...navigation} actions={<button onClick={documents.refresh} disabled={documents.loading}>새로고침</button>}>
    <ManagementTabs value="documents" onNavigate={navigation.onNavigate} />
    <Failure error={documents.error} retry={documents.refresh} />
    <Panel title="문서 목록"><PagedList label="문서 목록" items={documents.data?.documents ?? []} rowHeight={78} empty={documents.loading ? '문서를 불러오고 있습니다.' : '등록된 문서가 없습니다.'} render={value => <button className="wb-row-button" onClick={() => setDoc(value)}><span className="wb-row-copy"><strong>{value.title}</strong><small>{value.publisher} · {value.snapshot_date}</small></span><span className="wb-badge">{value.page_count ? `${value.page_count}페이지` : '원문 보기'}</span><span>›</span></button>} /></Panel>
    {doc && <Modal title={doc.title} className="wb-modal-wide" onClose={() => setDoc(null)}><EvidenceView key={doc.doc_id} value={{ doc_id: doc.doc_id, doc_title: doc.title, publisher: doc.publisher, snapshot_date: doc.snapshot_date, source_url: doc.url, page: 1, span: '' }} /></Modal>}
  </Workbench>;
}
