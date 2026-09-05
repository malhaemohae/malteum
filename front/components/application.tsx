'use client';

import { useEffect, useRef, useState } from 'react';
import { ApiEvidence, ApiHealth, ApiPack, ApiPackItem, ApiSessionSummary, findSessionEvent, malteumApi, ServerMessage, wsUrl } from '../lib/api';
import { Pcm16Capture } from '../lib/audio';
import { rememberSession } from '../lib/session-index';
import { errorText, evidenceForItem, LiveSession, Mode, NavItem, newLiveSession, reduceServer, Screen } from '../lib/workspace-model';
import MarketingLanding from './marketing-showcase';
import { Briefing, Dashboard } from './consultation';
import { DocumentsScreen, HistoryScreen, PackScreen, ReportScreen } from './operations';
import { Empty, EvidenceView, Modal, Notice, TextPages } from './workspace';

export default function Application() {
  const [screen, setScreen] = useState<Screen>('landing'); const [session, setSession] = useState<LiveSession | null>(null); const current = useRef<LiveSession | null>(null);
  const [pack, setPack] = useState<ApiPack | null>(null); const [health, setHealth] = useState<ApiHealth | null>(null); const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  const [reportTarget, setReportTarget] = useState<{ id: string; ended: boolean } | null>(null); const [newConfirm, setNewConfirm] = useState(false); const newAfterEnd = useRef(false);
  const [evidence, setEvidence] = useState<{ loading: boolean; value?: ApiEvidence; error?: string } | null>(null); const evidenceRequest = useRef(0);
  const [micActive, setMicActive] = useState(false); const [micPending, setMicPending] = useState(false); const [micError, setMicError] = useState('');
  const socket = useRef<WebSocket | null>(null); const capture = useRef<Pcm16Capture | null>(null); const connectingMic = useRef(false); const connectTimer = useRef<ReturnType<typeof setTimeout>>(); const endTimer = useRef<ReturnType<typeof setTimeout>>();
  const creating = useRef(false); const choice = useRef<{ customer: 'general' | 'professional' }>({ customer: 'general' });
  const audioSequence = useRef(0);
  const pendingAcknowledgements = useRef(new Set<string>());
  function update(value: LiveSession | null | ((previous: LiveSession | null) => LiveSession | null)) { const next = typeof value === 'function' ? value(current.current) : value; current.current = next; setSession(next); }
  function stopMic() { capture.current?.stop(); capture.current = null; connectingMic.current = false; setMicActive(false); setMicPending(false); }
  function closeSocket() { const old = socket.current; socket.current = null; old?.close(); clearTimeout(connectTimer.current); clearTimeout(endTimer.current); }
  useEffect(() => { let active = true; malteumApi.health().then(value => { if (active) setHealth(value); }).catch(() => { if (active) setHealth(null); }); return () => { active = false; socket.current?.close(); capture.current?.stop(); clearTimeout(connectTimer.current); clearTimeout(endTimer.current); }; }, []);
  useEffect(() => { if (!micActive) return; const timer = setInterval(() => update(value => value && value.status === 'connected' ? { ...value, seconds: value.seconds + 1 } : value), 1000); return () => clearInterval(timer); }, [micActive]);
  useEffect(() => { if (!session || session.status === 'ended') return; const beforeUnload = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; }; window.addEventListener('beforeunload', beforeUnload); return () => window.removeEventListener('beforeunload', beforeUnload); }, [session?.id, session?.status]);
  function navigate(value: NavItem) {
    if (creating.current) return;
    setError('');
    if (value === '상담') setScreen(current.current && current.current.status !== 'ended' ? 'dashboard' : 'briefing');
    if (value === '리포트') { if (current.current?.status === 'ended') setReportTarget({ id: current.current.id, ended: true }); setScreen('report'); }
    if (value === '이력') setScreen('history');
    if (value === '기준 관리' || value === '규정 팩') setScreen('packs');
    if (value === '문서') setScreen('documents');
  }
  function resetForNew() { stopMic(); closeSocket(); update(null); setMicError(''); setError(''); setNewConfirm(false); setScreen('briefing'); }
  function requestNew() { if (creating.current) return; if (current.current && current.current.status !== 'ended') setNewConfirm(true); else resetForNew(); }
  function command(value: Record<string, unknown>) {
    if (!current.current || current.current.status !== 'connected' || socket.current?.readyState !== WebSocket.OPEN) { update(previous => previous ? { ...previous, error: '서버 연결을 확인한 뒤 다시 시도해 주세요.' } : previous); return false; }
    if (current.current.mode === 'trace' && !['end', 'pong'].includes(String(value.t))) return false;
    if (value.t === 'acknowledge') pendingAcknowledgements.current.add(String(value.alert_ref));
    socket.current.send(JSON.stringify(value)); return true;
  }
  function connect(active: LiveSession) {
    closeSocket(); update({ ...active, status: 'connecting', error: undefined });
    const connection = new WebSocket(wsUrl(active.wsUrl)); socket.current = connection;
    let inbox = Promise.resolve();
    const isCurrent = () => socket.current === connection && current.current?.id === active.id;
    connectTimer.current = setTimeout(() => { if (isCurrent() && current.current?.status === 'connecting') { connection.close(); update(value => value ? { ...value, status: 'disconnected', error: '상담 서버 응답이 없습니다. 다시 연결해 주세요.' } : value); } }, 10000);
    connection.onopen = () => { if (!isCurrent()) return; connection.send(JSON.stringify(active.seq >= 0 ? { t: 'resume', session_id: active.id, from_seq: active.seq } : { t: 'hello', session_id: active.id, mode: active.mode, customer_profile: { type: choice.current.customer, tags: [] } })); };
    connection.onmessage = event => {
      if (!isCurrent() || typeof event.data !== 'string') return;
      try {
        const received = JSON.parse(event.data) as ServerMessage;
        if (received.t === 'ping') { connection.send(JSON.stringify({ t: 'pong' })); return; }
        inbox = inbox.then(async () => {
        if (!isCurrent()) return;
        let message = received;
        // Current WS mapping omits alert.acknowledged. Resolve that flag from the
        // persisted event, never by assuming that a successful send was a save.
        if (message.t === 'alert' && (active.mode === 'trace' || pendingAcknowledgements.current.size > 0)) {
          try {
            const event = await findSessionEvent(active.sourceSessionId ?? active.id, String(message.event_id));
            const alert = event?.alert as Record<string, unknown> | undefined;
            if (alert?.acknowledged === true) {
              message = { ...message, acknowledged: true };
              pendingAcknowledgements.current.delete(String(event?.supersedes));
            }
          } catch {
            update(value => value ? { ...value, error: '경보 확인 기록을 조회하지 못했습니다. 연결을 확인한 뒤 다시 시도해 주세요.' } : value);
          }
        }
        if (!isCurrent()) return;

        if (message.t === 'ready') clearTimeout(connectTimer.current);
        update(value => value ? reduceServer(value, message) : value);
        if (message.t === 'ended') {
          stopMic(); clearTimeout(endTimer.current); setReportTarget({ id: active.id, ended: true });
          if (newAfterEnd.current) { newAfterEnd.current = false; resetForNew(); } else setScreen('report');
        }
        }).catch(() => { if (isCurrent()) update(value => value ? { ...value, error: '서버 이벤트를 처리하지 못했습니다. 다시 연결해 주세요.' } : value); });
      } catch { update(value => value ? { ...value, error: '서버 메시지를 읽지 못했습니다. 연결을 다시 확인해 주세요.' } : value); }
    };
    const disconnected = () => { if (!isCurrent() || current.current?.status === 'ended') return; stopMic(); update(value => value ? { ...value, status: 'disconnected', ending: false, error: '서버 연결이 끊겼습니다. 다시 연결하면 저장된 이벤트부터 이어집니다.' } : value); };
    connection.onerror = disconnected; connection.onclose = disconnected;
  }
  async function start(pack: ApiPack, mode: Mode, customer: 'general' | 'professional', preset?: { preset_id: string; audio_ref?: string }) {
    if (creating.current) return; creating.current = true; setBusy(true); setError(''); setMicError(''); choice.current = { customer };
    try {
      const created = await malteumApi.createSession({ mode, pack_version: pack.pack_version, product_code: pack.product?.code, customer_profile: { type: customer, tags: [] }, ...(preset ? { preset_id: preset.preset_id, audio_ref: preset.audio_ref } : {}) });
      rememberSession(created.session_id);
      setPack(created.pack_version === pack.pack_version ? pack : await malteumApi.pack(created.pack_version));
      audioSequence.current = 0;
      pendingAcknowledgements.current.clear();
      const active = newLiveSession(created.session_id, created.ws_url, mode, created.pack_version); update(active); setScreen('dashboard'); connect(active);
      malteumApi.health().then(setHealth).catch(() => setHealth(null));
    } catch (reason) { setError(`상담을 시작하지 못했습니다. ${errorText(reason)}`); } finally { creating.current = false; setBusy(false); }
  }
  async function toggleMic() {
    update(value => value ? { ...value, textFallback: false } : value);
    if (micActive) { stopMic(); return; }
    if (connectingMic.current || current.current?.status !== 'connected') return;
    connectingMic.current = true; setMicPending(true); setMicError(''); const activeCapture = new Pcm16Capture(audioSequence.current); capture.current = activeCapture;
    try {
      await activeCapture.start((frame, sequence) => { if (socket.current?.readyState === WebSocket.OPEN) { socket.current.send(frame); audioSequence.current = sequence + 1; } });
      if (capture.current !== activeCapture || current.current?.status !== 'connected') { activeCapture.stop(); return; }
      setMicActive(true);
    } catch (reason) { activeCapture.stop(); capture.current = null; const name = reason instanceof Error ? reason.name : ''; setMicError(name === 'NotAllowedError' ? '마이크 사용이 차단되었습니다. 브라우저와 Windows의 마이크 권한을 확인해 주세요.' : name === 'NotFoundError' ? '입력 장치를 찾지 못했습니다. 마이크 연결을 확인해 주세요.' : `마이크를 시작하지 못했습니다. ${errorText(reason)}`); } finally { connectingMic.current = false; setMicPending(false); }
  }
  function endSession() {
    const active = current.current; if (!active || active.ending || active.status === 'ended') return;
    stopMic(); if (!command({ t: 'end' })) return; update(value => value ? { ...value, ending: true } : value);
    endTimer.current = setTimeout(() => { if (current.current?.id !== active.id || !current.current.ending) return; newAfterEnd.current = false; update(value => value ? { ...value, ending: false, error: '서버의 종료 확인이 도착하지 않았습니다. 연결 확인 후 다시 종료해 주세요.' } : value); }, 10000);
  }
  async function openEvidence(ref: string) {
    const requestId = ++evidenceRequest.current; setEvidence({ loading: true });
    try { const value = await malteumApi.evidence(ref); if (evidenceRequest.current === requestId) setEvidence({ loading: false, value }); } catch (reason) { if (evidenceRequest.current === requestId) setEvidence({ loading: false, error: errorText(reason) }); }
  }
  function itemEvidence(item: ApiPackItem) { if (!pack) return; const value = evidenceForItem(pack, item); setEvidence(value ? { loading: false, value } : { loading: false, error: '이 항목에는 서버 근거가 없습니다.' }); }
  function ask(question: string) { if (!command({ t: 'ask', question })) return; update(value => value ? { ...value, query: { question, pending: true } } : value); const id = current.current?.id; setTimeout(() => { const latest = current.current; if (latest && latest.id === id && latest.query?.question === question && latest.query.pending) update(value => value ? { ...value, query: { question, pending: false, answer: '응답이 지연되고 있습니다. 다시 요청할 수 있습니다.' } } : value); }, 15000); }
  async function openHistory(record: ApiSessionSummary, trace: boolean) {
    if (!trace) { setReportTarget({ id: record.session_id, ended: record.status !== 'running' }); setScreen('report'); return; }
    if (current.current && current.current.status !== 'ended') { setError('진행 중인 상담을 종료한 뒤 TRACE를 재생해 주세요.'); return; }
    if (creating.current) return; creating.current = true; setBusy(true); setError('');
    try { const created = await malteumApi.createSession({ mode: 'trace', source_session_id: record.session_id, pack_version: record.pack_version }); rememberSession(created.session_id); const selectedPack = await malteumApi.pack(created.pack_version); setPack(selectedPack); const active = { ...newLiveSession(created.session_id, created.ws_url, 'trace', created.pack_version), sourceSessionId: record.session_id }; update(active); setScreen('dashboard'); connect(active); } catch (reason) { setError(errorText(reason)); } finally { creating.current = false; setBusy(false); }
  }
  const navigation = { onNavigate: navigate, onNew: requestNew };
  let page;
  if (screen === 'landing') page = <MarketingLanding onStart={() => setScreen('briefing')} onNavigate={navigate} />;
  else if (screen === 'briefing') page = <Briefing {...navigation} busy={busy} onStart={start} />;
  else if (screen === 'dashboard' && session) page = <Dashboard {...navigation} session={session} pack={pack} health={health} micActive={micActive} micPending={micPending} micError={micError} onMic={toggleMic} onEnd={endSession} onRetry={() => connect(session)} onTextMode={() => { stopMic(); setMicError(''); update(value => value ? { ...value, textFallback: true, error: undefined } : value); }} onCommand={command} onDismiss={() => update(value => value ? { ...value, interventions: value.interventions.slice(1) } : value)} onEvidence={openEvidence} onItemEvidence={itemEvidence} onAsk={ask} />;
  else if (screen === 'report') page = <ReportScreen {...navigation} sessionId={reportTarget?.id ?? session?.id ?? null} ended={reportTarget?.ended ?? session?.status === 'ended'} onEvidence={openEvidence} />;
  else if (screen === 'packs') page = <PackScreen {...navigation} />;
  else if (screen === 'documents') page = <DocumentsScreen {...navigation} />;
  else page = <HistoryScreen {...navigation} onOpen={openHistory} busy={busy} error={error} />;
  return <>{page}{error && screen === 'briefing' && <Modal title="상담 연결 확인" onClose={() => setError('')}><TextPages text={error} /></Modal>}
    {evidence && <Modal title="근거 원문" onClose={() => { evidenceRequest.current++; setEvidence(null); }}>{evidence.loading ? <Empty>근거를 불러오고 있습니다.</Empty> : evidence.value ? <EvidenceView value={evidence.value} /> : <Notice>{evidence.error}</Notice>}</Modal>}
    {newConfirm && <Modal title="새 상담 시작" onClose={() => setNewConfirm(false)} actions={<><button onClick={() => setNewConfirm(false)}>현재 상담 유지</button><button className="wb-primary" disabled={session?.status !== 'connected' || session?.ending} onClick={() => { newAfterEnd.current = true; setNewConfirm(false); endSession(); }}>현재 상담 종료 후 새 상담</button></>}><TextPages text="현재 상담을 종료하고 서버에 기록한 뒤 새 상담을 준비합니다. 녹음 중이라면 녹음도 중지됩니다." /></Modal>}
  </>;
}
