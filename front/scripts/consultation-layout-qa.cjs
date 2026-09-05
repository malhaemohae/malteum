const path = require('node:path');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || path.join(process.env.USERPROFILE, '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const {allSizes,inspect,checks,failures,pageErrors} = require('./workspace-qa.cjs');
const output = path.resolve(__dirname,'../qa-output');
const scenario = JSON.parse(fs.readFileSync(path.resolve(__dirname,'../../assets/scenarios/preset-loan-b/script.json'),'utf8'));
const base = process.env.QA_BASE_URL || 'http://localhost:3000';

(async()=>{
  const browser = await chromium.launch({headless:true});
  const context = await browser.newContext({viewport:{width:1440,height:900}});
  const page = await context.newPage(); page.setDefaultTimeout(20000);
  const messages=[]; page.on('pageerror',error=>pageErrors.push(error.message));
  page.on('websocket',ws=>ws.on('framereceived',event=>{if(typeof event.payload==='string'){try{messages.push(JSON.parse(event.payload));}catch{}}}));
  let sessionId;
  try {
    await page.goto(base,{waitUntil:'domcontentloaded'});
    await page.getByRole('button',{name:/상담 시작|시작하기|대시보드/}).first().click();
    await page.getByLabel('상품·규정 팩',{exact:true}).selectOption(scenario.pack_version);
    await page.getByLabel('입력 방식',{exact:true}).selectOption('text');
    await allSizes(page,'split-briefing');
    await page.getByRole('button',{name:'상담 시작 →'}).click();
    await page.waitForFunction(()=>document.querySelector('.wb-heading .wb-badge')?.textContent==='TEXT');
    sessionId=messages.find(m=>m.t==='ready')?.session_id;
    for(const row of scenario.lines.slice(0,10)) {
      await page.getByLabel('화자',{exact:true}).selectOption(row.speaker);
      await page.getByLabel('상담 발화',{exact:true}).fill(row.text);
      await page.getByRole('button',{name:'전송',exact:true}).click();
      await page.waitForFunction(text=>[...document.querySelectorAll('.wb-chat-rows .wb-chat-text')].some(el=>el.textContent===text),row.text);
    }
    assert.ok(messages.some(m=>m.t==='utterance'&&m.speaker==='customer'));
    assert.ok(messages.some(m=>m.t==='utterance'&&m.speaker==='teller'));
    await page.getByRole('button',{name:'확인 기록',exact:true}).waitFor();
    await allSizes(page,'split-conversation');
    const geometry=await page.evaluate(()=>{
      const box=selector=>{const r=document.querySelector(selector).getBoundingClientRect();return{left:r.left,right:r.right,top:r.top,bottom:r.bottom};};
      return {chat:box('.wb-transcript'),shortcuts:box('.wb-shortcuts'),guide:box('.wb-guidance'),logoFilter:getComputedStyle(document.querySelector('.wb-brand img')).filter,headerPadding:parseFloat(getComputedStyle(document.querySelector('.wb-heading')).paddingTop)};
    });
    assert.ok(geometry.chat.right+10<=geometry.guide.left,'chat and guidance must be side by side');
    assert.ok(Math.abs(geometry.shortcuts.top-geometry.guide.top)<2 && Math.abs(geometry.chat.bottom-geometry.guide.bottom)<2,'shortcut/guide tops and chat/guide bottoms must align');
    assert.ok(geometry.chat.top>=geometry.shortcuts.bottom+10,'conversation needs separation below shortcuts');
    assert.equal(geometry.logoFilter,'none'); assert.ok(geometry.headerPadding>=8);
    const roleGeometry=await page.evaluate(()=>[...document.querySelectorAll('.wb-chat-rows .wb-chat-entry')].map(el=>{
      const bubble=el.querySelector('.wb-chat-bubble').getBoundingClientRect(),row=el.getBoundingClientRect();
      return {role:el.dataset.speaker,left:bubble.left-row.left,right:row.right-bubble.right};
    }));
    assert.ok(roleGeometry.some(row=>row.role==='customer'));assert.ok(roleGeometry.some(row=>row.role==='teller'));
    for(const row of roleGeometry) assert.ok(row.role==='customer'?Math.abs(row.left)<2:row.role==='teller'?Math.abs(row.right)<2:true,'role alignment');
    await page.locator('.wb-conversation-filters').getByRole('button',{name:'고객',exact:true}).click();
    assert.equal(await page.locator('.wb-chat-rows .wb-chat-entry:not([data-speaker="customer"])').count(),0);
    await page.locator('.wb-conversation-filters').getByRole('button',{name:'상담원',exact:true}).click();
    assert.equal(await page.locator('.wb-chat-rows .wb-chat-entry:not([data-speaker="teller"])').count(),0);
    await page.locator('.wb-conversation-filters').getByRole('button',{name:'전체',exact:true}).click();
    await page.screenshot({path:path.join(output,'consultation-service-desktop.png')});
    for(const [pane,label] of [['attention','현재 안내'],['checks','필수 안내']]) {
      await page.setViewportSize({width:390,height:844});
      await page.locator('.wb-mobile-tabs').getByRole('button',{name:new RegExp(label)}).click();
      await allSizes(page,`split-${pane}`);
    }
    await page.locator('.wb-chat-rows .wb-chat-bubble').first().click();
    await allSizes(page,'split-utterance-detail');
    await page.getByRole('dialog').getByRole('button',{name:'닫기',exact:true}).click();
    const chat=page.locator('[data-paged-list="상담 전사"]');
    await chat.getByRole('button',{name:'상담 전사 이전 페이지'}).click();
    const previous=await chat.locator('.wb-chat-rows').innerText();
    await page.getByLabel('화자',{exact:true}).selectOption('customer');
    await page.getByLabel('상담 발화',{exact:true}).fill('네, 안내해 주신 내용 확인했습니다.');
    await page.getByRole('button',{name:'전송',exact:true}).click();
    await page.waitForTimeout(500);
    assert.equal(await chat.locator('.wb-chat-rows').innerText(),previous,'reading an earlier page must not jump on new speech');
    await chat.getByRole('button',{name:'최신 발화',exact:true}).click();
    await chat.getByText('네, 안내해 주신 내용 확인했습니다.',{exact:true}).first().waitFor();
    await inspect(page,'split-follow-latest');
    await page.getByRole('button',{name:'상담 종료',exact:true}).click();
    await page.getByRole('heading',{name:'종료 리포트',exact:true}).waitFor();
    await page.getByLabel('규정 팩 버전',{exact:true}).waitFor();
    await allSizes(page,'split-report');
    await inspect(page,'split-report-desktop');
    const reportGeometry=await page.evaluate(()=>{
      const box=selector=>{const r=document.querySelector(selector).getBoundingClientRect();return {top:r.top,bottom:r.bottom,left:r.left,right:r.right};};
      return {heading:box('.wb-heading'),title:box('.wb-heading h1'),version:box('.wb-report-version')};
    });
    assert.ok(reportGeometry.title.top>=24,'report title needs space above it');
    assert.ok(reportGeometry.version.left>reportGeometry.title.right,'report version belongs in the right toolbar');
    assert.equal(await page.locator('.wb-heading>div:first-child p').count(),0,'report version must not be a subtitle');
    assert.equal(await page.getByLabel('규정 팩 버전',{exact:true}).innerText(),scenario.pack_version);
    await page.screenshot({path:path.join(output,'consultation-report-header.png')});
    console.log(JSON.stringify({checks:checks.length,failures,pageErrors,sessionId,serverUtterances:messages.filter(m=>m.t==='utterance').length,geometry,reportGeometry},null,2));
    if(failures.length||pageErrors.length)process.exitCode=1;
  } catch(error) {process.exitCode=1;console.error(error);await page.screenshot({path:path.join(output,'split-failure.png')}).catch(()=>{});}
  finally {
    // Close only this test's consultation, never an existing user session.
    if(await page.getByRole('button',{name:'상담 종료',exact:true}).isVisible().catch(()=>false)) {
      await page.getByRole('button',{name:'상담 종료',exact:true}).click().catch(()=>{});
      await page.getByRole('heading',{name:'종료 리포트',exact:true}).waitFor().catch(()=>{});
    }
    fs.writeFileSync(path.join(output,'consultation-layout-qa.json'),JSON.stringify({checks,failures,pageErrors,sessionId,events:messages.map(({t,speaker,alert_type})=>({t,speaker,alert_type}))},null,2));
    await browser.close();
  }
})();
