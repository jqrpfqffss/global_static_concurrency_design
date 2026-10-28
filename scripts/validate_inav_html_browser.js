async (page) => {
  const errors = [], warnings = [], failedRequests = [];
  page.on('pageerror', error => errors.push(String(error)));
  page.on('console', message => {
    if (message.type() === 'error') errors.push(message.text());
    if (message.type() === 'warning') warnings.push(message.text());
  });
  page.on('requestfailed', request => failedRequests.push(request.url()));
  const check = (condition, message) => { if (!condition) throw Error(message); };
  const url = page.url().split('#')[0];
  check(/^http:\/\/127\.0\.0\.1:\d+\/index\.html/.test(url), '必须先打开绑定本机回环地址的 INAV 首页');
  await page.goto(url, {timeout: 120000});
  const initial = await page.evaluate(() => ({
    rows: document.querySelectorAll('table.searchable > tbody > tr[data-group]').length,
    contexts: window.length, frames: document.querySelectorAll('iframe').length,
    graphLoaded: !!window.ECRA_CALL_GRAPH,
    loadMs: performance.getEntriesByType('navigation')[0].loadEventEnd
  }));
  check(initial.contexts === 0 && initial.frames === 0, '折叠页面预先占用了浏览上下文');
  const q = page.locator('#q'), variable = 'uart1.port.port.txBufferTail';
  await q.fill(variable);
  const row = page.locator('#inventory-table > tbody > tr[data-group]').filter({
    has: page.getByRole('link', {name: variable, exact: true})
  });
  await row.waitFor({state: 'visible', timeout: 30000});
  check(await row.count() === 1, '目标 UART 变量没有唯一显示');
  const rowId = await row.getAttribute('id');
  check(/^[a-z0-9-]+$/.test(rowId), '目标变量锚点无效');
  const detail = page.locator('#' + rowId).locator('details[data-external-detail="1"]');
  const summary = detail.locator(':scope > summary');
  const completeFrame = async () => page.waitForFunction(() => {
    const frame = document.querySelector('iframe[src]');
    return window.length === 1 && frame?.contentDocument?.readyState === 'complete' && frame.contentDocument.URL === frame.src;
  }, null, {timeout: 30000});
  const noFrames = async () => page.waitForFunction(() => window.length === 0 &&
    document.querySelectorAll('iframe').length === 0, null, {timeout: 15000});
  await summary.click(); await completeFrame();
  await summary.click(); await noFrames();
  await summary.click(); await completeFrame();
  await q.fill('ECRA_UI_NO_MATCH_' + Date.now());
  await noFrames();
  check(await detail.getAttribute('open') !== null, '隐藏详情时丢失了原展开状态');
  await q.fill(variable); await completeFrame();
  await page.locator('.tabs a[href="#risks"]').click(); await noFrames();
  await page.locator('.tabs a[href="#inventory"]').click(); await completeFrame();
  const frame = page.locator('iframe[data-ecra-src]').contentFrame();
  await frame.locator('details.graph > summary').click();
  await frame.locator('details.graph[data-loaded="1"]').waitFor({timeout: 30000});
  const graph = await page.evaluate(() => {
    const frame = document.querySelector('iframe[src]'), doc = frame.contentDocument;
    const graph = frame.contentWindow.ECRA_CALL_GRAPH;
    const lines = doc.querySelector('details.graph pre').textContent.split(/\n|\\n/);
    return {functions: Object.keys(graph.functions).length, calls: graph.calls.length,
      edges: lines.length, main: lines.some(line => line.startsWith('main (')),
      uartIrq: lines.some(line => line.includes('USART1_IRQHandler'))};
  });
  check(graph.main && graph.uartIrq, '完整调用图没有同时保留 main 和 USART1 中断证据');
  await q.fill('txBufferTail'); await page.locator('#page-size').selectOption('25');
  const filterState = () => page.evaluate(() => {
    const rows = [...document.querySelectorAll('#inventory-table > tbody > tr[data-group]')];
    const query = document.getElementById('q').value.toLowerCase();
    const filter = document.getElementById('filter').value, [kind, value] = filter.split(':');
    const index = window.ECRA_SEARCH_INDEX || {};
    const matches = rows.filter(row => {
      const text = row.dataset.searchRef ? index[row.dataset.searchRef] : row.dataset.search || row.textContent;
      return text.toLowerCase().includes(query) && (filter === 'all' ||
        (value ? row.dataset[kind] === value : row.dataset.group === filter));
    });
    const visible = rows.filter(row => !row.hidden);
    return {matches: matches.length, visible: visible.length, first: visible[0]?.id,
      decisions: [...new Set(visible.map(row => row.dataset.decision))],
      page: document.querySelector('#inventory .pager').textContent};
  });
  let state = await filterState();
  check(state.visible === Math.min(25, state.matches), '25 条分页数量不一致');
  const next = page.locator('#inventory').getByRole('button', {name: '下一页', exact: true});
  let pagingExecuted = false;
  if (await next.isEnabled()) {
    const first = state.first; await next.click(); state = await filterState();
    check(state.first !== first && state.page.includes('第 2 /'), '下一页没有切换记录');
    pagingExecuted = true;
  }
  await page.locator('#page-size').selectOption('100'); state = await filterState();
  check(state.visible === Math.min(100, state.matches), '100 条分页数量不一致');
  await page.locator('#filter').selectOption('decision:likely'); state = await filterState();
  check(state.visible === Math.min(100, state.matches) && state.decisions.every(value => value === 'likely'),
    '疑似风险筛选与完整索引不一致');
  check(!errors.length && !warnings.length && !failedRequests.length, '浏览器存在错误、警告或请求失败');
  return {complete: true, kind: 'SAVED_HTML_BROWSER_VERIFICATION', native_acceptance: false,
    safety_report_valid: false, review_executed: false, initial, graph,
    close_reopen: true, filter_hide_restore: true, panel_hide_restore: true,
    paging_executed: pagingExecuted, final_filter: state, errors, warnings, failedRequests};
}
