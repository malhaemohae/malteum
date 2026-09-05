const path=require('node:path');const fs=require('node:fs');const assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const {allSizes,checks,failures,pageErrors}=require('./workspace-qa.cjs');
(async()=>{
  const browser=await chromium.launch({headless:true});
  try {
    const page=await browser.newPage({viewport:{width:1440,height:900}});
    page.on('pageerror',error=>pageErrors.push(error.message));
    await page.goto(process.env.QA_BASE_URL||'http://127.0.0.1:3000');
    await page.getByRole('button',{name:'기준 관리',exact:true}).click();
    await page.getByRole('button',{name:'문서 검수',exact:true}).click();
    await page.locator('[data-paged-list="문서 목록"] .wb-row-button').filter({hasText:'원화정기예금 상품설명서'}).click();
    await page.locator('[data-paged-list="검수 후보"] .wb-row-button').first().click();
    await page.getByRole('dialog',{name:'후보 검수'}).waitFor();
    await allSizes(page,'candidate-detail');
    fs.writeFileSync(path.resolve(__dirname,'../qa-output/candidate-qa.json'),JSON.stringify({checks,failures,pageErrors},null,2));
    assert.deepEqual(failures,[]);assert.deepEqual(pageErrors,[]);
    console.log(`PASS: ${checks.length} real candidate review layouts.`);
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
