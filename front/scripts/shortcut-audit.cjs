// Read-only diagnostic: GETs use the local backend; session creation and every
// WebSocket are isolated. Only exact committed WS fixtures are sent to the UI.
// No microphone audio, mutations, or generated requests reach the real server.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || path.join(process.env.USERPROFILE, '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const fixtures = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../../back/contracts/fixtures/ws_messages.json'), 'utf8'));
const ready = fixtures.find(message => message.t === 'ready');
const numericAlert = fixtures.find(message => message.t === 'alert' && message.alert_type === 'number_mismatch');
const out = path.resolve(__dirname, '../qa-output');
fs.mkdirSync(out, { recursive: true });
const result = { scope: 'isolated browser actions with exact WS fixtures; actual GET catalog only', commands: [], blockedMutations: [], pageErrors: [] };
let browser;
(async () => {
  browser = await chromium.launch({ headless: true, args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, permissions: ['microphone'] });
  const page = await context.newPage();
  page.setDefaultTimeout(20000);
  page.on('pageerror', error => result.pageErrors.push(error.message));
  let wsClient; let frames = 0; const frameSizes = new Set();
  await context.route('**/api/**', route => {
    const request = route.request();
    if (request.method() === 'GET') return route.continue();
    if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/sessions') {
      return route.fulfill({ status: 201, json: { session_id: ready.session_id, pack_version: ready.pack_version, ws_url: '/ws' } });
    }
    result.blockedMutations.push({ method: request.method(), url: request.url() });
    return route.abort();
  });
  await page.routeWebSocket(/.*/, ws => {
    let appSocket = false;
    ws.onMessage(data => {
      if (typeof data !== 'string') { if (appSocket) { frames++; frameSizes.add(data.byteLength); } return; }
      const message = JSON.parse(data);
      if (!message.t) return; // Ignore dev-server hot-reload traffic, still isolated.
      result.commands.push(message);
      if (message.t === 'hello') { appSocket = true; wsClient = ws; ws.send(JSON.stringify(ready)); }
      // Deliberately withhold assist replies to examine waiting/duplicate-click UX.
    });
  });
  await page.goto('http://localhost:3000', { waitUntil: 'networkidle' });
  await page.getByRole('button', { name: /상담 시작|시작하기|대시보드/ }).first().click();
  await page.getByRole('button', { name: '상담 시작 →', exact: true }).click();
  const cards = page.locator('.wb-shortcuts');
  await cards.getByRole('button', { name: '● 녹음 시작', exact: true }).waitFor();
  await page.waitForFunction(() => !document.querySelector('.wb-shortcut.is-record')?.disabled);
  assert.equal(frames, 0);
  await cards.getByRole('button', { name: '● 녹음 시작', exact: true }).click();
  await page.getByRole('button', { name: '이어서 녹음 시작', exact: true }).click();
  await cards.getByRole('button', { name: '■ 녹음 중지', exact: true }).waitFor();
  for (let i = 0; frames < 2 && i < 50; i++) await page.waitForTimeout(100);
  assert.ok(frames > 0); assert.deepEqual([...frameSizes], [3204]);
  await cards.getByRole('button', { name: '■ 녹음 중지', exact: true }).click();
  await page.waitForTimeout(300); const stoppedFrames = frames;
  await page.waitForTimeout(400); assert.equal(frames, stoppedFrames);
  result.recording = { frames: stoppedFrames, bytesPerFrame: [...frameSizes], stopped: true, realServerReceivedAudio: false };

  const beforeChecks = result.commands.length;
  await cards.getByRole('button', { name: '필수 안내', exact: true }).click();
  assert.equal(await page.locator('.wb-guide-content').getAttribute('data-guide-pane'), 'checks');
  assert.equal(result.commands.length, beforeChecks);
  assert.equal(await page.locator('.wb-checks').isVisible(), true);
  await page.locator('[data-paged-list="필수 안내"] .wb-row-button').first().click();
  result.checklist = { type: 'local tab switch', rows: await page.locator('[data-paged-list="필수 안내"] .wb-row-button').count(), detailVisible: await page.getByRole('dialog').isVisible(), manualMarkButton: await page.getByRole('button', { name: '고지 완료 기록', exact: true }).isVisible() };
  await page.getByRole('dialog').getByRole('button', { name: '닫기', exact: true }).click();
  await cards.getByRole('button', { name: '필요 서류', exact: true }).click();
  await cards.getByRole('button', { name: '필요 서류', exact: true }).click();
  await cards.getByRole('button', { name: '기준 확인', exact: true }).click();
  await page.waitForTimeout(400);
  result.assistWaiting = {
    guidePane: await page.locator('.wb-guide-content').getAttribute('data-guide-pane'),
    displayedText: await page.locator('.wb-attention').innerText(),
    documentsStillEnabled: await cards.getByRole('button', { name: '필요 서류', exact: true }).isEnabled(),
    briefingStillEnabled: await cards.getByRole('button', { name: '기준 확인', exact: true }).isEnabled(),
    commands: result.commands.filter(message => message.t === 'assist_request'),
  };
  assert.deepEqual(result.assistWaiting.commands.map(message => message.assist_type), ['documents', 'documents', 'briefing']);
  await page.screenshot({ path: path.join(out, 'shortcut-audit-waiting.png') });
  wsClient.send(JSON.stringify(numericAlert));
  await page.getByRole('heading', { name: '숫자 확인', exact: true }).waitFor();
  await cards.getByRole('button', { name: '필요 서류', exact: true }).click();
  await page.waitForTimeout(200);
  result.withExistingAlert = { headingUnchanged: await page.getByRole('heading', { name: '숫자 확인', exact: true }).isVisible(), displayedText: await page.locator('.wb-attention').innerText() };
  await page.screenshot({ path: path.join(out, 'shortcut-audit-alert.png') });
  assert.deepEqual(result.blockedMutations, []); assert.deepEqual(result.pageErrors, []);
  fs.writeFileSync(path.join(out, 'shortcut-audit.json'), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result, null, 2));
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => { await browser?.close(); });
