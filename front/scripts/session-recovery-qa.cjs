const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || path.join(process.env.USERPROFILE, '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const base = process.env.QA_BASE_URL || 'http://localhost:3000';
const api = process.env.QA_API_URL || 'http://127.0.0.1:8000/api';
assert.ok([base, api].every(url => ['localhost', '127.0.0.1'].includes(new URL(url).hostname)), 'Only synthetic LOCAL sessions may be changed');
const { allSizes, failures } = require('./workspace-qa.cjs');
const output = path.resolve(__dirname, '../qa-output');
const created = []; const checks = []; let browser;
async function request(url, body) {
  const response = await fetch(api + url, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : undefined);
  assert.equal(response.status, body ? 201 : 200, url); return response.json();
}
function open(id, mode) {
  const messages = []; const ws = new WebSocket(api.replace(/^http/, 'ws').replace(/\/api$/, '/ws'));
  ws.onopen = () => ws.send(JSON.stringify({ t: 'hello', session_id: id, mode }));
  ws.onmessage = event => { const message = JSON.parse(event.data); messages.push(message); if (message.t === 'ping') ws.send(JSON.stringify({ t: 'pong' })); };
  return { ws, messages, wait: async predicate => { const until = Date.now() + 25000; while (!messages.some(predicate) && Date.now() < until) await new Promise(resolve => setTimeout(resolve, 80)); assert.ok(messages.some(predicate), `WS condition not met: ${JSON.stringify(messages.map(m => ({t:m.t,code:m.code})))}`); } };
}
async function seed(empty = false, mode = 'text') {
  const session = await request('/sessions', { mode, pack_version: 'DEP-2026.08-v4', ...(mode === 'replay' ? { preset_id: 'preset-dep-a', audio_ref: 'scenarios/preset-dep-a/audio.wav' } : {}) });
  created.push({ id: session.session_id, mode });
  const connection = open(session.session_id, mode);
  try {
    await connection.wait(m => m.t === 'ready');
    if (!empty && mode === 'text') {
      const pack = await request('/packs/DEP-2026.08-v4');
      connection.ws.send(JSON.stringify({ t: 'text_utterance', speaker: 'customer', text: '중도해지이율이 뭐예요?' }));
      await connection.wait(m => m.t === 'utterance');
      connection.ws.send(JSON.stringify({ t: 'mark_met', item_code: pack.items.find(i => i.type === 'required').code }));
      await connection.wait(m => m.t === 'verdict' && m.decided_by === 'human');
    }
    if (empty) {
      connection.ws.send(JSON.stringify({ t: 'end' }));
      const deadline = Date.now() + 20000;
      while ((await request(`/sessions/${session.session_id}`)).status === 'running' && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 200));
      assert.equal((await request(`/sessions/${session.session_id}`)).status, 'ended', 'The server, not the fixture, must confirm termination');
    }
    if (mode === 'replay') await connection.wait(m => m.t === 'utterance');
  } finally { connection.ws.close(); }
  await new Promise(resolve => setTimeout(resolve, 300));
  return session.session_id;
}
async function history(page, mode, id) {
  await page.getByRole('navigation', { name: '주 메뉴' }).getByRole('button', { name: '이력', exact: true }).click();
  const listLoaded = page.waitForResponse(response => response.request().method() === 'GET' && new URL(response.url()).pathname === '/api/sessions' && new URL(response.url()).searchParams.get('mode') === mode);
  if (await page.getByLabel('이력 입력 방식').inputValue() === mode) await page.getByRole('button', { name: '새로고침', exact: true }).click();
  else await page.getByLabel('이력 입력 방식').selectOption(mode);
  await listLoaded; await page.waitForTimeout(150);
  const row = page.locator(`[data-session-id="${id}"]`).locator('..');
  for (let i = 0; i < 30; i++) {
    if (await row.isVisible()) return row;
    const next = page.getByLabel('세션 이력 다음 페이지');
    if (await next.isEnabled()) await next.click(); else await page.waitForTimeout(100);
  }
  throw new Error(`Missing test session ${id}`);
}
(async () => {
  fs.mkdirSync(output, { recursive: true });
  const id = await seed(); console.log('Seeded local session:', id);
  const before = await request(`/sessions/${id}/events`);
  const summaryBefore = await request(`/sessions/${id}`);
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  page.on('dialog', dialog => dialog.accept());
  const errors = []; const sent = []; const received = []; const creations = [];
  page.on('request', request => { if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/sessions') creations.push(request.postDataJSON()); });
  page.on('pageerror', error => errors.push(error.message));
  page.on('websocket', ws => {
    ws.on('framesent', event => { if (typeof event.payload === 'string') sent.push(JSON.parse(event.payload)); });
    ws.on('framereceived', event => { if (typeof event.payload === 'string') received.push(JSON.parse(event.payload)); });
  });
  await page.goto(base, { waitUntil: 'networkidle' });
  await page.getByRole('button', { name: /상담 시작|시작하기|대시보드/ }).first().click();
  let row = await history(page, 'text', id);
  await row.getByRole('button', { name: '중간 리포트', exact: true }).click();
  await page.getByRole('heading', { name: '중간 리포트', exact: true }).waitFor();
  assert.equal(await page.getByRole('button', { name: 'PDF 저장' }).count(), 0, 'Intermediate data must not be exported as final');
  await allSizes(page, 'recovery-interim-report');
  if (process.env.QA_REPORT_ONLY === '1') {
    await history(page, 'text', id);
    await allSizes(page, 'recovery-history');
    const empty = await seed(true);
    row = await history(page, 'text', empty);
    await row.getByRole('button', { name: 'TRACE 재생', exact: true }).click();
    await page.getByText('저장된 발화·판정이 없어 TRACE를 재생할 수 없습니다. 리포트에서 기록을 확인해 주세요.', { exact: true }).waitFor();
    await allSizes(page, 'recovery-empty-trace');
    assert.deepEqual(failures, []); assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(output, 'session-report-qa.json'), JSON.stringify({ created, checks: ['real intermediate report', 'history actions', 'empty TRACE rejected', '30 layout viewports'], failures, errors }, null, 2));
    console.log('PASS: report/history/empty TRACE layout only; backend recovery is NOT covered');
    return;
  }
  await page.getByRole('button', { name: '상담 열기', exact: true }).click();
  await page.getByRole('button', { name: '상담 종료', exact: true }).waitFor();
  await page.waitForFunction(() => !document.querySelector('.wb-heading button:last-child')?.disabled);
  await page.locator('.wb-chat-rows').getByText('중도해지이율이 뭐예요?', { exact: true }).waitFor();
  assert.ok(sent.some(m => m.t === 'resume' && m.session_id === id));
  assert.ok(!received.some(m => m.code === 'invalid_message'));
  assert.equal(sent.find(m => m.session_id === id).t, 'hello');
  checks.push('intermediate report, same-session hello then one resume, original transcript');
  await allSizes(page, 'recovery-dashboard');
  await page.reload({ waitUntil: 'networkidle' });
  await page.getByRole('button', { name: /상담 시작|시작하기|대시보드/ }).first().click();
  row = await history(page, 'text', id);
  await allSizes(page, 'recovery-history');
  // allSizes may change page capacity; locate the original row again.
  row = await history(page, 'text', id);
  await row.getByRole('button', { name: '상담 열기', exact: true }).click();
  await page.locator('.wb-chat-rows').getByText('중도해지이율이 뭐예요?', { exact: true }).waitFor();
  await page.getByRole('button', { name: '상담 종료', exact: true }).click();
  await page.getByRole('heading', { name: '종료 리포트', exact: true }).waitFor();
  await page.getByRole('button', { name: 'PDF 저장', exact: true }).waitFor();
  const summaryAfter = await request(`/sessions/${id}`);
  assert.equal(summaryAfter.status, 'ended');
  assert.equal(summaryAfter.started_at, summaryBefore.started_at, 'original start time is preserved');
  assert.equal(creations.length, 0, 'recovery must never POST another session');
  assert.equal((await request('/sessions?limit=100')).sessions.filter(s => s.session_id === id).length, 1);
  const after = await request(`/sessions/${id}/events`);
  // The existing server appends session_started on hello even for the same ID.
  // Keep that audit behaviour visible; do not delete/filter stored events to pass QA.
  const recoveryConnections = sent.filter(m => m.t === 'hello' && m.session_id === id).length;
  assert.equal(after.events.filter(e => e.kind === 'session_started').length, before.events.filter(e => e.kind === 'session_started').length + recoveryConnections);
  for (const event of before.events) assert.deepEqual(after.events.find(e => e.event_id === event.event_id), event, 'existing audit records remain unchanged');
  assert.equal(after.events.filter(e => e.kind === 'session_ended').length, 1);
  assert.equal(after.events.filter(e => e.kind === 'utterance').length, before.events.filter(e => e.kind === 'utterance').length);
  const originalMet = summaryBefore.items.find(item => item.state === 'met');
  assert.equal(summaryAfter.items.find(item => item.item_code === originalMet.item_code).state, 'met');
  checks.push('reload recovery, same single session/original timestamp, immutable old events, no duplicate utterance, one persisted end, preserved judgement');
  console.log('PASS:', checks);
  const empty = await seed(true);
  row = await history(page, 'text', empty);
  const postsBefore = sent.length;
  await row.getByRole('button', { name: 'TRACE 재생', exact: true }).click();
  await page.getByText('저장된 발화·판정이 없어 TRACE를 재생할 수 없습니다. 리포트에서 기록을 확인해 주세요.', { exact: true }).waitFor();
  assert.equal(sent.length, postsBefore, 'Empty TRACE must not open a WS');
  await allSizes(page, 'recovery-empty-trace');
  checks.push('empty TRACE explained before creating replay');
  const live = await seed(false, 'live');
  row = await history(page, 'live', live);
  await row.getByRole('button', {name:'상담 열기',exact:true}).click();
  await page.getByRole('button', {name:'● 녹음 시작',exact:true}).waitFor();
  row = await history(page, 'text', id);
  const beforeBlockedTrace = creations.length;
  await row.getByRole('button', {name:'TRACE 재생',exact:true}).click();
  await page.getByText('다른 상담이 열려 있습니다. 왼쪽 상담 탭에서 현재 상담을 종료한 뒤 다시 열어 주세요.',{exact:true}).waitFor();
  assert.equal(creations.length,beforeBlockedTrace,'do not abandon an active consultation to launch TRACE');
  await page.getByRole('navigation',{name:'주 메뉴'}).getByRole('button',{name:'상담',exact:true}).click();
  await page.getByRole('button', {name:'상담 종료',exact:true}).click();
  await page.getByRole('button', {name:'PDF 저장',exact:true}).waitFor();
  assert.equal((await request(`/sessions/${live}`)).status,'ended');
  checks.push('LIVE with no utterances can reopen and end; microphone does not auto-start');
  row = await history(page, 'text', id);
  const traceReadyIndex = received.length;
  await row.getByRole('button', {name:'TRACE 재생',exact:true}).click();
  await page.locator('.wb-chat-rows').getByText('중도해지이율이 뭐예요?',{exact:true}).waitFor();
  const traceId = received.slice(traceReadyIndex).find(m=>m.t==='ready'&&m.mode==='trace')?.session_id;
  assert.ok(traceId); created.push({id:traceId,mode:'trace'});
  assert.equal(creations.at(-1).source_session_id,id);
  await page.getByRole('button', {name:'상담 종료',exact:true}).click();
  await page.getByRole('button', {name:'PDF 저장',exact:true}).waitFor();
  assert.equal((await request(`/sessions/${traceId}`)).status,'ended');
  checks.push('closed original enables real backend TRACE with original utterance, then saves end');
  const replay = await seed(false,'replay');
  const replayBefore = await request(`/sessions/${replay}/events`);
  const replaySummary = await request(`/sessions/${replay}`);
  row = await history(page,'replay',replay);
  await row.getByRole('button',{name:'상담 열기',exact:true}).click();
  await page.getByRole('button',{name:'상담 종료',exact:true}).click();
  await page.getByRole('button',{name:'PDF 저장',exact:true}).waitFor();
  const replayAfter = await request(`/sessions/${replay}/events`);
  const replayClosed = await request(`/sessions/${replay}`);
  assert.equal(replayClosed.status,'ended');
  assert.equal(replayClosed.started_at,replaySummary.started_at);
  for (const event of replayBefore.events) assert.deepEqual(replayAfter.events.find(e=>e.event_id===event.event_id),event);
  assert.equal(replayAfter.events.filter(e=>e.kind==='session_ended').length,1);
  checks.push('REPLAY history reopens and closes the same record without changing earlier audit events');
  assert.deepEqual(errors, []);
  assert.deepEqual(failures, []);
  console.log('PASS session recovery and all layout sizes');
  fs.writeFileSync(path.join(output, 'session-recovery-qa.json'), JSON.stringify({ created, checks, failures, errors }, null, 2));
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => {
  await browser?.close();
  for (const session of created) {
    if ((await request(`/sessions/${session.id}`)).status !== 'running') continue;
    const connection = open(session.id, session.mode);
    try { await connection.wait(m => m.t === 'ready'); connection.ws.send(JSON.stringify({t:'end'})); const deadline = Date.now() + 20000; while ((await request(`/sessions/${session.id}`)).status === 'running' && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 200)); }
    finally { connection.ws.close(); }
  }
});
