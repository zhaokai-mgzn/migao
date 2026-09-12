/**
 * 加工单功能 UI 旅程验收脚本（issue #3349，acceptance-protocol §2.3）
 * 以「商家运营」persona 走查订单详情页加工单区块，采集截图 + DOM 几何证据。
 * 四类必查：① 命名一致性 ② 全局样式基准 ③ 布局遮挡几何 ④ 写操作成果物可见性
 *
 * 运行：node accept-processing-order-ui.js <orderId>
 */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const ORDER_ID = process.argv[2];
if (!ORDER_ID) {
  console.error('用法: node accept-processing-order-ui.js <orderId>');
  process.exit(1);
}

const OUT = path.resolve(__dirname, 'acceptance/2026-09-12/processing-order/ui-evidence');
fs.mkdirSync(OUT, { recursive: true });
const evidence = { orderId: ORDER_ID, checks: {}, screenshots: [] };

const rect = (el) => {
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height), bottom: Math.round(r.bottom), right: Math.round(r.right) };
};
const overlaps = (a, b) => !!a && !!b && a.x < b.right && a.right > b.x && a.y < b.bottom && a.bottom > b.y;

async function probe(page) {
  return page.evaluate(() => {
    const q = (sel) => document.querySelector(sel);
    const r = (el) => { if (!el) return null; const b = el.getBoundingClientRect(); return { x: Math.round(b.x), y: Math.round(b.y), w: Math.round(b.width), h: Math.round(b.height), bottom: Math.round(b.bottom), right: Math.round(b.right) }; };
    // FAB：position:fixed 且在右下象限的元素（米宝浮动助手）
    const fixed = [...document.querySelectorAll('*')].filter((el) => {
      const cs = getComputedStyle(el);
      if (cs.position !== 'fixed' || cs.visibility === 'hidden' || cs.display === 'none') return false;
      const b = el.getBoundingClientRect();
      return b.width > 20 && b.height > 20 && b.left > window.innerWidth * 0.5 && b.top > window.innerHeight * 0.4;
    }).map((el) => ({ tag: el.tagName, cls: el.className.toString().slice(0, 60), rect: r(el) }));
    const heading = [...document.querySelectorAll('h1,h2,h3')].find((el) => el.textContent.includes('加工单'));
    const btns = [...document.querySelectorAll('button')].map((el) => ({ text: el.textContent.trim().slice(0, 12), rect: r(el) })).filter((b) => b.text);
    const container = q('main') || q('[class*="p-6"]');
    const bc = [...document.querySelectorAll('nav, [class*="breadcrumb"], header')].map((el) => el.textContent.replace(/\s+/g, ' ').trim().slice(0, 80)).filter(Boolean).slice(0, 4);
    return {
      fab: fixed,
      poHeading: heading ? { text: heading.textContent.trim(), rect: r(heading) } : null,
      buttons: btns,
      container: { rect: r(container), padding: container ? getComputedStyle(container).padding : null },
      h1: (() => { const h = document.querySelector('h1'); return h ? { text: h.textContent.trim(), fontSize: getComputedStyle(h).fontSize } : null; })(),
      breadcrumbs: bc,
      scrollHeight: document.documentElement.scrollHeight,
      viewportH: window.innerHeight,
    };
  });
}

(async () => {
  const browser = await chromium.launch({ channel: 'chrome' });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();

  // ── 登录（商家运营 persona）──
  await page.goto('http://localhost:3001/login', { waitUntil: 'domcontentloaded' });
  await page.fill('#phone', '13800138000');
  const sendBtn = page.locator('button', { hasText: '发送' }).first();
  if (await sendBtn.count()) await sendBtn.click();
  await page.fill('#code', '123456');
  await page.locator('button[type="submit"]').first().click();
  await page.waitForURL(/dashboard|orders/, { timeout: 30000 });
  evidence.checks.login = { ok: true, url: page.url() };

  // ── 基准页（订单列表）样式对照 ──
  await page.goto('http://localhost:3001/orders', { waitUntil: 'networkidle' });
  const baseline = await probe(page);
  await page.screenshot({ path: path.join(OUT, '00-baseline-orders-list.png') });
  evidence.checks.styleBaseline = { h1: baseline.h1, containerPadding: baseline.container.padding };

  // ── 订单详情页 ──
  await page.goto(`http://localhost:3001/orders/${ORDER_ID}`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1200);
  const top = await probe(page);
  await page.screenshot({ path: path.join(OUT, '01-order-detail-top.png') });
  await page.screenshot({ path: path.join(OUT, '02-order-detail-full.png'), fullPage: true });
  evidence.screenshots.push('01-order-detail-top.png', '02-order-detail-full.png');

  // ① 命名一致性：面包屑/标题含「订单」；无「加工单管理」等错名
  evidence.checks.naming = {
    breadcrumbs: top.breadcrumbs,
    h1: top.h1,
    poHeadingText: top.poHeading ? top.poHeading.text : null,
  };

  // ② 样式基准对照
  evidence.checks.styleMatch = {
    detailH1: top.h1,
    baselineH1: baseline.h1,
    detailContainerPadding: top.container.padding,
    baselineContainerPadding: baseline.container.padding,
    h1FontSizeEqual: top.h1 && baseline.h1 ? top.h1.fontSize === baseline.h1.fontSize : null,
  };

  // ③ 布局遮挡几何探针（内容不足一屏 + 滚到底）
  const fab = top.fab[0] ? top.fab[0].rect : null;
  const poBlock = top.poHeading ? top.poHeading.rect : null;
  const actionBtns = top.buttons.filter((b) => ['生成加工单', '发加工', '开始加工', '加工完成', '取消加工单', '复制全部', '打印'].includes(b.text));
  const beforeOverlap = actionBtns.map((b) => ({ btn: b.text, rect: b.rect, overlapsFab: overlaps(b.rect, fab) }));
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  await page.waitForTimeout(600);
  const bottom = await probe(page);
  await page.screenshot({ path: path.join(OUT, '03-order-detail-scrolled-bottom.png') });
  const fabBottom = bottom.fab[0] ? bottom.fab[0].rect : null;
  const btnsBottom = bottom.buttons.filter((b) => ['生成加工单', '发加工', '开始加工', '加工完成', '取消加工单', '复制全部', '打印'].includes(b.text));
  // 可点击性：区块标题中心点 elementFromPoint 命中自身或其后代
  const clickable = await page.evaluate(() => {
    const h = [...document.querySelectorAll('h1,h2,h3')].find((el) => el.textContent.includes('加工单'));
    if (!h) return null;
    const b = h.getBoundingClientRect();
    const el = document.elementFromPoint(b.x + b.width / 2, b.y + b.height / 2);
    return { hitTag: el ? el.tagName : null, hitIsHeadingOrChild: !!el && (el === h || h.contains(el) || el.contains(h)) };
  });
  evidence.checks.geometry = {
    fab, viewportH: top.viewportH, pageScrollHeight: top.scrollHeight,
    paddingBottomProbe: { actionBtns: beforeOverlap, fabBottom, bottomActionBtns: btnsBottom.map((b) => ({ btn: b.text, rect: b.rect, overlapsFab: overlaps(b.rect, fabBottom) })) },
    clickableProbe: clickable,
  };

  // ④ 写操作成果物可见性：发加工 → 状态推进可见
  const stateBefore = await page.locator('text=已生成').count();
  const issueBtn = page.locator('button', { hasText: '发加工' }).first();
  if (await issueBtn.count()) {
    await issueBtn.click();
    await page.waitForTimeout(300);
    const procInput = page.locator('input[placeholder*="加工方"]').first();
    if (await procInput.count()) await procInput.fill('UI验收加工厂');
    const dateInput = page.locator('input[placeholder*="交期"]').first();
    if (await dateInput.count()) await dateInput.fill('2026-09-30');
    await page.screenshot({ path: path.join(OUT, '04-issue-form.png') });
    await page.locator('button', { hasText: '确认发加工' }).first().click();
    await page.waitForTimeout(2500);
    const stateAfter = { issued: await page.locator('text=已发加工').count(), processor: await page.locator('text=UI验收加工厂').count(), copyBtn: await page.locator('button', { hasText: '复制全部' }).count() };
    await page.screenshot({ path: path.join(OUT, '05-after-issue.png') });
    evidence.screenshots.push('03-order-detail-scrolled-bottom.png', '04-issue-form.png', '05-after-issue.png');
    evidence.checks.writeVisibility = {
      before: { generatedBadge: stateBefore }, after: stateAfter,
      verdict: stateAfter.issued > 0 && stateAfter.processor > 0 ? 'PASS' : 'FAIL',
    };
  } else {
    evidence.checks.writeVisibility = { verdict: 'SKIP', reason: '当前状态无「发加工」按钮' };
  }

  fs.writeFileSync(path.join(OUT, 'evidence.json'), JSON.stringify(evidence, null, 2));
  console.log(JSON.stringify(evidence, null, 2));
  await browser.close();
})();
