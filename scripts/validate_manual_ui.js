// Run against the 33-variable fixture described in docs/manual-review-development.md:
// npx --yes --package @playwright/cli playwright-cli run-code --filename scripts/validate_manual_ui.js
async (page) => {
  const url = 'http://127.0.0.1:8876/index.html';
  const assert = (value, message) => { if (!value) throw new Error(message); };
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(url);
  await page.waitForFunction(() => document.querySelector('#manual-message').textContent.includes('已连接'));
  const fixtureRoot = await page.evaluate(async () => {
    const report = await (await fetch('/reports/global_static_concurrency.json')).json();
    return report.coverage.project_root;
  });
  await page.locator('.tabs a[href="#manual"]').click();
  const table = page.locator('#manual-table');
  const visible = () => table.locator('tbody > tr:visible');
  assert(await visible().count() === 25, 'first page must contain 25 variables');
  await page.locator('.pager[data-table="manual-table"] [data-step="1"]').click();
  assert(await visible().count() === 8, 'second page must contain remaining 8 variables');
  await page.locator('#manual-continue').click();
  const selected = page.locator(await page.evaluate(() => location.hash));
  assert(await selected.isVisible(), 'continue must reveal a pending variable across pages');
  const selectedId = await selected.getAttribute('id');
  await page.evaluate(() => {
    globalThis.manualMutatedIds = new Set();
    for (const node of document.querySelectorAll('[data-manual-id]')) {
      new MutationObserver(() => globalThis.manualMutatedIds.add(node.dataset.manualId))
        .observe(node, {subtree:true, attributes:true, childList:true, characterData:true});
    }
  });
  await selected.getByRole('button', {name:'确认无风险', exact:true}).click();
  await page.getByRole('button', {name:'保存确认', exact:true}).click();
  assert((await page.locator('#manual-save-message').textContent()).includes('请填写'), 'safe requires a reason');
  const note = '<img src=x onerror="globalThis.PWNED=1"> 人工依据：硬件串行执行';
  await page.locator('#manual-reason').fill(note);
  await page.locator('#manual-reviewer').fill('浏览器自动验收');
  await page.getByRole('button', {name:'保存确认', exact:true}).click();
  await page.locator('#manual-dialog').waitFor({state:'hidden'});
  assert((await page.locator('#manual-progress').textContent()).includes('已确认无风险：1'), 'progress must update');
  assert(await page.evaluate(() => globalThis.manualMutatedIds.size === 1), 'only the changed variable badges may update');
  assert(await page.evaluate(() => !globalThis.PWNED), 'notes must never execute HTML');
  await page.reload();
  await page.waitForFunction(() => document.querySelector('#manual-message').textContent.includes('已连接'));
  assert((await page.locator('#manual-progress').textContent()).includes('已确认无风险：1'), 'reload must recover durable state');
  await page.locator('.tabs a[href="#manual"]').click();
  await page.locator('#filter').selectOption('CONFIRMED_SAFE');
  assert(await visible().count() === 1, 'manual state filter');
  const name = await visible().first().locator('td a').first().textContent();
  await page.locator('#q').fill(name);
  assert(await visible().count() === 1, 'search must preserve correct identity');
  await visible().first().getByRole('button', {name:'撤销确认', exact:true}).click();
  await page.locator('#manual-reason').fill('撤销先前测试结论，继续核对');
  await page.getByRole('button', {name:'保存确认', exact:true}).click();
  await page.locator('#manual-dialog').waitFor({state:'hidden'});
  assert((await page.locator('#manual-progress').textContent()).includes('已确认无风险：0'), 'undo restores pending progress');
  await page.locator('#manual-continue').click();
  const pending = page.locator(await page.evaluate(() => location.hash));
  await pending.getByRole('button', {name:'确认有风险', exact:true}).click();
  await page.locator('#manual-reason').fill('主循环读改写被中断打断');

  // A second page reads the same revision before the first page saves.
  const second = await page.context().newPage();
  await second.goto(url + '#' + selectedId);
  await second.waitForFunction(() => document.querySelector('#manual-message').textContent.includes('已连接'));
  await second.locator('#' + selectedId).getByRole('button', {name:'确认无风险', exact:true}).click();
  await second.locator('#manual-reason').fill('第二页面的旧修订，不得覆盖');
  await page.getByRole('button', {name:'保存确认', exact:true}).click();
  await page.locator('#manual-dialog').waitFor({state:'hidden'});
  await second.getByRole('button', {name:'保存确认', exact:true}).click();
  await second.waitForFunction(() => document.querySelector('#manual-save-message').textContent.includes('保存失败'));
  assert((await second.locator('#manual-save-message').textContent()).includes('其他页面'), 'optimistic conflict must be explained');
  await second.close();

  const download = page.waitForEvent('download');
  await page.locator('#manual-export').click();
  await (await download).saveAs('output/playwright/manual-review-export.json');
  await page.locator('#manual-all-history').click();
  await page.locator('#manual-dialog').waitFor({state:'visible'});
  assert((await page.locator('#manual-history-text').textContent()).includes('撤销先前测试结论'), 'history preserves undo reason');
  assert(await page.evaluate(() => !globalThis.PWNED), 'history renders malicious notes as text');
  await page.locator('#manual-close').click();
  await page.screenshot({path:'output/playwright/manual-review.png', fullPage:true});
  await page.locator('header a[href="opencode_review.html"]').click();
  await page.waitForFunction(() => document.querySelector('#manual-message').textContent.includes('已连接'));
  assert((await page.locator('#manual-progress').textContent()).includes('已确认有风险：1'), 'review page shares manual state');
  await page.emulateMedia({media:'print'});
  await page.pdf({path:'output/playwright/manual-review-print.pdf'});
  await page.emulateMedia({media:'screen'});
  await page.goto('file:///' + fixtureRoot.replace(/\\/g, '/') + '/.ecra/index.html');
  assert((await page.locator('#manual-message').textContent()).includes('离线报告仅供查看'), 'offline persistence notice');
  assert(await page.locator('[data-manual-edit]:enabled').count() === 0, 'offline edits must stay disabled');
  assert(errors.length === 0, 'browser exceptions: ' + errors.join('; '));
  console.log('PASS: pagination, continue, safe reason, save, reload, undo, search, conflict, history, XSS, export, review page, print, offline');
}
