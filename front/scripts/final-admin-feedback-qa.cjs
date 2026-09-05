// Real catalog/authentication; approval POST intercepted, never approves real content.
const assert = require('node:assert/strict');
const fs = require('node:fs'); const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || path.join(process.env.USERPROFILE, '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const { allSizes, failures, checks } = require('./workspace-qa.cjs');
const result = { scope: 'real GET/auth, isolated approval response', failures, checks, errors: [], realApprovals: 0 };
(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    page.on('pageerror', e => result.errors.push(e.message));
    let approval, release;
    await page.route('**/api/**', async route => {
      const request = route.request();
      if (request.method() === 'GET') return route.continue();
      if (request.url().endsWith('/approve')) {
        approval = request.postDataJSON();
        await new Promise(resolve => { release = resolve; });
        return route.fulfill({ status: 503, json: { message: '격리 검사: 승인 저장 실패' } });
      }
      result.errors.push(`Unexpected mutation: ${request.method()}`); return route.abort();
    });
    await page.goto('http://localhost:3000');
    await page.getByRole('button', { name: '기준 관리', exact: true }).click();
    await page.getByRole('button', { name: '관리자 인증', exact: true }).click();
    await page.getByLabel('관리자 토큰').fill(fs.readFileSync(path.resolve(__dirname, '../.admin-token'), 'utf8').trim());
    await page.getByRole('button', { name: '인증 확인', exact: true }).click();
    await page.getByRole('button', { name: '인증 해제', exact: true }).waitFor();
    await page.getByRole('button', { name: '문서 검수', exact: true }).click();
    await page.locator('[data-paged-list="문서 목록"] .wb-row-button').filter({ hasText: '원화정기예금 상품설명서' }).click();
    await page.locator('[data-paged-list="검수 후보"] .wb-row-button').filter({ hasText: '검수 대기' }).first().click();
    await page.getByRole('button', { name: '검수 내용 수정', exact: true }).click();
    await page.getByLabel('검수 수정 내용').fill('격리 UI 검사 항목 이름');
    await page.getByRole('button', { name: '원문과 수정 내용 확인', exact: true }).click();
    await page.getByRole('button', { name: '검수 내용 수정', exact: true }).click();
    await page.getByLabel('수정할 내용').selectOption('plain_language');
    await page.getByLabel('검수 수정 내용').fill('격리 검사 문장입니다. 실제 승인하지 않습니다.');
    await allSizes(page, 'candidate-edit-feedback');
    await page.getByLabel('검수자 이름').fill('isolated-ui-test');
    await page.getByRole('button', { name: '검수 후 승인', exact: true }).click();
    await page.getByRole('button', { name: '승인 중…', exact: true }).waitFor();
    assert.ok(await page.getByRole('button', { name: '승인 중…', exact: true }).isDisabled());
    assert.equal(approval.edits.name, '격리 UI 검사 항목 이름');
    assert.deepEqual(approval.edits.plain_language, ['격리 검사 문장입니다. 실제 승인하지 않습니다.']);
    release();
    await page.getByText('격리 검사: 승인 저장 실패', { exact: true }).waitFor();
    assert.ok(await page.getByRole('button', { name: '검수 후 승인', exact: true }).isEnabled());
    await page.getByRole('dialog').getByRole('button', { name: '닫기', exact: true }).click();
    const switched = page.waitForResponse(response => decodeURIComponent(response.url()).includes('/06_상품설명서_가계대출/candidates'));
    await page.getByLabel('검수 문서 바로 선택').selectOption('06_상품설명서_가계대출');
    assert.equal((await switched).status(), 200);
    assert.equal(await page.locator('[data-paged-list="문서 목록"]').count(), 0);
    await allSizes(page, 'document-direct-switch');
    await page.getByLabel('검수 문서 바로 선택').selectOption('05_상품설명서_정기예금');
    await page.getByRole('button', { name: '추출 원문', exact: true }).click();
    await page.locator('[data-paged-list="추출 블록"] .wb-row-button').first().waitFor();
    const table = page.locator('[data-paged-list="추출 블록"] .wb-row-button').filter({ hasText: '· table' }).first();
    for (let attempt = 0; attempt < 10 && !await table.isVisible(); attempt++) {
      const next = page.getByLabel('추출 블록 다음 페이지');
      if (!await next.isEnabled()) break;
      await next.click();
    }
    await table.click();
    await page.getByRole('cell').first().click();
    await page.getByRole('button', { name: '표로 돌아가기', exact: true }).waitFor();
    assert.equal(await page.locator('dialog[open]').count(), 1);
    await allSizes(page, 'table-inline-cell');
    await page.getByRole('button', { name: '표로 돌아가기', exact: true }).click();
    await page.getByRole('cell').first().waitFor();
    await page.getByRole('dialog').getByRole('button', { name: '닫기', exact: true }).click();
    await page.getByRole('button', { name: 'PDF 업로드', exact: true }).click();
    await allSizes(page, 'document-upload-feedback');
    assert.ok(await page.getByRole('dialog').getByRole('button', { name: 'PDF 업로드', exact: true }).isDisabled());
    await page.getByRole('dialog').getByRole('button', { name: '닫기', exact: true }).click();
    await page.getByRole('navigation', { name: '주 메뉴' }).getByRole('button', { name: '상담', exact: true }).click();
    await page.getByRole('navigation', { name: '주 메뉴' }).getByRole('button', { name: '기준 관리', exact: true }).click();
    await page.locator('[data-workspace="documents"]').waitFor();
    assert.deepEqual(failures, []); assert.deepEqual(result.errors, []);
    console.log(`PASS: candidate edits survive review toggle, pending/error/retry, ${checks.length} layouts; no real approvals.`);
  } finally {
    fs.writeFileSync(path.resolve(__dirname, '../qa-output/final-admin-feedback-qa.json'), JSON.stringify(result, null, 2));
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
