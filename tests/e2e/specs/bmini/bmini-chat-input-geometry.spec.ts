// case_ids: BM-044
/**
 * B 端 H5「问黄金策」输入条的**几何判据**（issue #6596）
 *
 * ## 治的形态（用户真机截图 + 主会话独立探针读数）
 *
 * `MerchantTabBar` 是 `position: fixed; bottom: 0` 的**浮层**，而 `.chat-page` 是 `height: 100vh`
 * 且**没有为它留位** ⇒ 输入条被底栏压住。线上 BEFORE 读数（390×844，真 Chrome）：
 *
 * | 读数 | 修前（app.migaozn.com/b/） |
 * |---|---|
 * | `.chat-page` 高度 | **864px**（视口 844 ⇒ 高出 20px = 状态栏 `padding-top` 被 content-box 加在 100vh 之上） |
 * | `.message-input` 底边 | **864**（已在视口外） |
 * | `.merchant-tabbar` 顶边 | **794** ⇒ 被遮 **70px**（`COVERED`） |
 *
 * ## 判据（三条，全部是**几何数字**，不是「看着正常」）
 *
 * | # | 断言 | 回归时会怎么红 |
 * |---|---|---|
 * | 1 | 默认语音模式：`__hold` 在位（用户裁定「默认文字叫按住说话」） | 默认变成打字 ⇒ 红 |
 * | 2 | 🔴 `coveredPx = 输入条底边 − 底栏顶边 ≤ 0`（底栏不压输入条） | 撤掉 `.chat-page` 的预留 ⇒ 70px 重叠 ⇒ 红 |
 * | 3 | 🔴 `chatPageHeight ≤ viewportHeight`（整页不高于视口） | 去掉 `box-sizing: border-box` ⇒ 864 > 844 ⇒ 红 |
 *
 * ## 边界（照实登记，§19.1）
 *
 * - 本腿走**本地 H5 产物**（`playwright.bmini.config.ts` 自带产物新鲜度前置断言 + 静态服务），
 *   `/api/**` **桩掉**（只读、不产生真实写请求）⇒ 不连后端。
 * - Chromium 里 `env(safe-area-inset-bottom)` 恒 0 ⇒ 量到的是「无安全区」那一档；
 *   带安全区那一档（iPhone 真机 +34px）由同一算式 `.chat-page{padding-bottom: calc(50PX + env(...))}`
 *   构造性覆盖（形态判据见 `frontend/bmini-app/tests/chat-input-bar-layout.test.tsx`），
 *   真机读数另记（PR body 的未覆盖登记）。
 * - 🔴 本文件不许出现弱断言（fail-closed）。
 */
import { test, expect } from '@playwright/test'

const CHAT_PAGE = '/#/pages/chat/index/index'

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

test.describe('B 端 H5 输入条几何（issue #6596）', () => {
  test('默认是「按住说话」单行条，且底栏不遮输入条（coveredPx ≤ 0、整页不高于视口）', async ({
    page,
  }) => {
    await seedAuth(page)
    await stubBackend(page)

    await page.goto(CHAT_PAGE)

    // 判据 1：默认语音模式（用户裁定「默认文字叫按住说话」）
    await expect(page.locator('.message-input__hold')).toBeVisible()
    await expect(page.locator('.message-input__row')).toBeVisible()

    const geometry = await page.evaluate(() => {
      const input = document.querySelector('.message-input')
      const row = document.querySelector('.message-input__row')
      const bar = document.querySelector('.merchant-tabbar')
      const chatPage = document.querySelector('.chat-page')
      const toggle = document.querySelector('.message-input__mode-toggle')
      const center = document.querySelector('.message-input__center')
      const attach = document.querySelector('.message-input__attach')
      // 空草稿时 `__actions` 是空容器（0 高，是渲染条件不是缺陷）⇒ 用**添图键**当"第三个格子"
      if (!input || !bar || !chatPage || !row || !toggle || !center || !attach) return null
      const inputRect = input.getBoundingClientRect()
      const barRect = bar.getBoundingClientRect()
      const pageRect = chatPage.getBoundingClientRect()
      const toggleRect = toggle.getBoundingClientRect()
      const centerRect = center.getBoundingClientRect()
      const attachRect = attach.getBoundingClientRect()
      return {
        inputBottom: inputRect.bottom,
        barTop: barRect.top,
        chatPageHeight: pageRect.height,
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
    if (geometry === null) throw new Error('拿不到输入条 / 底栏 / 页面根节点 —— 页面白屏或未渲染？')

    console.log(
      `[6596 几何] 输入条底边=${geometry.inputBottom} 底栏顶边=${geometry.barTop} ` +
        `重叠=${geometry.inputBottom - geometry.barTop} 页面高=${geometry.chatPageHeight} ` +
        `视口高=${geometry.viewportHeight} 行高=${geometry.rowHeight} ` +
        `三格高=${geometry.toggleHeight}/${geometry.centerHeight}/${geometry.attachHeight}`,
    )

    // 判据 2：底栏不压输入条
    const overlap = geometry.inputBottom - geometry.barTop
    expect(overlap).toBeLessThanOrEqual(0)
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

    await page.screenshot({ path: 'test-results/bmini/6596-chat-input-bar.png', fullPage: false })
  })
})
