const path = require('node:path');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || path.join(process.env.USERPROFILE, '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const output = path.resolve(__dirname, '../qa-output');
const baseUrl = process.env.QA_BASE_URL || 'http://localhost:3000';
fs.mkdirSync(output, { recursive: true });
const sizes = [[1920,1080],[1440,900],[1366,768],[1280,720],[1024,768],[1280,600],[768,1024],[390,844],[390,667],[320,568]];
const fixtureCatalog = process.env.QA_FIXTURE_CATALOG === '1';
const failures = []; const checks = []; const pageErrors = [];

async function inspect(page, name, screenshot = false) {
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(180);
  const layout = await page.evaluate(() => {
    const active = document.querySelector('dialog[open]:last-of-type') || document.querySelector('.wb');
    if (!active) return { issues: ['workspace missing'] };
    const issues = [];
    const visible = el => { const rect = el.getBoundingClientRect(); const css = getComputedStyle(el); return rect.width > 0 && rect.height > 0 && css.visibility !== 'hidden' && css.display !== 'none' && !el.closest('.wb-probe'); };
    if (document.documentElement.scrollWidth > innerWidth + 1 || document.documentElement.scrollHeight > innerHeight + 1) issues.push(`document ${document.documentElement.scrollWidth}x${document.documentElement.scrollHeight} > ${innerWidth}x${innerHeight}`);
    for (const element of active.querySelectorAll('*')) {
      if (!visible(element)) continue;
      const css = getComputedStyle(element); const rect = element.getBoundingClientRect();
      if (/auto|scroll/.test(css.overflowY) && element.scrollHeight > element.clientHeight + 2) issues.push(`scrollY ${element.className}`);
      if (/auto|scroll/.test(css.overflowX) && element.scrollWidth > element.clientWidth + 2) issues.push(`scrollX ${element.className}`);
      if (element.matches('button,input,select,textarea') && (rect.left < -1 || rect.top < -1 || rect.right > innerWidth + 1 || rect.bottom > innerHeight + 1)) issues.push(`outside control ${element.textContent.slice(0,35)}`);
    }
    for (const element of active.querySelectorAll('.wb-panel-body,.wb-list-rows,.wb-chat-rows,.wb-reader-area,.wb-body,.wb-modal-body')) {
      if (!visible(element)) continue;
      const parent = element.getBoundingClientRect();
      for (const child of element.children) {
        if (!visible(child)) continue;
        const r = child.getBoundingClientRect();
        if (r.bottom > parent.bottom + 2 || r.right > parent.right + 2 || r.left < parent.left - 2) issues.push(`pane overflow ${element.className} > ${child.className} (${Math.round(r.bottom-parent.bottom)}px)`);
      }
    }
    for (const element of active.querySelectorAll('.wb-list,.wb-dashboard,.wb-conversation,.wb-guidance,.wb-chat-rows,.wb-main')) {
      if (!visible(element)) continue;
      const children = [...element.children].filter(visible);
      for (let a=0;a<children.length;a++) for(let b=a+1;b<children.length;b++) {
        const ra=children[a].getBoundingClientRect(), rb=children[b].getBoundingClientRect();
        if (Math.min(ra.right,rb.right)-Math.max(ra.left,rb.left)>2 && Math.min(ra.bottom,rb.bottom)-Math.max(ra.top,rb.top)>2) issues.push(`overlap ${children[a].className} / ${children[b].className}`);
      }
    }
    return { issues: [...new Set(issues)] };
  });
  checks.push({ name, size: page.viewportSize(), ...layout });
  if (layout.issues.length) failures.push({ name, size: page.viewportSize(), ...layout });
  if (screenshot) await page.screenshot({ path: path.join(output, name.replace(/[^a-zA-Z0-9-]/g,'_') + '.png') });
}
async function allSizes(page, name) {
  for (const [width,height] of sizes) { await page.setViewportSize({width,height}); await inspect(page,`${name}-${width}`,width===1440 || width===390); }
  await page.setViewportSize({width:1440,height:900});
}

module.exports={allSizes,inspect,checks,failures,pageErrors};
if(require.main===module) (async () => {
  const browser = await chromium.launch({ headless:true, args:['--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream'] });
  const context = await browser.newContext({viewport:{width:1440,height:900}, permissions:['microphone']});
  const page = await context.newPage(); page.setDefaultTimeout(15000); page.on('pageerror', error => pageErrors.push(error.message));
  // Catalog-only fixtures for layout QA when PostgreSQL is unavailable. Sessions,
  // WebSocket judgement, evidence, events and reports still use the real backend.
  if (fixtureCatalog) {
    const packs = ['DEP-2026.08-v4','LOAN-2026.08-v5'].map(version => JSON.parse(fs.readFileSync(path.resolve(__dirname,`../../back/contracts/fixtures/rulepack_${version}.json`),'utf8')));
    const docs = [...new Map(packs.flatMap(pack=>pack.sources).map(source=>[source.doc_id,source])).values()];
    await page.route('**/api/packs**', route => {
      const pathname=decodeURIComponent(new URL(route.request().url()).pathname);
      if(route.request().method()!=='GET') return route.continue();
      const pack=packs.find(pack=>pathname.split('/')[3]===pack.pack_version);
      const body=pathname.endsWith('/packs') ? {packs:packs.map(pack=>({...pack,item_count:pack.items.length,source_count:pack.sources.length}))} : pathname.endsWith('/briefing') && pack ? {pack_version:pack.pack_version,must_say:pack.items.filter(i=>i.type==='required').map(i=>({item_code:i.code,name:i.name,elements:i.requirement_elements,plain_language:i.plain_language})),must_not_say:pack.items.filter(i=>i.type==='forbidden').map(i=>({item_code:i.code,name:i.name,examples:i.forbidden_examples})),documents_required:pack.items.filter(i=>i.type==='reference').flatMap(i=>i.requirement_elements??[]),generated_at:pack.published_at,cached:false} : pack;
      return body ? route.fulfill({json:body}) : route.continue();
    });
    await page.route('**/api/documents', route=>route.request().method()==='GET' ? route.fulfill({json:{documents:docs.map(doc=>({...doc,status:'ready'}))}}) : route.continue());
    await page.route('**/api/documents/*/extraction', route=>{
      const docId=decodeURIComponent(new URL(route.request().url()).pathname.split('/')[3]);
      const file=path.resolve(__dirname,`../../assets/extraction/${docId}.json`);
      return docs.some(doc=>doc.doc_id===docId) && fs.existsSync(file) ? route.fulfill({json:JSON.parse(fs.readFileSync(file,'utf8'))}) : route.continue();
    });
  }
  const messages=[]; const frames=[];
  page.on('websocket', ws => { ws.on('framereceived', event => { if(typeof event.payload==='string') { try{messages.push(JSON.parse(event.payload));}catch{}} }); ws.on('framesent', event=>{if(Buffer.isBuffer(event.payload)) frames.push(event.payload);}); });
  await page.goto(baseUrl, {waitUntil:'networkidle'});
  const start = page.getByRole('button', { name: /상담 시작|시작하기|대시보드/ }).first();
  console.log('Landing buttons:', await page.getByRole('button').allTextContents());
  await start.click();
  await page.getByRole('button',{name:'상담 시작 →'}).waitFor();
  await page.waitForFunction(()=>document.querySelector('select[aria-label="상품·규정 팩"]')?.value);
  await allSizes(page,'briefing');
  await page.getByRole('button',{name:'상담 시작 →'}).click();
  await page.getByRole('button',{name:'● 녹음 시작'}).waitFor({state:'visible'});
  await page.waitForFunction(()=>document.querySelector('[data-workspace="dashboard"]') && [...document.querySelectorAll('.wb-badge')].some(e=>e.textContent==='LIVE'));
  await allSizes(page,'dashboard-idle');
  const readyCount = messages.filter(message=>message.t==='ready').length;
  const consultNav=page.getByRole('navigation',{name:'주 메뉴'}).getByRole('button',{name:'상담',exact:true});
  await consultNav.click(); await consultNav.click();
  assert.equal(messages.filter(message=>message.t==='ready').length,readyCount,'reselecting consultation must not create another session');
  await page.getByRole('button',{name:'● 녹음 시작'}).click();
  await page.getByRole('button',{name:'■ 녹음 중지'}).waitFor();
  const recordingDeadline = Date.now() + 6000;
  while (!frames.length && Date.now() < recordingDeadline) await page.waitForTimeout(100);
  await page.getByRole('button',{name:'■ 녹음 중지'}).click();
  assert.ok(frames.length > 0, 'microphone must send PCM, not just show active');
  assert.ok(frames.every(frame=>frame.byteLength===3204), 'PCM frame must match contract');
  const previous=frames.at(-1).readUInt32BE(0);
  await page.getByRole('button',{name:'● 녹음 시작'}).click();
  const restartDeadline = Date.now() + 6000;
  while (frames.at(-1).readUInt32BE(0) <= previous && Date.now() < restartDeadline) await page.waitForTimeout(100);
  await page.getByRole('button',{name:'■ 녹음 중지'}).click();
  assert.ok(frames.at(-1).readUInt32BE(0)>previous,'audio sequence must survive stop/start');
  const fallback = page.getByRole('button',{name:'텍스트 입력',exact:true});
  const useLiveFallback = await fallback.isVisible();
  if (useLiveFallback) await fallback.click();
  else {
    // A configured STT must not be made to fail just to expose the fallback UI.
    // Microphone packets above use LIVE; deterministic judgement below uses TEXT.
    await page.getByRole('button',{name:'상담 종료',exact:true}).click();
    await page.getByRole('heading',{name:'종료 리포트',exact:true}).waitFor();
    await page.getByRole('button',{name:'＋ 새 상담',exact:true}).click();
    await page.getByLabel('입력 방식',{exact:true}).selectOption('text');
    await page.getByRole('button',{name:'상담 시작 →'}).click();
    await page.getByRole('textbox',{name:'상담 발화'}).waitFor();
  }
  await page.getByRole('textbox',{name:'상담 발화'}).fill('만기 뒤에 붙는 이자에는 과세가 되며 세율은 14%입니다.');
  await page.getByRole('button',{name:'전송',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('[data-paged-list="상담 전사"]')?.textContent.includes('과세'));
  await page.waitForTimeout(700);
  await allSizes(page,'dashboard-active');
  assert.ok(messages.some(message=>message.t==='verdict'),'text input must receive real server judgement');
  assert.ok(messages.some(message=>message.t==='alert'&&message.alert_type==='number_mismatch'),'numeric mismatch must come from server');
  if (useLiveFallback) assert.equal(await page.getByRole('button',{name:'● 녹음 시작'}).isVisible(),true,'text fallback must preserve the LIVE recording control');
  await page.getByRole('button',{name:'확인 기록',exact:true}).click();
  await page.waitForFunction(()=>!document.querySelector('.wb-attention')?.textContent.includes('숫자 확인'));
  await page.locator('.wb-shortcuts').getByRole('button',{name:'필수 안내',exact:true}).click();
  const item = page.locator('[data-paged-list="필수 안내"] .wb-row-button').first(); await item.click();
  await allSizes(page,'item-detail');
  await page.getByRole('button',{name:'근거 원문',exact:true}).click();
  await page.getByRole('dialog',{name:'근거 원문',exact:true}).waitFor();
  await allSizes(page,'evidence');
  await page.setViewportSize({width:390,height:844});
  await page.getByRole('button',{name:'PDF 페이지',exact:true}).click();
  await page.locator('.wb-page-canvas img').waitFor();
  await page.waitForFunction(()=>document.querySelector('.wb-page-canvas img')?.naturalWidth>0);
  await allSizes(page,'evidence-page');
  await page.getByRole('dialog',{name:'근거 원문',exact:true}).getByRole('button',{name:'닫기',exact:true}).click();
  assert.equal(await page.locator('dialog[open]').count(),0);
  await page.locator('[data-check-item]').first().getByRole('button',{name:'고지 기록',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('[data-paged-list="필수 안내"] .wb-row-button .wb-badge')?.getAttribute('data-state')==='met');
  assert.ok(messages.some(message=>message.t==='verdict'&&message.decided_by==='human'),'manual mark must wait for a human server verdict');
  await page.locator('[data-paged-list="필수 안내"] .wb-row-button').first().click();
  await page.getByRole('button',{name:'수동 고지 기록 취소',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('[data-paged-list="필수 안내"] .wb-row-button .wb-badge')?.getAttribute('data-state')==='unmet');
  await page.locator('[data-paged-list="필수 안내"] .wb-row-button').first().click();
  await page.getByRole('button',{name:'범위에서 제외',exact:true}).click();
  await page.getByRole('textbox',{name:'제외 사유'}).fill('프론트 연동 검증용 제외 사유');
  await allSizes(page,'waive-form');
  await page.getByRole('button',{name:'제외 사유 기록',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('[data-paged-list="필수 안내"] .wb-row-button')?.textContent.includes('제외'));
  await page.locator('.wb-guide-tabs').getByRole('button',{name:/현재 안내/}).click();
  await page.getByRole('textbox',{name:'규정 질문'}).fill('중도해지 이자율은 어떻게 되나요?');
  await page.getByRole('button',{name:'질문',exact:true}).click();
  await page.getByRole('button',{name:'답변 보기',exact:true}).waitFor();
  await page.getByRole('button',{name:'답변 보기',exact:true}).click();
  await allSizes(page,'answer');
  await page.getByRole('dialog').last().getByRole('button',{name:'닫기',exact:true}).click();
  await page.getByRole('button',{name:'상담 종료',exact:true}).click();
  await page.getByRole('heading',{name:'종료 리포트',exact:true}).waitFor();
  await page.getByRole('button',{name:'PDF 저장',exact:true}).waitFor();
  const ended = messages.findLast(message=>message.t==='ended');
  assert.ok(ended,'server must acknowledge the end');
  const popupPromise=page.waitForEvent('popup');
  await page.getByRole('button',{name:'PDF 저장',exact:true}).click();
  const printPage=await popupPromise;
  await printPage.getByRole('heading',{name:'말틈 상담 리포트',exact:true}).waitFor();
  assert.ok((await printPage.locator('body').innerText()).includes(ended.session_id),'export uses the ended server session');
  await printPage.close();
  await allSizes(page,'report');
  for(const label of ['금지·숫자','이해 지원','위험 신호','타임라인']) {await page.getByRole('button',{name:label,exact:true}).click();await inspect(page,`report-${label}`);}
  await page.getByRole('navigation',{name:'주 메뉴'}).getByRole('button',{name:'이력',exact:true}).click();
  await page.getByRole('button',{name:'TRACE 재생',exact:true}).first().waitFor(); await allSizes(page,'history');
  await page.getByRole('navigation',{name:'주 메뉴'}).getByRole('button',{name:'기준 관리',exact:true}).click();
  const tokenPath = path.resolve(__dirname,'../.admin-token');
  const token = process.env.QA_ADMIN_TOKEN || (fs.existsSync(tokenPath) ? fs.readFileSync(tokenPath,'utf8').trim() : '');
  if (token) {
    await page.getByRole('button',{name:'관리자 인증',exact:true}).click();
    await allSizes(page,'admin-auth'); // Screenshots are taken BEFORE a secret is entered.
    await page.getByLabel('관리자 토큰',{exact:true}).fill(token);
    await page.getByRole('button',{name:'인증 확인',exact:true}).click();
    await page.getByRole('dialog',{name:'관리자 인증',exact:true}).waitFor({state:'hidden'});
    await page.getByRole('button',{name:'인증 해제',exact:true}).waitFor();
  }
  await page.getByRole('button',{name:/ICBC 원화정기예금/}).waitFor(); await allSizes(page,'packs');
  await page.getByRole('button',{name:/ICBC 원화정기예금/}).click(); await allSizes(page,'pack-items');
  await page.locator('[data-paged-list="팩 항목"] .wb-row-button').first().click(); await allSizes(page,'pack-detail');
  await page.getByRole('dialog').last().getByRole('button',{name:'닫기',exact:true}).click();
  await page.getByRole('button',{name:'문서 검수',exact:true}).click();
  await page.locator('[data-paged-list="문서 목록"] .wb-row-button').first().waitFor(); await allSizes(page,'documents');
  const depositDocument=page.locator('[data-paged-list="문서 목록"] .wb-row-button').filter({hasText:'원화정기예금 상품설명서'});
  while (!await depositDocument.count()) await page.locator('[data-paged-list="문서 목록"]').getByRole('button',{name:'문서 목록 다음 페이지',exact:true}).click();
  await depositDocument.click(); await allSizes(page,'candidates');
  const candidateRows=page.locator('[data-paged-list="검수 후보"] .wb-row-button');
  await candidateRows.first().waitFor();
  await candidateRows.first().click();await allSizes(page,'candidate-detail');await page.getByRole('dialog').last().getByRole('button',{name:'닫기',exact:true}).click();
  await page.getByRole('button',{name:'추출 원문',exact:true}).click();
  if (token) await page.locator('[data-paged-list="추출 블록"] .wb-row-button').first().waitFor();
  await allSizes(page,'extraction');
  if (token) {
    await page.locator('[data-paged-list="추출 블록"] .wb-row-button').first().click();
    await allSizes(page,'extraction-detail');
    await page.getByRole('dialog').last().getByRole('button',{name:'닫기',exact:true}).click();
  }
  await page.getByRole('button',{name:'PDF 업로드',exact:true}).click(); await allSizes(page,'upload'); await page.getByRole('dialog').last().getByRole('button',{name:'닫기',exact:true}).click();
  await page.getByRole('button',{name:'규정 팩',exact:true}).click();
  await page.getByRole('button',{name:'규정 팩 발행',exact:true}).click();
  await allSizes(page,'publish'); await page.getByRole('dialog').last().getByRole('button',{name:'닫기',exact:true}).click();
  await page.getByRole('navigation',{name:'주 메뉴'}).getByRole('button',{name:'이력',exact:true}).click();
  const beforeTraceReady=messages.filter(message=>message.t==='ready').length;
  await page.locator('button:not(:disabled)').filter({hasText:/^TRACE 재생$/}).first().click();
  const traceDeadline = Date.now() + 45000;
  while(messages.filter(message=>message.t==='ready').length===beforeTraceReady && Date.now()<traceDeadline) await page.waitForTimeout(100);
  assert.ok(messages.filter(message=>message.t==='ready').length>beforeTraceReady,'wait for the newly created TRACE session, not a previous consultation');
  const traceReadyIndex = messages.findLastIndex(message=>message.t==='ready');
  while (!messages.slice(traceReadyIndex+1).some(message=>message.t==='utterance') && Date.now()<traceDeadline) await page.waitForTimeout(300);
  assert.ok(messages.slice(traceReadyIndex+1).some(message=>message.t==='utterance'),'TRACE must replay saved utterances');
  await inspect(page,'trace',true);
  if (await page.getByRole('button',{name:/^(상담|재생) 종료$/}).isVisible()) { await page.getByRole('button',{name:/^(상담|재생) 종료$/}).click(); await page.getByRole('heading',{name:'종료 리포트',exact:true}).waitFor(); }
  // Failure and empty states are independently sized; no product-side fake data.
  await page.route('**/api/packs',route=>route.fulfill({json:{packs:[]}}));
  await page.getByRole('button',{name:'＋ 새 상담',exact:true}).click();
  await page.getByText('서버에 발행된 규정 팩이 없습니다.',{exact:false}).waitFor();
  await allSizes(page,'no-packs');
  assert.equal(await page.getByRole('button',{name:'상담 시작 →'}).isEnabled(),false);
  await page.route('**/api/packs',route=>route.fulfill({status:503,json:{message:'검증용 서버 연결 오류'}}));
  await page.getByRole('navigation',{name:'주 메뉴'}).getByRole('button',{name:'기준 관리',exact:true}).click();
  await page.getByText('검증용 서버 연결 오류',{exact:false}).waitFor();
  await allSizes(page,'backend-error');
  const result={fixtureCatalog,checks, failures, pageErrors, frames:{count:frames.length,first:frames[0]?.readUInt32BE(0),last:frames.at(-1)?.readUInt32BE(0)}, messages:messages.map(m=>({t:m.t,session_id:m.session_id,item_code:m.item_code,state:m.state,seq:m.seq})), health:await(await fetch(baseUrl+'/api/health')).json()};
  fs.writeFileSync(path.join(output,'workspace-qa.json'),JSON.stringify(result,null,2));
  console.log(JSON.stringify({checks:checks.length,failures,pageErrors,frames:result.frames},null,2));
  await browser.close(); if(failures.length || pageErrors.length)process.exitCode=1;
})().catch(error=>{fs.writeFileSync(path.join(output,'workspace-qa-failure.json'),JSON.stringify({error:error.stack,checks,failures,pageErrors},null,2));console.error(error);process.exit(1);});
