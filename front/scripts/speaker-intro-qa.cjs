const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || path.join(process.env.USERPROFILE, '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const { allSizes, inspect, checks, failures } = require('./workspace-qa.cjs');
const fixtures = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../../back/contracts/fixtures/ws_messages.json'), 'utf8'));
const ready = fixtures.find(m => m.t === 'ready');
const ended = fixtures.find(m => m.t === 'ended');
const out = path.resolve(__dirname, '../qa-output');
const errors = [], sent = [], packets = [];
let browser, client, created = 0, activeId, mode = 'live', seq = 1;
(async () => {
  browser = await chromium.launch({ headless: true, args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, permissions: ['microphone'] });
  await context.addInitScript(() => {
    const capture = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    window.__speakerPreviewQa = { calls: 0, denied: false, tracks: [] };
    navigator.mediaDevices.getUserMedia = async options => {
      const state = window.__speakerPreviewQa; state.calls++;
      if (state.denied) throw new DOMException('QA permission denied', 'NotAllowedError');
      const stream = await capture(options); state.tracks.push(...stream.getTracks()); return stream;
    };
  });
  const page = await context.newPage(); page.setDefaultTimeout(20000);
  page.on('pageerror', error => errors.push(error.message));
  await context.route('**/api/**', route => {
    const request = route.request(), url = new URL(request.url());
    if (request.method() === 'GET') return route.continue();
    if (request.method() === 'POST' && url.pathname === '/api/sessions') {
      mode = request.postDataJSON().mode; activeId = `speaker-preview-qa-${++created}`;
      return route.fulfill({ status: 201, json: { session_id: activeId, pack_version: ready.pack_version, ws_url: '/ws' } });
    }
    errors.push(`Unexpected write: ${request.method()} ${url.pathname}`); return route.abort();
  });
  await page.routeWebSocket(/.*/, ws => ws.onMessage(data => {
    if (typeof data !== 'string') { packets.push(Buffer.from(data)); return; }
    const message = JSON.parse(data); if (!message.t) return; sent.push(message);
    if (message.t === 'hello' || message.t === 'resume') { client = ws; seq = 1; ws.send(JSON.stringify({ ...ready, session_id: activeId, mode, seq: seq++ })); }
    if (message.t === 'end') ws.send(JSON.stringify({ ...ended, session_id: activeId, seq: seq++ }));
  }));
  const intro = () => page.getByRole('dialog', { name: '녹음 전 안내', exact: true });
  const mic = () => page.getByRole('button', { name: '● 녹음 시작', exact: true });
  const proceed = () => intro().getByRole('button', { name: '이어서 녹음 시작', exact: true });
  const stop = () => page.getByRole('button', { name: '■ 녹음 중지', exact: true });
  const micCalls = () => page.evaluate(() => window.__speakerPreviewQa.calls);
  await page.goto('http://localhost:3000', { waitUntil: 'networkidle' });
  await page.getByRole('button', { name: /상담 시작|시작하기|대시보드/ }).first().click();
  await page.getByRole('button', { name: '상담 시작 →', exact: true }).click();
  await mic().click(); await intro().waitFor();
  const before = sent.length;
  await allSizes(page, 'speaker-intro');
  for (const [width, height] of [[844, 390], [667, 375]]) { await page.setViewportSize({ width, height }); await inspect(page, `speaker-intro-landscape-${width}`, true); }
  await page.setViewportSize({ width: 1440, height: 900 });
  await intro().screenshot({ path: path.join(out, 'speaker-intro-preview.png') });
  assert.equal(await micCalls(), 0); assert.equal(packets.length, 0); assert.equal(sent.length, before);
  assert.equal(await page.locator('.wb-chat-entry').count(), 0, 'preview text must not become a transcript');
  assert.match(await intro().innerText(), /이 화면에서는 녹음하지 않습니다/);
  assert.doesNotMatch(await intro().innerText(), /등록 완료|인식 완료/);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  assert.equal(await page.locator('.wb-speaker-mic').evaluate(el => getComputedStyle(el, '::before').animationName), 'none');
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  for (let i = 0; i < 5; i++) { await page.keyboard.press('Tab'); assert.ok(await intro().evaluate(el => el.contains(document.activeElement)), JSON.stringify(await intro().evaluate(el => ({ active: document.activeElement?.tagName, height: getComputedStyle(el).height, minHeight: getComputedStyle(el).minHeight, top: getComputedStyle(el).top, bottom: getComputedStyle(el).bottom })))); }
  await page.keyboard.press('Escape'); await intro().waitFor({ state: 'hidden' }); assert.ok(await mic().evaluate(el => el === document.activeElement));
  await mic().click(); await intro().getByRole('button', { name: '취소', exact: true }).click();
  await mic().click(); await page.mouse.click(2, 2); await intro().waitFor({ state: 'hidden' });
  assert.equal(await micCalls(), 0); assert.equal(packets.length, 0);
  await page.evaluate(() => { window.__speakerPreviewQa.denied = true; });
  await mic().click(); await proceed().click();
  await page.getByText('마이크 사용이 차단되었습니다.', { exact: false }).waitFor();
  assert.equal(await micCalls(), 1); assert.equal(packets.length, 0);
  await page.evaluate(() => { window.__speakerPreviewQa.denied = false; });
  await mic().click(); await proceed().click(); await stop().waitFor();
  for (let n = 0; packets.length < 2 && n < 50; n++) await page.waitForTimeout(100);
  assert.ok(packets.length > 0); assert.ok(packets.every(packet => packet.length === 3204));
  await stop().click(); await page.waitForTimeout(350); const count = packets.length;
  await page.waitForTimeout(450); assert.equal(packets.length, count);
  assert.ok(await page.evaluate(() => window.__speakerPreviewQa.tracks.every(track => track.readyState === 'ended')));
  await mic().click(); await stop().waitFor(); assert.equal(await intro().count(), 0, 'restart in the same session skips the intro');
  for (let n = 0; packets.length === count && n < 50; n++) await page.waitForTimeout(100);
  assert.ok(packets.at(-1).readUInt32BE(0) > packets[count - 1].readUInt32BE(0)); await stop().click();
  await page.getByRole('button', { name: '상담 종료', exact: true }).click();
  await page.getByRole('heading', { name: '종료 리포트', exact: true }).waitFor();
  await page.getByRole('button', { name: '＋ 새 상담', exact: true }).click();
  await page.getByRole('button', { name: '상담 시작 →', exact: true }).click();
  await mic().click(); await intro().waitFor();
  client.close(); await intro().waitFor({ state: 'hidden' });
  assert.equal(await micCalls(), 3, 'new session preview and disconnect must not open a device');
  assert.ok(sent.every(message => ['hello', 'resume', 'pong', 'end'].includes(message.t)), 'no enrollment or fabricated speech commands');
  assert.deepEqual(errors, []); assert.deepEqual(failures, []);
  console.log(JSON.stringify({ passed: true, layoutCount: checks.length, microphoneRequests: await micCalls(), packets: packets.length, checks: ['preview is silent and non-persistent', '12 viewport sizes', 'focus/escape/cancel/backdrop', 'reduced motion', 'permission failure/retry', 'real PCM only after continue', 'stop/start cleanup and sequence', 'new session intro', 'disconnect dismisses intro'], errors }, null, 2));
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => {
  fs.mkdirSync(out, { recursive: true }); fs.writeFileSync(path.join(out, 'speaker-intro-layout.json'), JSON.stringify({ checks, failures, errors }, null, 2)); await browser?.close();
});
