// Run: node front/scripts/evidence-transcript-unit-qa.cjs
// Uses installed TypeScript, React and the existing Playwright runtime. No app server or backend.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || path.join(process.env.USERPROFILE || process.env.HOME, '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const front = path.resolve(__dirname, '..');
const source = name => fs.readFileSync(path.join(front, name), 'utf8');
const compile = name => ts.transpileModule(source(`components/${name}.tsx`), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.React } }).outputText;
const evidence = { doc_id: 'portrait', page: 1, span: 'Exact evidence', bbox: [60, 600, 180, 660] };
const rows = count => Array.from({ length: count }, (_, i) => ({ id: `row-${i}`, speaker: i % 2 ? 'teller' : 'customer', t_ms: i * 1000, text: `Message ${i} ` + 'readable text '.repeat(10) }));
let browser;
let passed = 0;
let failed = 0;
async function test(name, run) {
  try { await run(); passed++; console.log(`PASS: ${name}`); }
  catch (error) { failed++; console.error(`FAIL: ${name}\n${error.stack}`); }
}
(async () => {
  browser = await chromium.launch({ headless: true, ...(fs.existsSync(chromium.executablePath()) ? {} : { channel: 'chrome' }) });
  const page = await browser.newPage({ viewport: { width: 1200, height: 850 } });
  page.setDefaultTimeout(5000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  let failImage = false;
  await page.route('https://evidence-qa.test/**', async route => {
    const url = new URL(route.request().url());
    if (!url.pathname.includes('/pages/')) return route.fulfill({ contentType: 'text/html', body: '<div id="root" class="wb"></div>' });
    if (failImage) return route.abort();
    const scale = Number(url.searchParams.get('scale') || 2);
    const wide = url.pathname.includes('/pages/2.png');
    const width = (wide ? 900 : 600) * scale, height = (wide ? 600 : 900) * scale;
    await route.fulfill({ contentType: 'image/svg+xml', body: `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}"><rect width="100%" height="100%" fill="white"/></svg>` });
  });
  await page.goto('https://evidence-qa.test/');
  for (const name of ['react/umd/react.development.js', 'react-dom/umd/react-dom.development.js']) await page.addScriptTag({ content: fs.readFileSync(require.resolve(name.replace('/umd/' + name.split('/umd/')[1], '') + '/package.json').replace('package.json', 'umd/' + name.split('/umd/')[1]), 'utf8') });
  await page.addStyleTag({ content: source('app/workspace.css') + source('app/evidence.css') + '\n#root{width:900px;height:600px;display:flex}.wb-chat{display:flex;flex-direction:column;width:500px;height:360px}.wb-ev-card{max-width:450px}.wb-chat-bubble{font:16px/23px sans-serif}.wb-ev-viewport{min-height:0}' });
  await page.evaluate(({ ev, tr }) => {
    window.pendingEvidence = new Map(); window.fetchCounts = new Map();
    const api = {
      apiUrl: value => value,
      malteumApi: {
        evidence: ref => { window.fetchCounts.set(ref, (window.fetchCounts.get(ref) || 0) + 1); return new Promise((resolve, reject) => window.pendingEvidence.set(ref, { resolve, reject })); },
        documents: async () => ({ documents: [{ doc_id: 'portrait', page_count: 3 }, { doc_id: 'other', page_count: 2 }] }),
      },
    };
    const require = name => name === 'react' ? { ...React, default: React } : name === '../lib/api' ? api : name === '../lib/workspace-model' ? { timeLabel: String } : { Empty: ({ children }) => React.createElement('div', null, children) };
    const load = code => { const exports = {}; new Function('require', 'exports', code)(require, exports); return exports; };
    window.ev = load(ev); window.tr = load(tr); window.root = ReactDOM.createRoot(document.getElementById('root'));
    window.render = (name, props, key = name) => ReactDOM.flushSync(() => root.render(React.createElement(name === 'Transcript' ? window.tr[name] : window.ev[name], { ...props, key, onSelect() {}, onOpen() {} })));
    window.metrics = () => { const host = document.querySelector('.wb-chat-rows'); return { top: host.scrollTop, gap: host.scrollHeight - host.clientHeight - host.scrollTop, following: document.querySelector('.wb-chat').dataset.following }; };
  }, { ev: compile('evidence'), tr: compile('transcript') });
  const render = (name, props, key) => page.evaluate(({ name, props, key }) => window.render(name, props, key), { name, props, key });
  const loaded = () => page.waitForFunction(() => { const img = document.querySelector('.wb-ev-canvas img'); return img && img.complete && img.naturalWidth > 0 && getComputedStyle(img).visibility !== 'hidden'; });
  const atEnd = () => page.waitForFunction(() => window.metrics().gap <= 1);

  await test('fallback bounding box is scale invariant in full viewer and compact card', async () => {
    for (const name of ['EvidenceView', 'EvidenceCard']) {
      await render(name, name === 'EvidenceView' ? { value: evidence } : { evidence }); await loaded();
      await page.waitForFunction(() => { const el=document.querySelector('.wb-ev-highlight'); return el && Math.abs(parseFloat(el.style.left) - 10) < 0.01; });
      const box = await page.locator('.wb-ev-highlight').evaluate(el => ({ x: parseFloat(el.style.left), y: parseFloat(el.style.top), w: parseFloat(el.style.width) }));
      assert.ok(Math.abs(box.x - 10) < 0.01 && Math.abs(box.y - 26.6667) < 0.01 && Math.abs(box.w - 20) < 0.01, JSON.stringify(box));
    }
  });
  await test('neighbor page uses its own landscape ratio and hides the citation', async () => {
    await render('EvidenceView', { value: { ...evidence, page_size: [600, 900] } }, 'neighbor'); await loaded();
    await page.getByRole('button', { name: '다음 페이지', exact: true }).click(); await loaded();
    await page.waitForFunction(() => { const el = document.querySelector('.wb-ev-canvas'); return Math.abs(el.clientHeight / el.clientWidth - 2 / 3) < 0.01; });
    assert.equal(await page.locator('.wb-ev-highlight').count(), 0);
    await page.getByRole('button', { name: /근거 위치로/ }).click(); await loaded();
    await page.waitForFunction(() => { const el = document.querySelector('.wb-ev-canvas'); return Math.abs(el.clientHeight / el.clientWidth - 1.5) < 0.01; });
  });
  await test('reference changes never expose the previous value, including before passive effects', async () => {
    await page.evaluate(() => {
      window.snapshots = [];
      function Probe({ id }) { const state = ev.useEvidence(id); React.useLayoutEffect(() => { snapshots.push({ id, ref: state.ref, value: state.value?.span }); }); return null; }
      window.probe = id => ReactDOM.flushSync(() => root.render(React.createElement(Probe, { id })));
      probe('old');
    });
    await page.evaluate(value => pendingEvidence.get('old').resolve(value), evidence);
    await page.waitForFunction(() => snapshots.some(s => s.value === 'Exact evidence'));
    await page.evaluate(() => { probe('next'); probe('last'); });
    await page.evaluate(value => pendingEvidence.get('next').resolve({ ...value, span: 'Obsolete response' }), evidence);
    await page.evaluate(value => pendingEvidence.get('last').resolve({ ...value, span: 'Current response' }), evidence);
    await page.waitForFunction(() => snapshots.some(s => s.value === 'Current response'));
    assert.deepEqual(await page.evaluate(() => snapshots.filter(s => s.id !== 'old' && s.value && s.value !== 'Current response')), []);
  });
  await test('failed fetch offers retry and recovers the card', async () => {
    await render('EvidenceCard', { evidenceRef: 'retry-ref' }, 'fetch-retry');
    await page.evaluate(() => pendingEvidence.get('retry-ref').reject(new Error('offline')));
    await page.getByRole('button', { name: /다시/ }).click();
    await page.waitForFunction(() => fetchCounts.get('retry-ref') === 2);
    await page.evaluate(value => pendingEvidence.get('retry-ref').resolve(value), evidence);
    await loaded(); assert.equal(await page.getByText('Exact evidence', { exact: true }).count(), 1);
  });
  await test('image failures retry in viewer and card without nested buttons', async () => {
    for (const name of ['EvidenceView', 'EvidenceCard']) {
      failImage = true;
      const imageEvidence = { ...evidence, doc_id: 'image-' + name };
      await render(name, name === 'EvidenceView' ? { value: imageEvidence } : { evidence: imageEvidence }, `image-retry-${name}`);
      const retry = page.getByRole('button', { name: '이미지 다시 불러오기', exact: true }); await retry.waitFor();
      assert.equal(await page.locator('button button').count(), 0);
      failImage = false; await retry.click(); await loaded();
      assert.equal(await retry.count(), 0);
    }
  });
  await test('cache deduplicates active reads, retains hot entries and bounds old entries', async () => {
    const result = await page.evaluate(async value => {
      const settle = async ref => { const pending = ev.loadEvidence(ref); pendingEvidence.get(ref)?.resolve(value); await pending; };
      await settle('cache-old'); await settle('cache-hot');
      const a = ev.loadEvidence('cache-pending'), b = ev.loadEvidence('cache-pending');
      pendingEvidence.get('cache-pending').resolve(value); await a;
      for (let i = 0; i < 300; i++) { await settle(`cache-${i}`); await ev.loadEvidence('cache-hot'); }
      const before = fetchCounts.get('cache-old'); await settle('cache-old');
      return { dedup: a === b, hot: fetchCounts.get('cache-hot'), evicted: fetchCounts.get('cache-old') > before };
    }, evidence);
    assert.deepEqual(result, { dedup: true, hot: 1, evicted: true });
  });
  await test('smooth append does not disable follow on its own scroll events', async () => {
    await render('Transcript', { items: rows(15) }, 'smooth'); await atEnd();
    await page.evaluate(() => { window.followTransitions = []; window.followObserver?.disconnect(); window.followObserver = new MutationObserver(() => followTransitions.push(document.querySelector('.wb-chat').dataset.following)); followObserver.observe(document.querySelector('.wb-chat'), { attributes: true, attributeFilter: ['data-following'] }); });
    const next = rows(16); next[15].text = 'Long new message '.repeat(160);
    await render('Transcript', { items: next }, 'smooth'); await atEnd();
    assert.equal((await page.evaluate(() => metrics())).following, 'true');
    assert.ok(!(await page.evaluate(() => followTransitions)).includes('false'));
  });
  await test('manual reading survives append, same-count text growth and resizing', async () => {
    const initial = rows(25); await render('Transcript', { items: initial }, 'reader'); await atEnd();
    await page.locator('.wb-chat-rows').hover(); await page.mouse.wheel(0, -900);
    await page.waitForFunction(() => metrics().following === 'false');
    await page.waitForFunction(() => metrics().gap > 500);
    // Finish the physical wheel event before selecting the anchor.
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const anchor = await page.evaluate(() => { const host = document.querySelector('.wb-chat-rows'); const el = [...host.children].find(row => row.getBoundingClientRect().bottom > host.getBoundingClientRect().top); return { text: el.textContent, offset: el.getBoundingClientRect().top - host.getBoundingClientRect().top }; });
    const more = rows(26); await render('Transcript', { items: more }, 'reader');
    assert.match(await page.locator('.wb-chat-jump').innerText(), /새 발화 1개/);
    more[0].text += 'earlier text grew '.repeat(100); await render('Transcript', { items: more }, 'reader');
    await page.locator('.wb-chat').evaluate(el => { el.style.width = '380px'; el.style.height = '290px'; });
    await page.waitForFunction(expected => { const host = document.querySelector('.wb-chat-rows'); const el = [...host.children].find(row => row.textContent === expected.text); return el && Math.abs(el.getBoundingClientRect().top - host.getBoundingClientRect().top - expected.offset) < 2; }, anchor);
    assert.equal((await page.evaluate(() => metrics())).following, 'false');
    await page.getByRole('button', { name: /최신으로/ }).click(); await atEnd();
    assert.equal((await page.evaluate(() => metrics())).following, 'true');
  });
  await test('same-count updates, host resize and keyed filters continue following', async () => {
    const initial = rows(10); await render('Transcript', { items: initial }, 'updates'); await atEnd();
    initial[9].text = 'long text '.repeat(200); await render('Transcript', { items: initial }, 'updates'); await atEnd();
    await page.locator('.wb-chat').evaluate(el => { el.style.width = '340px'; el.style.height = '220px'; }); await atEnd();
    await render('Transcript', { items: rows(10).filter(r => r.speaker === 'teller') }, 'filter-teller'); await atEnd();
    await render('Transcript', { items: [] }, 'filter-empty');
    assert.equal(await page.locator('.wb-chat-jump').count(), 0);
    await render('Transcript', { items: rows(1) }, 'filter-empty'); await atEnd();
  });
  await test('no uncaught component errors', async () => assert.deepEqual(errors, []));
  console.log(`RESULT: ${passed} passed, ${failed} failed`);
  if (failed) process.exitCode = 1;
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => { await browser?.close(); });
