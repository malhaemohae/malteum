'use client';

import { useEffect, useState } from 'react';
import { ApiCandidate, ApiDocument, ApiPack, ApiPackItem, ApiSessionSummary, hasAdminToken, malteumApi, setAdminToken } from '../lib/api';
import { errorText, evidenceForItem, fieldNames, NavItem, statusNames, textValue, timeLabel } from '../lib/workspace-model';
import { rememberedSessionIds } from '../lib/session-index';
import { openReportPrint } from '../lib/report-print';
import { Empty, EvidenceView, Modal, Notice, PagedList, Panel, Tabs, TextPages, useResource, Workbench } from './workspace';

type Navigation = { onNavigate: (nav: NavItem) => void; onNew: () => void };
function Failure({ error, retry }: { error: string; retry: () => void }) { return <Notice action={<button onClick={retry}>다시 불러오기</button>}>{error}</Notice>; }
const labelFor = (key: string) => fieldNames[key] ?? key;
const detailText = (row: Record<string, unknown>) => Object.entries(row).map(([key, value]) => `${labelFor(key)}\n${typeof value === 'string' ? statusNames[value] ?? value : textValue(value)}`).join('\n\n');

export function ReportScreen({ sessionId, ended, onEvidence, ...navigation }: Navigation & { sessionId: string | null; ended: boolean; onEvidence: (ref: string) => void }) {
  const report = useResource(() => sessionId && ended ? malteumApi.report(sessionId) : Promise.resolve(null), [sessionId, ended]);
  const [tab, setTab] = useState<'omission' | 'commission' | 'comprehension' | 'risk_signals' | 'timeline'>('omission'); const [detail, setDetail] = useState<Record<string, unknown> | null>(null);
  const sections = report.data?.sections; const rows = (sections?.[tab] ?? []) as Record<string, unknown>[];
  const summary = sections?.summary;
  const [printError, setPrintError] = useState('');
  const shownSummary = ['met', 'partial', 'unmet', 'violations'].filter(key => typeof summary?.[key] === 'number');
  return <Workbench screen="report" title="종료 리포트" {...navigation} actions={report.data && <><span className="wb-report-version" aria-label="규정 팩 버전">{report.data.pack_version}</span><button className="wb-primary" onClick={() => setPrintError(openReportPrint(report.data!) ? '' : '인쇄 창을 열지 못했습니다. 이 사이트의 팝업을 허용한 뒤 다시 시도해 주세요.')}>PDF 저장</button></>}>
    <Failure error={report.error} retry={report.refresh} />
    <Notice>{printError}</Notice>
    {!sessionId || !ended ? <Panel><Empty><h2>상담 종료 후 리포트를 확인할 수 있습니다.</h2><button onClick={() => navigation.onNavigate('상담')}>상담으로 돌아가기</button></Empty></Panel> : report.loading ? <Panel><Empty>리포트를 불러오고 있습니다.</Empty></Panel> : !report.data ? <Panel><Empty>리포트를 불러오지 못했습니다.</Empty></Panel> : <>
      {shownSummary.length > 0 && <div className="wb-summary">{shownSummary.map(key => <div key={key}><strong>{String(summary?.[key])}</strong><span>{labelFor(key)}</span></div>)}</div>}
      <div className="wb-toolbar"><Tabs value={tab} onChange={setTab} items={[{ value: 'omission', label: '설명 이행' }, { value: 'commission', label: '금지·숫자' }, { value: 'comprehension', label: '이해 지원' }, { value: 'risk_signals', label: '위험 신호' }, { value: 'timeline', label: '타임라인' }]} /><button onClick={() => setDetail({ ...(summary ?? {}), ...(report.data?.sources ? { '출처': report.data.sources } : {}), ...(report.data?.disclaimer ? { '유의사항': report.data.disclaimer } : {}) })}>요약·출처</button></div>
      <Panel title="항목별 증빙"><PagedList key={tab} label="리포트" items={rows} empty="이 항목에 대한 서버 기록이 없습니다." render={row => <><button className="wb-row-button" onClick={() => setDetail(row)}><span className="wb-row-copy"><strong>{textValue(row.name ?? row.label ?? row.message ?? row.item_code ?? row.assist_type ?? row.alert_type ?? '기록 상세')}</strong><small>{typeof row.t_ms === 'number' ? timeLabel(row.t_ms / 1000) : textValue(row.item_code ?? row.event_id ?? '')}</small></span><span className="wb-badge" data-state={String(row.state ?? row.final_state ?? row.outcome ?? '')}>{statusNames[String(row.state ?? row.final_state ?? row.outcome)] ?? textValue(row.state ?? row.final_state ?? row.outcome ?? '')}</span><span>›</span></button>{typeof row.evidence_ref === 'string' && <button onClick={() => onEvidence(String(row.evidence_ref))}>근거</button>}</>} /></Panel>
    </>}
    {detail && <Modal title="리포트 기록 상세" onClose={() => setDetail(null)} actions={typeof detail.evidence_ref === 'string' && <button onClick={() => onEvidence(String(detail.evidence_ref))}>근거 원문</button>}><TextPages text={detailText(detail)} /></Modal>}
  </Workbench>;
}

export function HistoryScreen({ onOpen, busy, error, ...navigation }: Navigation & { onOpen: (record: ApiSessionSummary, trace: boolean) => void; busy: boolean; error: string }) {
  const [mode, setMode] = useState('');
  const records = useResource(async () => {
    const all: ApiSessionSummary[] = []; let cursor: string | undefined; const seen = new Set<string>();
    do { const result = await malteumApi.sessions(mode ? mode as ApiSessionSummary['mode'] : undefined, cursor); all.push(...result.sessions); cursor = result.next_cursor ?? undefined; if (cursor && seen.has(cursor)) throw new Error('이력 페이지 연결이 반복됩니다. 다시 불러와 주세요.'); if (cursor) seen.add(cursor); } while (cursor);
    const known = rememberedSessionIds().filter(id => !all.some(record => record.session_id === id));
    const recovered = await Promise.allSettled(known.map(id => malteumApi.session(id)));
    for (const result of recovered) if (result.status === 'fulfilled' && (!mode || result.value.mode === mode)) all.push(result.value);
    return all.sort((a,b) => b.started_at.localeCompare(a.started_at));
  }, [mode]);
  const [detail, setDetail] = useState<ApiSessionSummary | null>(null);
  return <Workbench screen="history" title="세션 이력" subtitle="저장된 상담과 TRACE 재생" {...navigation} actions={busy ? <span className="wb-badge" role="status">TRACE 연결 중…</span> : <button onClick={records.refresh} disabled={records.loading}>새로고침</button>}>
    <Failure error={records.error || error} retry={records.refresh} />
    <div className="wb-toolbar"><label>입력 방식<select aria-label="이력 입력 방식" value={mode} onChange={event => setMode(event.target.value)}><option value="">전체</option>{['live', 'text', 'replay', 'trace'].map(value => <option key={value} value={value}>{value.toUpperCase()}</option>)}</select></label><small>{records.data?.length ?? 0}개 세션</small></div>
    <Panel><PagedList label="세션 이력" items={records.data ?? []} rowHeight={80} empty={records.loading ? '이력을 불러오고 있습니다.' : records.error ? '이력을 확인하지 못했습니다.' : '아직 저장된 세션이 없습니다.'} render={record => <><button className="wb-row-button" onClick={() => setDetail(record)}><span className="wb-row-copy"><strong>{record.product_name ?? record.pack_version}</strong><small>{new Date(record.started_at).toLocaleString('ko-KR')} · {record.mode.toUpperCase()} · {statusNames[record.status] ?? record.status}</small></span></button><div className="wb-actions"><button disabled={busy || record.status === 'running'} onClick={() => onOpen(record, false)}>리포트</button><button disabled={busy || record.status === 'running'} onClick={() => onOpen(record, true)}>TRACE 재생</button></div></>} /></Panel>
    {detail && <Modal title="세션 정보" onClose={() => setDetail(null)}><TextPages text={detailText(detail)} /></Modal>}
  </Workbench>;
}

function ManagementTabs({ value, onNavigate, onAuthorized }: { value: 'packs' | 'documents'; onNavigate: (nav: NavItem) => void; onAuthorized?: () => void }) {
  const [open, setOpen] = useState(false); const [token, setToken] = useState(''); const [error, setError] = useState(''); const [busy, setBusy] = useState(false); const [authorized, setAuthorized] = useState(hasAdminToken);
  async function authenticate() {
    if (!token.trim() || busy) return;
    setBusy(true); setError(''); setAdminToken(token);
    try {
      const docs = await malteumApi.documents();
      if (!docs.documents.length) throw new Error('인증을 확인할 문서가 없습니다. 관리자에게 문의하세요.');
      await malteumApi.extraction(docs.documents[0].doc_id);
      setAuthorized(true); setToken(''); setOpen(false); onAuthorized?.();
    } catch { setAdminToken(''); setAuthorized(false); setError('관리자 인증에 실패했습니다. 토큰과 서버 연결을 확인하세요.'); }
    finally { setBusy(false); }
  }
  return <><div className="wb-toolbar"><Tabs value={value} onChange={value => onNavigate(value === 'packs' ? '규정 팩' : '문서')} items={[{ value: 'packs', label: '규정 팩' }, { value: 'documents', label: '문서 검수' }]} /><button onClick={() => { if (authorized) { setAdminToken(''); setAuthorized(false); onAuthorized?.(); } else { setOpen(true); setError(''); } }}>{authorized ? '인증 해제' : '관리자 인증'}</button></div>
    {open && <Modal title="관리자 인증" onClose={() => { if (!busy) { setOpen(false); setToken(''); } }} actions={<button className="wb-primary" disabled={busy || !token.trim()} onClick={authenticate}>{busy ? '확인 중…' : '인증 확인'}</button>}><Notice>{error}</Notice><label>관리자 토큰<input type="password" autoComplete="off" value={token} onChange={event => setToken(event.target.value)} disabled={busy} /></label><p>문서 추출 조회·업로드·후보 승인·팩 발행에 필요합니다. 토큰은 이 화면을 새로고침하면 해제됩니다.</p></Modal>}
  </>;
}

export function PackScreen(navigation: Navigation) {
  const packs = useResource(() => malteumApi.packs()); const [selected, setSelected] = useState('');
  const pack = useResource(() => selected ? malteumApi.pack(selected) : Promise.resolve(null), [selected]);
  const [item, setItem] = useState<ApiPackItem | null>(null); const [tab, setTab] = useState<'detail' | 'evidence'>('detail');
  const [publish, setPublish] = useState(false); const [upload, setUpload] = useState<Record<string, unknown> | null>(null); const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  async function publishPack() { if (!upload || busy) return; setBusy(true); setError(''); try { await malteumApi.publishPack(upload); setPublish(false); setUpload(null); packs.refresh(); } catch (reason) { setError(errorText(reason)); } finally { setBusy(false); } }
  const evidence = item && pack.data ? evidenceForItem(pack.data, item) : null;
  return <Workbench screen="packs" title="기준 관리" subtitle={selected || '서버에 발행된 규정 팩'} {...navigation} actions={<button onClick={() => { setPublish(true); setError(''); }}>규정 팩 발행</button>}>
    <ManagementTabs value="packs" onNavigate={navigation.onNavigate} /><Failure error={packs.error || pack.error} retry={() => { packs.refresh(); pack.refresh(); }} />
    {!selected ? <Panel title="발행된 규정 팩"><PagedList label="규정 팩" items={packs.data?.packs ?? []} rowHeight={76} empty={packs.loading ? '팩 목록을 불러오고 있습니다.' : '발행된 팩이 없습니다.'} render={value => <button className="wb-row-button" onClick={() => setSelected(value.pack_version)}><span className="wb-row-copy"><strong>{value.product?.name ?? value.pack_version}</strong><small>{value.pack_version} · {value.published_at ? new Date(value.published_at).toLocaleDateString('ko-KR') : ''}</small></span><span className="wb-badge">{value.item_count == null ? '항목 수 미제공' : `${value.item_count}개 항목`}</span><span>›</span></button>} /></Panel> : <Panel title={pack.data?.product?.name ?? selected} action={<button onClick={() => { setSelected(''); setItem(null); }}>팩 목록</button>}><PagedList key={selected} label="팩 항목" items={pack.data?.items ?? []} empty={pack.loading ? '팩 항목을 불러오고 있습니다.' : '항목이 없습니다.'} render={value => <button className="wb-row-button" onClick={() => { setItem(value); setTab('detail'); }}><span className="wb-row-copy"><strong>{value.name}</strong><small>{value.code}</small></span><span className="wb-badge">{{ required: '필수', forbidden: '금지', reference: '참고', risk: '위험' }[value.type] ?? value.type}</span><span>›</span></button>} /></Panel>}
    {item && <Modal title={item.name} onClose={() => setItem(null)}><Tabs value={tab} onChange={setTab} items={[{ value: 'detail', label: '기준·쉬운 말' }, { value: 'evidence', label: '근거 원문' }]} />{tab === 'evidence' ? evidence ? <EvidenceView value={evidence} /> : <Empty>이 항목에는 근거가 제공되지 않았습니다.</Empty> : <TextPages text={`${item.name}\n${item.code}\n\n필수 요소\n${item.requirement_elements?.join('\n') ?? '미제공'}\n\n승인된 쉬운 말\n${item.plain_language?.join('\n') ?? '미제공'}${item.documents_required ? `\n\n필요 서류\n${item.documents_required.join('\n')}` : ''}${item.forbidden_examples ? `\n\n금지 표현 예시\n${item.forbidden_examples.join('\n')}` : ''}${item.risk_examples ? `\n\n위험 신호 예시\n${item.risk_examples.join('\n')}` : ''}\n\n승인자: ${item.approved_by ?? '미제공'}\n승인 시각: ${item.approved_at ?? '미제공'}`} />}</Modal>}
    {publish && <Modal title="규정 팩 발행" onClose={() => !busy && setPublish(false)} actions={<button className="wb-primary" disabled={!upload || busy} onClick={publishPack}>{busy ? '발행 중…' : '확인 후 발행'}</button>}><Notice>{error}</Notice><label>검수·승인된 규정 팩 JSON<input type="file" accept=".json,application/json" aria-label="규정 팩 JSON" disabled={busy} onChange={async event => { setUpload(null); setError(''); const file = event.target.files?.[0]; if (!file) return; try { const parsed: unknown = JSON.parse(await file.text()); if (!parsed || typeof parsed !== 'object' || !('pack_version' in parsed) || !('items' in parsed) || !Array.isArray(parsed.items)) throw new Error('pack_version과 items가 있는 규정 팩 파일을 선택하세요.'); setUpload(parsed as Record<string, unknown>); } catch (reason) { setError(errorText(reason)); } }} /></label>{upload ? <TextPages text={JSON.stringify(upload, null, 2)} label="발행 내용" /> : <Empty>기존 문서 후보 승인은 문서 검수에서 진행합니다. 새 팩의 근거·승인·버전 검증은 서버에서 수행합니다.</Empty>}</Modal>}
  </Workbench>;
}

type Block = { block_id?: string; page?: number; kind?: string; text?: string; table?: { rows?: number; cols?: number; cells?: { r: number; c: number; text: string }[] } };
function ExtractedTable({ block }: { block: Block }) {
  const [column, setColumn] = useState(0); const [cell, setCell] = useState<string | null>(null);
  const cells = block.table?.cells ?? []; const rowIds = Array.from(new Set(cells.map(cell => cell.r))).sort((a,b) => a-b); const columnIds = Array.from(new Set(cells.map(cell => cell.c))).sort((a,b) => a-b);
  const shown = columnIds.slice(column * 2, column * 2 + 2);
  return <><div className="wb-toolbar"><small>원문 표 · 행과 열 구조 유지</small><div className="wb-actions"><button disabled={column === 0} onClick={() => setColumn(value => value - 1)}>이전 열</button><small>{column + 1}/{Math.max(1,Math.ceil(columnIds.length / 2))}</small><button disabled={(column + 1) * 2 >= columnIds.length} onClick={() => setColumn(value => value + 1)}>다음 열</button></div></div><PagedList label="원문 표 행" items={rowIds} rowHeight={80} render={r => <div role="row" className="wb-table-row">{shown.map(c => <button role="cell" key={c} className="wb-row-button" onClick={() => setCell(cells.find(cell => cell.r === r && cell.c === c)?.text ?? '')}><span className="wb-row-copy"><small>행 {r + 1} · 열 {c + 1}</small><strong>{cells.find(cell => cell.r === r && cell.c === c)?.text ?? ''}</strong></span></button>)}</div>} />{cell !== null && <Modal title="표 셀 원문" onClose={() => setCell(null)}><TextPages text={cell} /></Modal>}</>;
}

export function DocumentsScreen(navigation: Navigation) {
  const documents = useResource(() => malteumApi.documents()); const [doc, setDoc] = useState<ApiDocument | null>(null); const [view, setView] = useState<'candidates' | 'extraction'>('candidates');
  const candidates = useResource(() => doc ? malteumApi.candidates(doc.doc_id) : Promise.resolve(null), [doc?.doc_id]);
  const extraction = useResource(() => doc && view === 'extraction' ? malteumApi.extraction(doc.doc_id) : Promise.resolve(null), [doc?.doc_id, view]);
  const [candidate, setCandidate] = useState<ApiCandidate | null>(null); const [block, setBlock] = useState<Block | null>(null); const [reviewer, setReviewer] = useState('');
  const [upload, setUpload] = useState(false); const [file, setFile] = useState<File | null>(null); const [docId, setDocId] = useState(''); const [publisher, setPublisher] = useState(''); const [date, setDate] = useState(''); const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  useEffect(() => { if (!doc || extraction.data?.status !== 'extracting') return; const timer = setInterval(() => { extraction.refresh(); candidates.refresh(); }, 4000); return () => clearInterval(timer); }, [doc?.doc_id, extraction.data?.status]);
  async function uploadFile() { if (!file || !docId.trim() || !publisher.trim() || !date || busy) return; setBusy(true); setError(''); try { await malteumApi.uploadDocument(file, { docId: docId.trim(), title: file.name, publisher: publisher.trim(), snapshotDate: date }); documents.refresh(); setUpload(false); setFile(null); } catch (reason) { setError(errorText(reason)); } finally { setBusy(false); } }
  async function approve() { if (!doc || !candidate || candidate.span_verified !== true || !reviewer.trim() || busy) return; setBusy(true); setError(''); try { await malteumApi.approveCandidate(doc.doc_id, candidate.candidate_id, reviewer.trim()); setCandidate(null); candidates.refresh(); documents.refresh(); } catch (reason) { setError(errorText(reason)); } finally { setBusy(false); } }
  const blocks = Array.isArray(extraction.data?.blocks) ? extraction.data.blocks as Block[] : [];
  return <Workbench screen="documents" title="기준 관리" subtitle={doc?.title ?? '문서 업로드·추출·검수'} {...navigation} actions={<button className="wb-primary" onClick={() => { setUpload(true); setError(''); }}>PDF 업로드</button>}>
    <ManagementTabs value="documents" onNavigate={navigation.onNavigate} onAuthorized={() => { documents.refresh(); extraction.refresh(); }} /><Failure error={documents.error || (view === 'candidates' ? candidates.error : extraction.error)} retry={() => { documents.refresh(); candidates.refresh(); extraction.refresh(); }} />
    {!doc ? <Panel title="문서 목록"><PagedList label="문서 목록" items={documents.data?.documents ?? []} rowHeight={78} empty={documents.loading ? '문서를 불러오고 있습니다.' : '등록된 문서가 없습니다.'} render={value => <button className="wb-row-button" onClick={() => { setDoc(value); setView('candidates'); }}><span className="wb-row-copy"><strong>{value.title}</strong><small>{value.publisher} · {value.snapshot_date}</small></span><span className="wb-badge">{{ extracting: '추출 중', ready: '추출 완료', failed: '실패' }[value.status]}</span><span>›</span></button>} /></Panel> : <>
      <div className="wb-toolbar"><Tabs value={view} onChange={setView} items={[{ value: 'candidates', label: '검수 후보' }, { value: 'extraction', label: '추출 원문' }]} /><div className="wb-actions"><button onClick={() => { candidates.refresh(); extraction.refresh(); }}>새로고침</button><button onClick={() => setDoc(null)}>문서 목록</button></div></div>
      <Panel title={view === 'candidates' ? '후보 항목' : `추출 원문 · ${extraction.data?.status === 'extracting' ? '추출 중' : extraction.data?.status === 'failed' ? '추출 실패' : '페이지별 블록'}`}>
        {view === 'candidates' ? <PagedList label="검수 후보" items={candidates.data?.candidates ?? []} empty={candidates.loading ? '검수 후보를 불러오고 있습니다.' : '서버에 등록된 검수 후보가 없습니다.'} render={value => <button className="wb-row-button" onClick={() => { setCandidate(value); setError(''); }}><span className="wb-row-copy"><strong>{value.name}</strong><small>{value.suggested_code ?? value.candidate_id} · p.{value.evidence?.page ?? '—'}</small></span><span className="wb-badge" data-state={value.status}>{value.status === 'approved' ? '승인' : value.status === 'rejected' ? '반려' : value.span_verified ? '검수 대기' : '원문 불일치'}</span><span>›</span></button>} /> : <PagedList label="추출 블록" items={blocks} empty={extraction.loading ? '추출 원문을 불러오고 있습니다.' : String(extraction.data?.error ?? '추출 블록이 없습니다.')} render={value => <button className="wb-row-button" onClick={() => setBlock(value)}><span className="wb-row-copy"><strong>{value.text || (value.kind === 'table' ? '표 원문' : value.kind ?? '추출 블록')}</strong><small>p.{value.page ?? '—'} · {value.kind}</small></span><span>›</span></button>} />}
      </Panel>
    </>}
    {candidate && <Modal title="후보 검수" onClose={() => !busy && setCandidate(null)} actions={<><input aria-label="검수자 이름" value={reviewer} onChange={event => setReviewer(event.target.value)} placeholder="검수자 이름" disabled={busy} style={{ width: 160 }} /><button className="wb-primary" disabled={busy || !reviewer.trim() || candidate.span_verified !== true || candidate.status === 'approved' || candidate.status === 'rejected'} onClick={approve}>{busy ? '승인 중…' : candidate.status === 'approved' ? '승인됨' : '검수 후 승인'}</button></>}><Notice>{error || (candidate.span_verified !== true ? '인용 구절이 검증되지 않아 승인할 수 없습니다.' : '')}</Notice><TextPages text={`${candidate.name}\n${candidate.suggested_code ?? candidate.candidate_id}\n\n필수 요소\n${candidate.requirement_elements?.join('\n') ?? '미제공'}\n\n인용 원문 · p.${candidate.evidence?.page ?? '—'}\n${candidate.evidence?.span ?? '원문이 제공되지 않았습니다.'}`} /></Modal>}
    {block && <Modal title={`추출 원문 · p.${block.page ?? '—'}`} onClose={() => setBlock(null)}>{block.kind === 'table' && block.table ? <ExtractedTable block={block} /> : <TextPages text={block.text ?? '텍스트가 제공되지 않았습니다.'} />}</Modal>}
    {upload && <Modal title="PDF 문서 업로드" onClose={() => !busy && setUpload(false)} actions={<button className="wb-primary" disabled={busy || !file || !docId.trim() || !publisher.trim() || !date} onClick={uploadFile}>{busy ? '업로드 중…' : 'PDF 업로드'}</button>}><Notice>{error}</Notice><div className="wb-form"><label className="wb-wide">PDF 파일<input type="file" accept=".pdf,application/pdf" aria-label="PDF 파일" disabled={busy} onChange={event => setFile(event.target.files?.[0] ?? null)} /></label><label>문서 ID<input value={docId} maxLength={160} disabled={busy} onChange={event => setDocId(event.target.value)} required /></label><label>발행 기관<input value={publisher} maxLength={160} disabled={busy} onChange={event => setPublisher(event.target.value)} required /></label><label>기준일<input type="date" value={date} disabled={busy} onChange={event => setDate(event.target.value)} required /></label></div></Modal>}
  </Workbench>;
}
