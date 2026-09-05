// Actual local REST/WS/LLM/DB. Creates and retains labelled QA sessions only.
const assert = require('node:assert/strict');
const fs = require('node:fs'); const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || path.join(process.env.USERPROFILE, '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const base = process.env.QA_BASE_URL || 'http://127.0.0.1:3000';
const api = 'http://127.0.0.1:8000/api';
const out = path.resolve(__dirname, '../qa-output');
const result = { scope: 'real local backend, TEXT consultation, actual assist/manual record/report/TRACE', created: [], messages: [], checks: [], errors: [] };
const get = async route => { const response = await fetch(api + route); assert.equal(response.status, 200); return response.json(); };
let browser;
(async () => {
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  page.setDefaultTimeout(25000);
  page.on('pageerror', error => result.errors.push(error.message));
  page.on('response', async response => { if (response.status() === 201 && response.request().method() === 'POST' && new URL(response.url()).pathname === '/api/sessions') result.created.push((await response.json()).session_id); });
  page.on('websocket', ws => ws.on('framereceived', frame => { if (typeof frame.payload === 'string') { const message = JSON.parse(frame.payload); if (message.t) result.messages.push(message); } }));
  await page.goto(base, { waitUntil: 'networkidle' });
  await page.getByRole('button', { name: /상담 시작|시작하기|대시보드/ }).first().click();
  await page.getByLabel('입력 방식', { exact: true }).selectOption('text');
  await page.getByLabel('고객 유형', { exact: true }).selectOption('professional');
  await page.getByRole('button', { name: '상담 시작 →', exact: true }).click();
  await page.waitForFunction(() => !!document.querySelector('[data-workspace=dashboard]') && [...document.querySelectorAll('.wb-badge')].some(node => node.textContent === 'TEXT'));
  async function say(text) { await page.getByRole('textbox', { name: '상담 발화', exact: true }).fill(text); await page.getByRole('button', { name: '전송', exact: true }).click(); }
  async function item(name) { await page.locator('.wb-shortcuts').getByRole('button', { name: '필수 안내', exact: true }).click(); await page.locator('[data-paged-list="필수 안내"] .wb-row-button').filter({ hasText: name }).click(); }
  await say('만기 전에 찾으면 약속한 이자보다 적게 받습니다.');
  await page.locator('.wb-chat-entry').first().waitFor();
  await page.locator('.wb-shortcuts').getByRole('button', { name: '필수 안내', exact: true }).click();
  await page.locator('[data-check-item="DEP-INT-002"]').getByRole('button', { name: '쉬운 말', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '쉬운 말 안내', exact: true });
  await dialog.getByText('쉬운 말 안내가 도착했습니다.', { exact: true }).waitFor();
  assert.ok((await dialog.locator('[data-reader-copy]').first().innerText()).length > 10);
  const firstCount = result.messages.filter(message => message.t === 'assist' && message.assist_type === 'rephrase').length;
  await dialog.getByRole('button', { name: '다시 요청', exact: true }).click();
  await dialog.getByText('쉬운 말 안내가 도착했습니다.', { exact: true }).waitFor();
  assert.ok(result.messages.filter(message => message.t === 'assist' && message.assist_type === 'rephrase').length > firstCount);
  result.checks.push('actual manual rephrase and repeat request visible');
  await page.screenshot({ path: path.join(out, 'final-live-rephrase.png') });
  await dialog.getByRole('button', { name: '닫기', exact: true }).click();
  await page.locator('[data-check-item="DEP-PRO-001"]').getByRole('button', { name: '고지 기록', exact: true }).click();
  await page.getByText('수동 변경이 서버에 저장됐습니다.', { exact: true }).waitFor();
  await page.locator('[data-check-item="DEP-PRO-001"]').getByRole('button', { name: '기록 취소', exact: true }).click();
  await page.getByText('수동 변경이 서버에 저장됐습니다.', { exact: true }).waitFor();
  await item('예금자보호 대상과 한도');
  await page.getByRole('button', { name: '범위에서 제외', exact: true }).click();
  await page.getByRole('textbox', { name: '제외 사유', exact: true }).fill('프론트 통합 검수용 수동 제외. 실제 상담 아님.');
  await page.getByRole('button', { name: '제외 사유 기록', exact: true }).click();
  await page.getByText('수동 변경이 서버에 저장됐습니다.', { exact: true }).waitFor();
  result.checks.push('manual met, undo and waiver confirmed by server');
  await page.locator('.wb-guide-tabs').getByRole('button', { name: /^현재 안내/ }).click();
  await page.getByRole('textbox', { name: '규정 질문', exact: true }).fill('이 예금은 일부해지가 가능한가요?');
  await page.getByRole('button', { name: '질문', exact: true }).click();
  await page.getByRole('button', { name: '답변 보기', exact: true }).waitFor();
  assert.ok(result.messages.some(message => message.t === 'assist' && message.assist_type === 'answer' && message.evidence_ref));
  result.checks.push('typed regulatory question has actual evidence-backed answer');
  await page.getByLabel('화자', { exact: true }).selectOption('customer');
  await say('딸이 알려준 계좌로 보내 주세요.');
  await page.locator('.wb-attention.is-risk').waitFor();
  await page.getByRole('button', { name: '확인 기록', exact: true }).click();
  await page.getByText('확인 기록이 서버에 저장됐습니다.', { exact: true }).waitFor();
  assert.equal(await page.locator('.wb-attention.is-risk').count(), 0);
  result.checks.push('risk acknowledgement confirms the matching persisted event before success feedback');
  await page.getByRole('button', { name: '상담 종료', exact: true }).click();
  await page.getByRole('heading', { name: '종료 리포트', exact: true }).waitFor();
  const id = result.created[0];
  const events = (await get(`/sessions/${id}/events`)).events;
  const report = await get(`/sessions/${id}/report`);
  assert.equal(events.at(-1).kind, 'session_ended');
  assert.ok(events.some(event => event.kind === 'assist' && event.assist?.assist_type === 'rephrase'));
  assert.ok(events.some(event => event.kind === 'verdict' && event.verdict?.decided_by === 'human'));
  assert.ok(events.some(event => event.kind === 'alert' && event.alert?.acknowledged === true));
  await page.waitForTimeout(2000);
  assert.deepEqual((await get(`/sessions/${id}/report`)).sections, report.sections);
  assert.equal((await get(`/sessions/${id}/events`)).events.length, events.length);
  result.checks.push('DB stores assisted/manual events; ended report remains stable');
  await page.getByRole('button', { name: 'TRACE 재생', exact: true }).click();
  await page.locator('.wb-chat-entry').first().waitFor();
  await page.getByRole('button', { name: '재생 종료', exact: true }).click();
  await page.getByRole('heading', { name: '종료 리포트', exact: true }).waitFor();
  result.checks.push('report starts TRACE directly without returning to history');
  await page.getByRole('button', { name: '＋ 새 상담', exact: true }).click();
  await page.getByRole('heading', { name: '상담 준비', exact: true }).waitFor();
  await page.waitForFunction(() => [...document.querySelectorAll('button')].some(button => button.textContent === '상담 시작 →' && !button.disabled));
  assert.equal(await page.getByLabel('입력 방식', { exact: true }).inputValue(), 'text');
  assert.equal(await page.getByLabel('고객 유형', { exact: true }).inputValue(), 'professional');
  assert.equal(await page.getByLabel('상품·규정 팩', { exact: true }).inputValue(), 'DEP-2026.08-v6');
  result.checks.push('new consultation retains pack/customer/input settings without auto-starting recording');
  assert.deepEqual(result.errors, []);
})().catch(error => { result.errors.push(error.message); process.exitCode = 1; }).finally(async () => {
  await browser?.close();
  // End only this run's QA sessions if a UI assertion failed midway.
  for (const id of result.created) {
    try {
      const session = await get(`/sessions/${id}`); if (session.status !== 'running') continue;
      await new Promise(resolve => {
        const ws = new WebSocket('ws://127.0.0.1:8000/ws'); const timer = setTimeout(() => { ws.close(); resolve(); }, 12000);
        ws.onopen = () => ws.send(JSON.stringify({ t: 'hello', session_id: id, mode: session.mode }));
        ws.onmessage = event => { const message = JSON.parse(event.data); if (message.t === 'ready') ws.send(JSON.stringify({ t: 'end' })); if (message.t === 'ping') ws.send(JSON.stringify({ t: 'pong' })); if (message.t === 'ended') { clearTimeout(timer); ws.close(); resolve(); } };
        ws.onerror = () => { clearTimeout(timer); resolve(); };
      });
    } catch (error) { result.errors.push(`cleanup ${id}: ${error.message}`); }
  }
  fs.writeFileSync(path.join(out, 'final-live-feedback-qa.json'), JSON.stringify(result, null, 2));
  console.log(JSON.stringify({ created: result.created, checks: result.checks, errors: result.errors }, null, 2));
});
