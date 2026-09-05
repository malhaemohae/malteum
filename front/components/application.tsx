'use client';

import { useEffect, useRef, useState } from 'react';
import { flushSync } from 'react-dom';
import { ApiEvidence, ApiHealth, ApiPack, ApiPackItem, ApiPreset, ApiSessionSummary, findSessionEvent, malteumApi, ServerMessage, wsUrl } from '../lib/api';
import { Pcm16Capture } from '../lib/audio';
import { ReplayAudio, ReplayAudioState } from '../lib/replay-audio';
import { nextAudioSequence, rememberAudioSequence, rememberSession, rememberReplayPreset } from '../lib/session-index';
import { historyAudioPreset } from '../lib/history-audio';
import { HistoryAction, isPlayableEvent, recoveredSession, sessionEvents, sessionHandshake, traceBlockedReason } from '../lib/session-recovery';
import { rememberTraceSource, resolveTraceSource } from '../lib/trace-source';
import { TraceSourcePicker } from './trace-source-picker';
import { hasStoredUtterance } from '../lib/trace-start';
import { errorText, evidenceForItem, LiveSession, Mode, NavItem, newLiveSession, reduceServer, Screen, sessionScreen } from '../lib/workspace-model';
import MarketingLanding from './marketing-showcase';
import { Briefing, Dashboard, Preparation } from './consultation';
import { DocumentsScreen, HistoryScreen, PackScreen, ReportScreen } from './operations';
import { Empty, EvidenceView, Modal, Notice, TextPages } from './workspace';

export default function Application() {
  const [screen, setScreen] = useState<Screen>('landing'); const [session, setSession] = useState<LiveSession | null>(null); const current = useRef<LiveSession | null>(null);
  const [pack, setPack] = useState<ApiPack | null>(null); const [health, setHealth] = useState<ApiHealth | null>(null); const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  const [reportTarget, setReportTarget] = useState<{ id: string; ended: boolean } | null>(null); const [newConfirm, setNewConfirm] = useState(false); const newAfterEnd = useRef(false);
  const [traceSelection, setTraceSelection] = useState<ApiSessionSummary | null>(null);
  const preparation = useRef<Preparation>({ mode: 'live', customer: 'general' });
  const managementScreen = useRef<'packs' | 'documents'>('packs');
  const [evidence, setEvidence] = useState<{ loading: boolean; value?: ApiEvidence; error?: string } | null>(null); const evidenceRequest = useRef(0);
  const [micActive, setMicActive] = useState(false); const [micPending, setMicPending] = useState(false); const [micError, setMicError] = useState('');
  const socket = useRef<WebSocket | null>(null); const capture = useRef<Pcm16Capture | null>(null); const connectingMic = useRef(false); const connectTimer = useRef<ReturnType<typeof setTimeout>>(); const endTimer = useRef<ReturnType<typeof setTimeout>>();
  const creating = useRef(false); const choice = useRef<{ customer: 'general' | 'professional' }>({ customer: 'general' });
  const audioSequence = useRef(0);
  const replayAudio = useRef<ReplayAudio | null>(null); const [replaySound, setReplaySound] = useState<ReplayAudioState | null>(null);
  function clearReplayAudio() { const old = replayAudio.current; replayAudio.current = null; old?.dispose(); setReplaySound(null); }
  async function prepareReplayAudio(presetId: string, packVersion: string) {
    clearReplayAudio();
    const player = new ReplayAudio(value => { if (replayAudio.current === player) setReplaySound(value); }); replayAudio.current = player;
    await player.prepare(presetId, packVersion);
  }
  useEffect(() => { replayAudio.current?.setVisible(screen === 'playback'); }, [screen]);
  const pendingAcknowledgements = useRef(new Set<string>());
  function update(value: LiveSession | null | ((previous: LiveSession | null) => LiveSession | null)) { const next = typeof value === 'function' ? value(current.current) : value; current.current = next; setSession(next); }
  function stopMic() { capture.current?.stop(); capture.current = null; connectingMic.current = false; setMicActive(false); setMicPending(false); }
  function closeSocket() { replayAudio.current?.stop(); const old = socket.current; socket.current = null; old?.close(); clearTimeout(connectTimer.current); clearTimeout(endTimer.current); }
  useEffect(() => { let active = true; malteumApi.health().then(value => { if (active) setHealth(value); }).catch(() => { if (active) setHealth(null); }); return () => { active = false; socket.current?.close(); capture.current?.stop(); const old = replayAudio.current; replayAudio.current = null; old?.dispose(); clearTimeout(connectTimer.current); clearTimeout(endTimer.current); }; }, []);
  useEffect(() => { if (!micActive) return; const timer = setInterval(() => update(value => value && value.status === 'connected' ? { ...value, seconds: value.seconds + 1 } : value), 1000); return () => clearInterval(timer); }, [micActive]);
  useEffect(() => { if (!session || session.status === 'ended') return; const beforeUnload = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; }; window.addEventListener('beforeunload', beforeUnload); return () => window.removeEventListener('beforeunload', beforeUnload); }, [session?.id, session?.status]);
  function navigate(value: NavItem) {
    if (creating.current) return;
    setError('');
    if (value === '상담') {
      const active = current.current;
      if (active && active.status !== 'ended' && sessionScreen(active.mode) === 'playback') {
        setScreen('playback');
        if (active.status === 'connected' && !active.ending) { newAfterEnd.current = true; endSession(); }
        else if (!active.ending) update(previous => previous ? { ...previous, error: '재생 연결을 확인하고 종료한 뒤 새 상담을 시작해 주세요.' } : previous);
        return;
      }
      setScreen(active && active.status !== 'ended' ? 'dashboard' : 'briefing');
    }
    if (value === '리포트') { if (current.current) setReportTarget({ id: current.current.id, ended: current.current.status === 'ended' }); setScreen('report'); }
    if (value === '이력') setScreen('history');
    if (value === '기준 관리') setScreen(managementScreen.current);
    if (value === '규정 팩') { managementScreen.current = 'packs'; setScreen('packs'); }
    if (value === '문서') { managementScreen.current = 'documents'; setScreen('documents'); }
  }
  function resetForNew() { stopMic(); closeSocket(); clearReplayAudio(); update(null); setMicError(''); setError(''); setNewConfirm(false); setScreen('briefing'); }
  function requestNew() { if (creating.current) return; if (current.current && current.current.status !== 'ended') setNewConfirm(true); else resetForNew(); }
  function command(value: Record<string, unknown>) {
    if (!current.current || current.current.status !== 'connected' || socket.current?.readyState !== WebSocket.OPEN) { update(previous => previous ? { ...previous, error: '서버 연결을 확인한 뒤 다시 시도해 주세요.' } : previous); return false; }
    if (current.current.mode === 'trace' && !['end', 'pong'].includes(String(value.t))) return false;
    const tracked = ['mark_met', 'mark_waived', 'acknowledge'].includes(String(value.t)) || (value.t === 'assist_request' && value.assist_type === 'rephrase');
    if (tracked && current.current.action?.pending) return false;
    if (tracked) {
      const action = { kind: value.t === 'assist_request' ? 'rephrase' : String(value.t), itemCode: typeof value.item_code === 'string' ? value.item_code : undefined, ref: typeof value.alert_ref === 'string' ? value.alert_ref : undefined, pending: true, message: value.t === 'assist_request' ? '쉬운 말 안내를 요청하고 있습니다.' : '변경 사항을 서버에 기록하고 있습니다.' };
      update(previous => previous ? { ...previous, error: undefined, action } : previous);
      const id = current.current?.id;
      setTimeout(() => { if (current.current?.id === id && current.current.action === action && action.pending) update(previous => previous ? { ...previous, action: { ...action, pending: false, message: '서버 응답이 지연되고 있습니다. 다시 요청해 주세요.' } } : previous); }, 15000);
    }
    if (value.t === 'acknowledge') pendingAcknowledgements.current.add(String(value.alert_ref));
    socket.current.send(JSON.stringify(value)); return true;
  }
  function finishSession(id: string) {
    if (current.current?.id !== id) return;
    stopMic(); closeSocket(); clearReplayAudio(); update(value => value ? { ...value, status: 'ended', ending: false, error: undefined } : value);
    setReportTarget({ id, ended: true });
    if (newAfterEnd.current) { newAfterEnd.current = false; resetForNew(); } else setScreen('report');
  }
  function connect(active: LiveSession, recover = false) {
    closeSocket(); update({ ...active, status: 'connecting', error: undefined });
    const connection = new WebSocket(wsUrl(active.wsUrl)); socket.current = connection;
    const handshake = sessionHandshake(active, recover, choice.current.customer);
    let inbox = Promise.resolve();
    const isCurrent = () => socket.current === connection && current.current?.id === active.id;
    connectTimer.current = setTimeout(() => { if (isCurrent() && current.current?.status === 'connecting') { connection.close(); update(value => value ? { ...value, status: 'disconnected', error: '상담 서버 응답이 없습니다. 다시 연결해 주세요.' } : value); } }, 10000);
    connection.onopen = () => { if (isCurrent()) connection.send(JSON.stringify(handshake.hello)); };
    connection.onmessage = event => {
      if (!isCurrent() || typeof event.data !== 'string') return;
      try {
        const received = JSON.parse(event.data) as ServerMessage;
        if (received.t === 'ping') { connection.send(JSON.stringify({ t: 'pong' })); return; }
        inbox = inbox.then(async () => {
        if (!isCurrent()) return;
        if (current.current?.ending && !['ended', 'error', 'ready'].includes(received.t)) return;
        if (current.current?.status === 'disconnected' && !['ended', 'error', 'ready'].includes(received.t)) return;
        let message = received;
        const handshakeResult = handshake.ready(message);
        message = handshakeResult.message;
        if (handshakeResult.resume) connection.send(JSON.stringify(handshakeResult.resume));
        if (message.t === 'error' && current.current?.status === 'connecting') {
          clearTimeout(connectTimer.current); socket.current = null; connection.close();
          update(value => value ? { ...value, status: 'disconnected', error: `상담 서버에 연결하지 못했습니다. ${String(message.message ?? '이력에서 저장 기록을 확인해 주세요.')}` } : value);
          return;
        }
        // Current WS mapping omits alert.acknowledged. Resolve that flag from the
        // persisted event, never by assuming that a successful send was a save.
        if (message.t === 'alert' && (active.mode === 'trace' || pendingAcknowledgements.current.size > 0)) {
          try {
            const event = await findSessionEvent(active.sourceSessionId ?? active.id, String(message.event_id));
            const alert = event?.alert as Record<string, unknown> | undefined;
            if (alert?.acknowledged === true) {
              message = { ...message, acknowledged: true, acknowledged_ref: event?.supersedes };
              pendingAcknowledgements.current.delete(String(event?.supersedes));
            }
          } catch {
            update(value => value ? { ...value, error: '경보 확인 기록을 조회하지 못했습니다. 연결을 확인한 뒤 다시 시도해 주세요.' } : value);
          }
        }
        if (!isCurrent()) return;

        if (message.t === 'ready') clearTimeout(connectTimer.current);
        const show = () => { if (isCurrent()) update(value => value ? reduceServer(value, message) : value); };
        if (['replay', 'trace'].includes(active.mode) && message.t === 'utterance' && replayAudio.current && !current.current?.seen.includes(String(message.event_id))) await replayAudio.current.present(message, () => flushSync(show));
        else show();
        if (message.t === 'ended') {
          finishSession(active.id);
        }
        }).catch(() => { if (isCurrent()) update(value => value ? { ...value, error: '서버 이벤트를 처리하지 못했습니다. 다시 연결해 주세요.' } : value); });
      } catch { update(value => value ? { ...value, error: '서버 메시지를 읽지 못했습니다. 연결을 다시 확인해 주세요.' } : value); }
    };
    const disconnected = () => {
      if (!isCurrent() || current.current?.status === 'ended' || current.current?.status === 'disconnected') return;
      stopMic(); replayAudio.current?.stop(); update(value => value ? { ...value, status: 'disconnected', ending: false, error: '서버 연결이 끊겼습니다. 다시 연결하거나 이력에서 저장 기록을 확인해 주세요.' } : value);
      // A lost ended frame must not strand a session the server already closed.
      malteumApi.session(active.id).then(detail => { if (isCurrent() && detail.status !== 'running') finishSession(active.id); }).catch(() => { /* Keep the reconnect action when status cannot be verified. */ });
    };
    connection.onerror = disconnected; connection.onclose = disconnected;
  }
  async function start(pack: ApiPack, mode: Mode, customer: 'general' | 'professional', preset?: { preset_id: string; audio_ref?: string }) {
    if (current.current && current.current.status !== 'ended') { setError('진행 중인 상담 또는 재생을 먼저 종료해 주세요.'); return; }
    if (creating.current) return; creating.current = true; setBusy(true); setError(''); setMicError(''); choice.current = { customer };
    try {
      clearReplayAudio();
      if (mode === 'replay' && preset) await prepareReplayAudio(preset.preset_id, pack.pack_version);
      const created = await malteumApi.createSession({ mode, pack_version: pack.pack_version, product_code: pack.product?.code, customer_profile: { type: customer, tags: [] }, ...(preset ? { preset_id: preset.preset_id, audio_ref: preset.audio_ref } : {}) });
      rememberSession(created.session_id);
      if (mode === 'live' || mode === 'text') preparation.current = { packVersion: created.pack_version, mode, customer };
      if (mode === 'replay' && preset) rememberReplayPreset(created.session_id, preset.preset_id);
      setPack(created.pack_version === pack.pack_version ? pack : await malteumApi.pack(created.pack_version));
      audioSequence.current = 0;
      pendingAcknowledgements.current.clear();
      const active = newLiveSession(created.session_id, created.ws_url, mode, created.pack_version); update(active); setScreen(sessionScreen(mode)); connect(active);
      malteumApi.health().then(setHealth).catch(() => setHealth(null));
    } catch (reason) { clearReplayAudio(); setError(`상담을 시작하지 못했습니다. ${errorText(reason)}`); } finally { creating.current = false; setBusy(false); }
  }
  async function startPreset(preset: ApiPreset) {
    if (creating.current) return;
    if (current.current && current.current.status !== 'ended') { setError('진행 중인 상담 또는 재생을 먼저 종료해 주세요.'); return; }
    creating.current = true; setBusy(true); setError('');
    try {
      const selectedPack = await malteumApi.pack(preset.pack_version);
      creating.current = false;
      await start(selectedPack, 'replay', preset.customer_profile?.type === 'professional' ? 'professional' : 'general', preset);
    } catch (reason) { setError(errorText(reason)); } finally { creating.current = false; setBusy(false); }
  }
  async function toggleMic() {
    update(value => value ? { ...value, textFallback: false } : value);
    if (micActive) { stopMic(); return; }
    if (connectingMic.current || current.current?.status !== 'connected' || current.current.mode !== 'live' || current.current.ending) return;
    connectingMic.current = true; setMicPending(true); setMicError(''); const activeCapture = new Pcm16Capture(audioSequence.current); capture.current = activeCapture;
    try {
      await activeCapture.start((frame, sequence) => { if (socket.current?.readyState === WebSocket.OPEN) { socket.current.send(frame); audioSequence.current = sequence + 1; if (current.current) rememberAudioSequence(current.current.id, sequence + 1); } });
      if (capture.current !== activeCapture || current.current?.status !== 'connected') { activeCapture.stop(); return; }
      setMicActive(true);
    } catch (reason) { activeCapture.stop(); capture.current = null; const name = reason instanceof Error ? reason.name : ''; setMicError(name === 'NotAllowedError' ? '마이크 사용이 차단되었습니다. 브라우저와 Windows의 마이크 권한을 확인해 주세요.' : name === 'NotFoundError' ? '입력 장치를 찾지 못했습니다. 마이크 연결을 확인해 주세요.' : `마이크를 시작하지 못했습니다. ${errorText(reason)}`); } finally { connectingMic.current = false; setMicPending(false); }
  }
  function endSession() {
    const active = current.current; if (!active || active.ending || active.status === 'ended') return;
    stopMic(); replayAudio.current?.stop(); if (!command({ t: 'end' })) return; update(value => value ? { ...value, ending: true } : value);
    endTimer.current = setTimeout(async () => {
      if (current.current?.id !== active.id || !current.current.ending) return;
      try { if ((await malteumApi.session(active.id)).status !== 'running') { finishSession(active.id); return; } } catch { /* Never assume an unconfirmed end succeeded. */ }
      if (current.current?.id !== active.id || current.current.status === 'ended') return;
      newAfterEnd.current = false; update(value => value ? { ...value, ending: false, error: '종료가 확인되지 않았습니다. 다시 연결하거나 이력에서 상담을 열어 종료해 주세요.' } : value);
    }, 10000);
  }
  async function openEvidence(ref: string) {
    const requestId = ++evidenceRequest.current; setEvidence({ loading: true });
    try {
      const value = await malteumApi.evidence(ref);
      let sourcePack = pack;
      // A report may belong to a different pack from the active consultation.
      // Resolve its immutable version; never attach an unrelated source URL.
      if (screen === 'report' && reportTarget) {
        try { const report = await malteumApi.report(reportTarget.id); sourcePack = pack?.pack_version === report.pack_version ? pack : await malteumApi.pack(report.pack_version); }
        catch { sourcePack = null; } // Original evidence remains usable without an external link.
      }
      const source = sourcePack?.sources?.find(source => source.doc_id === value.doc_id);
      if (evidenceRequest.current === requestId) setEvidence({ loading: false, value: { ...value, source_url: value.source_url ?? source?.url } });
    } catch (reason) { if (evidenceRequest.current === requestId) setEvidence({ loading: false, error: errorText(reason) }); }
  }
  function itemEvidence(item: ApiPackItem) { if (!pack) return; const value = evidenceForItem(pack, item); setEvidence(value ? { loading: false, value } : { loading: false, error: '이 항목에는 서버 근거가 없습니다.' }); }
  function ask(question: string) { if (!command({ t: 'ask', question })) return; update(value => value ? { ...value, query: { question, pending: true } } : value); const id = current.current?.id; setTimeout(() => { const latest = current.current; if (latest && latest.id === id && latest.query?.question === question && latest.query.pending) update(value => value ? { ...value, query: { question, pending: false, answer: '응답이 지연되고 있습니다. 다시 요청할 수 있습니다.' } } : value); }, 15000); }
  async function openHistory(record: ApiSessionSummary, action: HistoryAction) {
    if (creating.current) return;
    setError('');
    if (action === 'report') { setReportTarget({ id: record.session_id, ended: record.status !== 'running' }); setScreen('report'); return; }
    if (action === 'resume' && current.current?.id === record.session_id && current.current.status !== 'ended') {
      setScreen(sessionScreen(current.current.mode)); if (current.current.status === 'disconnected') connect(current.current, true); return;
    }
    if (current.current && current.current.status !== 'ended') { setError('다른 상담이 열려 있습니다. 왼쪽 상담 탭에서 현재 상담을 종료한 뒤 다시 열어 주세요.'); return; }
    if (creating.current) return; creating.current = true; setBusy(true); setError('');
    try {
      const latest = await malteumApi.session(record.session_id);
      if (action === 'resume') {
        if (latest.status !== 'running') { setReportTarget({ id: latest.session_id, ended: true }); setScreen('report'); return; }
        const [selectedPack, events] = await Promise.all([malteumApi.pack(latest.pack_version), sessionEvents(latest.session_id)]);
        clearReplayAudio();
        if (latest.mode === 'replay') {
          const presetId = historyAudioPreset(latest, events);
          if (presetId) await prepareReplayAudio(presetId, latest.pack_version);
          replayAudio.current?.restoreTranscript(events.filter(event => event.kind === 'utterance').map(event => String((event.utterance as { text?: string } | undefined)?.text ?? '')));
        }
        stopMic(); setMicError(''); setPack(selectedPack); pendingAcknowledgements.current.clear();
        audioSequence.current = nextAudioSequence(latest.session_id);
        rememberSession(latest.session_id); setScreen(sessionScreen(latest.mode)); connect(recoveredSession(latest, selectedPack, events), true);
        return;
      }
      const blocked = traceBlockedReason(latest); if (blocked) throw new Error(blocked);
      const source = await resolveTraceSource(latest);
      if (!source) { setTraceSelection(latest); return; }
      const sourceBlocked = traceBlockedReason(source); if (sourceBlocked) throw new Error(sourceBlocked);
      const sourceEvents = await sessionEvents(source.session_id);
      if (!sourceEvents.some(isPlayableEvent)) throw new Error('저장된 발화·판정이 없어 TRACE를 재생할 수 없습니다. 리포트에서 기록을 확인해 주세요.');
      const selectedPack = await malteumApi.pack(source.pack_version);
      clearReplayAudio();
      const presetId = historyAudioPreset(source, sourceEvents);
      if (presetId && hasStoredUtterance(sourceEvents)) await prepareReplayAudio(presetId, source.pack_version);
      const created = await malteumApi.createSession({ mode: 'trace', source_session_id: source.session_id, pack_version: source.pack_version });
      rememberTraceSource(created.session_id, source.session_id); setTraceSelection(null);
      rememberSession(created.session_id); setPack(selectedPack);
      const active = { ...newLiveSession(created.session_id, created.ws_url, 'trace', created.pack_version), sourceSessionId: source.session_id, traceHasUtterances: hasStoredUtterance(sourceEvents) };
      update(active); setScreen('playback'); connect(active);
    } catch (reason) { clearReplayAudio(); setError(errorText(reason)); } finally { creating.current = false; setBusy(false); }
  }
  const navigation = { onNavigate: navigate, onNew: requestNew };
  let page;
  if (screen === 'landing') page = <MarketingLanding onStart={() => setScreen('briefing')} onNavigate={navigate} />;
  else if (screen === 'briefing') page = <Briefing {...navigation} busy={busy} onStart={start} defaults={preparation.current} />;
  else if ((screen === 'dashboard' || screen === 'playback') && session) page = <Dashboard {...navigation} session={session} pack={pack} health={health} micActive={micActive} micPending={micPending} micError={micError} replaySound={replaySound} onReplaySound={() => { void replayAudio.current?.toggle(); }} onMic={toggleMic} onEnd={endSession} onRetry={() => connect(session, true)} onTextMode={() => { stopMic(); setMicError(''); update(value => value ? { ...value, textFallback: true, error: undefined } : value); }} onCommand={command} onDismiss={() => update(value => value ? { ...value, interventions: value.interventions.slice(1) } : value)} onEvidence={openEvidence} onItemEvidence={itemEvidence} onAsk={ask} />;
  else if (screen === 'report') page = <ReportScreen {...navigation} sessionId={reportTarget?.id ?? session?.id ?? null} onEvidence={openEvidence} onResume={record => openHistory(record, 'resume')} onTrace={record => openHistory(record, 'trace')} busy={busy} error={error} />;
  else if (screen === 'packs') page = <PackScreen {...navigation} />;
  else if (screen === 'documents') page = <DocumentsScreen {...navigation} />;
  else page = <HistoryScreen {...navigation} onOpen={openHistory} onStartPreset={startPreset} busy={busy} error={error} />;
  return <>{page}{error && screen === 'briefing' && <Modal title="상담 연결 확인" onClose={() => setError('')}><TextPages text={error} /></Modal>}
    {traceSelection && <TraceSourcePicker trace={traceSelection} busy={busy} error={error} onClose={() => { setTraceSelection(null); setError(''); }} onPlay={record => openHistory(record, 'trace')} />}
    {evidence && <Modal title="근거 원문" onClose={() => { evidenceRequest.current++; setEvidence(null); }}>{evidence.loading ? <Empty>근거를 불러오고 있습니다.</Empty> : evidence.value ? <EvidenceView value={evidence.value} /> : <Notice>{evidence.error}</Notice>}</Modal>}
    {newConfirm && <Modal title="새 상담 시작" onClose={() => setNewConfirm(false)} actions={<><button onClick={() => setNewConfirm(false)}>현재 상담 유지</button><button className="wb-primary" disabled={session?.status !== 'connected' || session?.ending} onClick={() => { newAfterEnd.current = true; setNewConfirm(false); endSession(); }}>현재 상담 종료 후 새 상담</button></>}><TextPages text="현재 상담을 종료하고 서버에 기록한 뒤 새 상담을 준비합니다. 녹음 중이라면 녹음도 중지됩니다." /></Modal>}
  </>;
}
