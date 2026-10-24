// case_ids: BM-044
/**
 * B 端 H5「问黄金策」输入条的**几何判据**（issue #6596；issue #7252 补真机安全区档）
 *
 * ## 治的形态（用户真机截图 + 主会话独立探针读数）
 *
 * `MerchantTabBar` 是 `position: fixed; bottom: 0` 的**浮层**，而 `.chat-page` 是 `height: 100vh`
 * 且**没有为它留位** ⇒ 输入条被底栏压住。线上 BEFORE 读数（390×844，真 Chrome）：
 *
 * | 读数 | 修前（app.migaozn.com/b/，#6596 之前） |
 * |---|---|
 * | `.chat-page` 高度 | **864px**（视口 844 ⇒ 高出 20px = 状态栏 `padding-top` 被 content-box 加在 100vh 之上） |
 * | `.message-input` 底边 | **864**（已在视口外） |
 * | `.merchant-tabbar` 顶边 | **794** ⇒ 被遮 **70px**（`COVERED`） |
 *
 * ## 为什么补「安全区 34」这一档（issue #7252）
 *
 * #6596 上线后本腿只跑 Chromium 默认档（`env(safe-area-inset-bottom)=0`）⇒ 恰好**看不见**底栏的
 * `content-box` 缺陷：底栏同时写 `height: calc(50PX + env(...))` 与 `padding-bottom: env(...)`，
 * 无安全区时实用高 50 = 页面预留 50（绿），有安全区 34 时实用高 **118**、预留 84 ⇒ 输入条被压 **34px**
 * （用户 2026-10-18 真机「按住说话被遮住一半」）。⇒ 本腿用 CDP `Emulation.setSafeAreaInsetsOverride`
 * 补跑 **safe=34** 一档：旧 CSS 在这一档 `coveredPx = +34`、底栏高 118，**必红**。
 *
 * ## 判据（几何数字，不是「看着正常」）
 *
 * | # | 断言 | 回归时会怎么红 |
 * |---|---|---|
 * | 1 | 默认语音模式：`__hold` 在位（用户裁定「默认文字叫按住说话」） | 默认变成打字 ⇒ 红 |
 * | 2 | 🔴 `coveredPx = 输入条底边 − 底栏顶边 ≤ 0`（**两档安全区各跑一次**） | 撤掉 `.chat-page` 的预留 ⇒ 70px 重叠 ⇒ 红；底栏丢 `box-sizing: border-box` ⇒ 34px 重叠 ⇒ 红 |
 * | 3 | 🔴 `chatPageHeight ≤ viewportHeight`（整页不高于视口） | 去掉 `box-sizing: border-box` ⇒ 864 > 844 ⇒ 红 |
 * | 4 | 单行：切换键 / 中间区 / 添图键等高且竖直中心对齐（±1px） | 退回两行结构 ⇒ 红 |
 * | 5 | 🔴 safe=34 档：底栏**实用高 = 84**（50 + 安全区）、贴视口底边、页面预留 = 84 | content-box ⇒ 118 ≠ 84 ⇒ 红 |
 *
 * ## 边界（照实登记，§19.1）
 *
 * - 本腿走**本地 H5 产物**（`playwright.bmini.config.ts` 自带产物新鲜度前置断言 + 静态服务），
 *   `/api/**` **桩掉**（只读、不产生真实写请求）⇒ 不连后端。
 * - 安全区由 CDP 模拟（不是真机）：`Emulation.setSafeAreaInsetsOverride{bottom:34}` 会真正改写页面的
 *   `env(safe-area-inset-bottom)`（本机实测：底栏 50 → 84，与真机同式）。旧版 Chrome 不支持该命令 ⇒
 *   该档**显式 skip**（`test.skip` 会在报告里可见，不当成「跑过」）；不支持的浏览器由
 *   `frontend/bmini-app/tests/tabbar-content-inset.test.ts` 的盒模型复算兜底。
 * - 真机读数另记（PR body 的未覆盖登记）。
 * - 🔴 本文件不许出现弱断言（fail-closed）。
 */
import { test, expect } from '@playwright/test'

const CHAT_PAGE = '/#/pages/chat/index/index'
/** Taro 注入的原生条高（= 页面预留算式里的 50PX）；安全区另加 `env(...)` */
const TABBAR_BASE_HEIGHT = 50
const IPHONE_SAFE_BOTTOM = 34

/** 桩：本腿只判几何，不连后端（`/api/**` 一律返回空壳，页面按「拿不到 ⇒ 照常渲染输入条」走） */
async function stubBackend(page: import('@playwright/test').Page) {
  await page.route('**/api/**', async (route) => {
    const url = route.request().url()
    // `/api/auth/me` 的响应体形状 = `ApiResponse<User>`，而黄金策唤出授权门读的是
    // `me.capabilities.mibaoChat`（`services/userService.ts::getUserInfo` 判 `res.success && res.data`）
    // ⇒ 桩必须给对形状，否则停在「需要管理员授权」，输入条整块不渲染（几何就没得量）。
    const body = url.includes('/api/auth/me')
      ? {
          success: true,
          data: {
            id: 'e2e',
            username: 'e2e',
            name: 'e2e',
            tenantId: 1,
            capabilities: { mibaoChat: true },
          },
        }
      : { success: true, data: [] }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(body),
    })
  })
}

/** 登录态（Taro h5 的 storage 是 `localStorage[key] = JSON.stringify({data})`） */
async function seedAuth(page: import('@playwright/test').Page) {
  const payload = Buffer.from(
    JSON.stringify({ sub: 'e2e', exp: Math.floor(Date.now() / 1000) + 86400 }),
  ).toString('base64')
  await page.addInitScript(
    ([token, user]) => {
      localStorage.setItem('auth_token', JSON.stringify({ data: token }))
      localStorage.setItem('auth_user', JSON.stringify({ data: user }))
    },
    [`e2e.${payload}.sig`, JSON.stringify({ id: 'e2e', name: 'e2e', tenantId: 1 })],
  )
}

/**
 * 把 `env(safe-area-inset-bottom)` 覆盖成给定像素（必须在 `goto` **之前**调用）。
 * 返回是否成功：旧版 Chrome 没有这个 CDP 命令 ⇒ 调用方显式 skip（不是静默通过）。
 */
async function overrideSafeArea(page: import('@playwright/test').Page, bottom: number): Promise<boolean> {
  const cdp = await page.context().newCDPSession(page)
  try {
    await cdp.send('Emulation.setSafeAreaInsetsOverride', { insets: { bottom } })
    return true
  } catch {
    return false
  }
}

type Geometry = {
  inputBottom: number
  barTop: number
  barBottom: number
  barHeight: number
  chatPageHeight: number
  chatPagePaddingBottom: number
  viewportHeight: number
  rowHeight: number
  toggleHeight: number
  centerHeight: number
  attachHeight: number
  toggleTop: number
  centerTop: number
  attachTop: number
}

async function measure(page: import('@playwright/test').Page): Promise<Geometry> {
  return page.evaluate(() => {
    const input = document.querySelector('.message-input')
    const row = document.querySelector('.message-input__row')
    const bar = document.querySelector('.merchant-tabbar')
    const chatPage = document.querySelector('.chat-page')
    const toggle = document.querySelector('.message-input__mode-toggle')
    const center = document.querySelector('.message-input__center')
    const attach = document.querySelector('.message-input__attach')
    // 空草稿时 `__actions` 是空容器（0 高，是渲染条件不是缺陷）⇒ 用**添图键**当"第三个格子"
    if (!input || !bar || !chatPage || !row || !toggle || !center || !attach) {
      throw new Error('拿不到输入条 / 底栏 / 页面根节点 —— 页面白屏或未渲染？')
    }
    const inputRect = input.getBoundingClientRect()
    const barRect = bar.getBoundingClientRect()
    const pageRect = chatPage.getBoundingClientRect()
    const toggleRect = toggle.getBoundingClientRect()
    const centerRect = center.getBoundingClientRect()
    const attachRect = attach.getBoundingClientRect()
    return {
      inputBottom: inputRect.bottom,
      barTop: barRect.top,
      barBottom: barRect.bottom,
      barHeight: barRect.height,
      chatPageHeight: pageRect.height,
      chatPagePaddingBottom: parseFloat(getComputedStyle(chatPage).paddingBottom),
      viewportHeight: window.innerHeight,
      rowHeight: row.getBoundingClientRect().height,
      toggleHeight: toggleRect.height,
      centerHeight: centerRect.height,
      attachHeight: attachRect.height,
      toggleTop: toggleRect.top,
      centerTop: centerRect.top,
      attachTop: attachRect.top,
    }
  })
}

/** 判据 1~4：两档安全区共用的几何断言（跑完返回读数，供额外断言用） */
async function expectInputBarGeometry(
  page: import('@playwright/test').Page,
  safeBottom: number,
): Promise<Geometry> {
  // 判据 1：默认语音模式（用户裁定「默认文字叫按住说话」）
  await expect(page.locator('.message-input__hold')).toBeVisible()
  await expect(page.locator('.message-input__row')).toBeVisible()

  const geometry = await measure(page)
  console.log(
    `[输入条几何 safe=${safeBottom}] 输入条底边=${geometry.inputBottom} 底栏顶边=${geometry.barTop} ` +
      `底栏高=${geometry.barHeight} 重叠=${geometry.inputBottom - geometry.barTop} ` +
      `页面高=${geometry.chatPageHeight} 页预留=${geometry.chatPagePaddingBottom} ` +
      `视口高=${geometry.viewportHeight} 行高=${geometry.rowHeight} ` +
      `三格高=${geometry.toggleHeight}/${geometry.centerHeight}/${geometry.attachHeight}`,
  )

  // 判据 2：底栏不压输入条
  expect(geometry.inputBottom - geometry.barTop).toBeLessThanOrEqual(0)
  // 判据 3：整页不高于视口（`box-sizing: border-box` 守这一条）
  expect(geometry.chatPageHeight).toBeLessThanOrEqual(geometry.viewportHeight)
  // 判据 4：**单行** —— 切换键 / 中间区 / 添图键三个格子的**竖直中心对得齐**（±1 CSS px），
  //   且三格等高（±1 CSS px）⇒ 「四个控件在同一行」不是靠 flex 换行凑出来的。
  //   ⚠️ 不钉「88」这个数：那是 **750 设计稿**的 px，H5 产物经 `postcss-pxtransform` 折成 CSS px
  //   （实测 390×844 下 = 45.75）。钉死设计稿数值会造出一个「永远红」的断言。
  expect(Math.abs(geometry.toggleHeight - geometry.centerHeight)).toBeLessThanOrEqual(1)
  expect(Math.abs(geometry.centerHeight - geometry.attachHeight)).toBeLessThanOrEqual(1)
  expect(Math.abs(geometry.toggleTop - geometry.centerTop)).toBeLessThanOrEqual(1)
  expect(Math.abs(geometry.attachTop - geometry.centerTop)).toBeLessThanOrEqual(1)
  // 行高不会超过最高格 + 容差（行是等高的容器，不随内容抖）
  expect(geometry.rowHeight).toBeLessThanOrEqual(geometry.centerHeight + 1)
  return geometry
}

test.describe('B 端 H5 输入条几何（issue #6596 / #7252）', () => {
  test('默认是「按住说话」单行条，且底栏不遮输入条（无安全区档）', async ({ page }) => {
    await seedAuth(page)
    await stubBackend(page)
    await page.goto(CHAT_PAGE)

    const geometry = await expectInputBarGeometry(page, 0)
    // 无安全区档的构造性读数：底栏高 = Taro 条高，且贴视口底边
    expect(Math.abs(geometry.barHeight - TABBAR_BASE_HEIGHT)).toBeLessThanOrEqual(1)
    expect(Math.abs(geometry.barBottom - geometry.viewportHeight)).toBeLessThanOrEqual(1)
    expect(Math.abs(geometry.chatPagePaddingBottom - TABBAR_BASE_HEIGHT)).toBeLessThanOrEqual(1)

    await page.screenshot({ path: 'test-results/bmini/6596-chat-input-bar.png', fullPage: false })
  })

  test('🔴 安全区 34（iPhone home indicator）：底栏实用高 84、输入条不被压', async ({ page }) => {
    if (!(await overrideSafeArea(page, IPHONE_SAFE_BOTTOM))) {
      test.skip(true, '当前 Chrome 不支持 CDP Emulation.setSafeAreaInsetsOverride ⇒ 本档未跑（盒模型复算见 tabbar-content-inset.test.ts）')
    }
    await seedAuth(page)
    await stubBackend(page)
    await page.goto(CHAT_PAGE)

    const geometry = await expectInputBarGeometry(page, IPHONE_SAFE_BOTTOM)
    const expectedBarHeight = TABBAR_BASE_HEIGHT + IPHONE_SAFE_BOTTOM
    // 判据 5：底栏**实用高** = 50 + 34（content-box 会把 padding 再加一遍 ⇒ 118）
    expect(Math.abs(geometry.barHeight - expectedBarHeight)).toBeLessThanOrEqual(1)
    // 底栏仍贴视口底边（安全区被条覆盖，不是把条抬起来）
    expect(Math.abs(geometry.barBottom - geometry.viewportHeight)).toBeLessThanOrEqual(1)
    // 页面预留与底栏实用高逐值相等（`.chat-page` 的 padding-bottom）
    expect(Math.abs(geometry.chatPagePaddingBottom - expectedBarHeight)).toBeLessThanOrEqual(1)

    await page.screenshot({ path: 'test-results/bmini/7252-chat-input-bar-safe-area.png', fullPage: false })
  })
})
