// case_ids: OR-001, DF-002, UI-014, UI-016, UI-044, ST-011
/**
 * 小布 H5 视觉回归 — 无会话 UX + 主页（推荐胶囊 + 六格等权）+ 订单卡片
 *
 * 目的：验证 C 端 mini-app 渲染效果（用户直接看到的 UI），
 * 弥补 API 层验收覆盖不到的视觉/布局回归。
 *
 * 运行前提：mini-app 已 build:h5（dist/ 为 H5 产物），
 * 用静态服务器提供 dist/（见 playwright.xiaobu.config.ts webServer）。
 *
 * Mock 策略：拦截 API 返回固定数据，保证视觉断言确定性（不依赖真实 LLM/后端）。
 *
 * UI-014: 快捷入口六入口全保留，**六格等权**（2 列 × 3 行，算料报价不跨整行）
 * UI-016: 导航副标题企业名取自企业设置 tenantName（mock='米高窗帘'）
 * UI-044: 空态顶部横滑推荐胶囊（纯前端静态策划文案；文案方向 = 能力钩子 + 场景痛点）
 *
 * 2026-09-17 同步 M1-A（UI-044）：空态**不再展示商品推荐卡**（NewArrivals 组件与
 * 「新品推荐」区块已删除，推荐改由「推荐热门商品」快捷对话入口承载）
 * ⇒ 移除本 spec 对「新品推荐/遮光窗帘」的断言与 /chat/products/new-arrivals mock，
 *    并新增「商品推荐卡不得出现」的负向断言。
 *
 * 2026-09-18 同步 issue #4236（用户裁定「**回退为六格**，保留推荐胶囊」）：
 * · `#4199` 曾把 QuickActions 改成瑞幸式两栏分组（「你可以这样对我说：」+ 下单小助手/专属推荐师
 *   + 组头配色 + 右箭头），用户判为「反而改得更丑」并明确要回「上个 2 列 × 3 行的设计」
 *   ⇒ **回退为六格等权** + 原标题「您可以试试以下问题」；本 spec 对两栏分组结构做**负向断言**
 *   （防半回退 / 死代码）。
 * · **保留** RecommendChips（用户在原截图上圈出该区并明确「保留」），但**文案重定**为
 *   「能力钩子 + 场景痛点」5 条（每条指向不同能力：算料/知识/商品/性价比/物流）。
 * · **同一批**更新 `xiaobu-empty-welcome.png` 截图基线（空态画面再次改变 ⇒ darwin + linux 双平台）。
 * · ⚠️ 商品卡的负向判据保持**结构性**（`.new-arrivals*` 容器 + `¥` 价格），不用「遮光窗帘」子串代理
 *   —— 胶囊文案可能合法含商品词，子串代理会假红。
 *
 * 2026-09-18 同步卡型口径（#4016 P14 的「两个零发射点卡型」现**统一为「补发射点」**）：
 * · `payment` —— #4016 P14 当时工具层确实无数据源 ⇒ 缺触发机制 ⇒ 维持裁剪；**issue #4085 第 1 项**
 *   按用户 2026-09-18 裁定（与 `production_progress` 同款）**补发射点**：新增 C 端只读工具
 *   `payment_qrcode_query`（返回的 `data` 即卡载荷 —— `payment_qrcodes.wechat/alipay`
 *   各含精简字段 image_url/payee_name；数据源复用 `GET /api/admin/agent/payment-qrcodes`）
 *   → 后端 `_detect_card_type` 映射 `payment` → C 端恢复 `case 'payment'`
 *   ⇒ 本 spec 断言它**真渲染**（收款码内容 + 无码空态），**不再**落「消息内容暂不支持预览」占位。
 * · `production_progress` —— `production_progress_query` 工具存在且返回的正是卡载荷 ⇒ 属**接线漏一行**，
 *   用户 2026-09-18 裁定「**补发射点**」⇒ 后端补映射、三端恢复渲染分支，本 spec 断言它**真渲染**。
 * · 3 对别名 + `knowledge(_result)` **仍维持裁剪**（后端至今无发射点）。
 * （issue #4003 的教训：**砍/加卡片必须同批同步视觉 spec**，否则 spec 与实现分叉持续红 ——
 *   #4085 正是被这条红项抓出来的：旧断言写「payment 维持裁剪」，与「已放行」的实现相反。）
 */

import { test, expect } from '../../fixtures'

// ═══════════════════════════════════════════════════════════════
// Mock 数据
// ═══════════════════════════════════════════════════════════════

const MOCK_SESSION = {
  id: 'sess-vr-001',
  session_id: 'sess-vr-001',
  title: '视觉回归会话',
  status: 'active',
  customer_name: '视觉测试用户',
  last_message: '',
  created_at: '2026-06-20T10:00:00Z',
  updated_at: '2026-06-20T10:00:00Z',
}

/** 订单卡片 mock（OrderCard 渲染依据：order 类型卡片） */
const MOCK_ORDER_CARD = {
  type: 'order',
  data: {
    orders: [
      {
        order_no: 'ORD-20260601-001',
        status: 'shipped',
        status_text: '已发货',
        total_amount: 299.5,
        items: [{ product_name: '遮光窗帘', quantity: 2, amount: 199 }],
        created_at: '2026-06-01T10:00:00Z',
      },
    ],
  },
}

/** 收款码卡 mock（#4085 第 1 项「补发射点」后真可达 ⇒ 应**真渲染**）。
 *
 * 载荷形状 = C 端只读工具 `payment_qrcode_query` 的 `data`（`payment_qrcodes.wechat/alipay`
 * 各含精简字段 image_url/payee_name）—— 与后端单测 `tests/test_payment_qrcode_query.py`
 * 的冻结契约样例同源；旧 mock（顶层 order_no/amount/payee_name）**不是**真实载荷形状。
 */
const MOCK_PAYMENT_CARD = {
  type: 'payment',
  data: {
    payment_qrcodes: {
      wechat: {
        payment_type: 'wechat',
        image_url: 'https://img.migao.test/w.png',
        payee_name: '亿家纺织',
      },
      alipay: {
        payment_type: 'alipay',
        image_url: 'https://img.migao.test/a.png',
        payee_name: '亿家纺织',
      },
    },
  },
}

/** 商家未配收款码时的同卡型载荷：**空对象是合法答案**（工具 success=true）⇒ 卡片走空态。
 *
 * 真值：评测栈种子（tests/agent_eval/fixtures/*.sql、docs/deployment/demo-seed.sql）
 * 里 `tenant_payment_qrcodes` 零行 —— 空态才是该环境下的真实形态（同 ST-012 的口径）。
 */
const MOCK_PAYMENT_CARD_EMPTY = { type: 'payment', data: { payment_qrcodes: {} } }

/** 生产进度卡 mock（#4016 P14「补发射点」后真可达 ⇒ 应**真渲染**） */
const MOCK_PRODUCTION_PROGRESS_CARD = {
  type: 'production_progress',
  data: {
    order_no: 'CSO260915-02615',
    status: 'producing',
    progress_percent: 40,
    current_operation: '韩褶',
    pending_operations: ['韩褶', '定型', '打包'],
    expected_delivery_date: '2026-09-25',
  },
}

// ═══════════════════════════════════════════════════════════════
// Mock 设置
// ═══════════════════════════════════════════════════════════════

async function setupMocks(page: import('@playwright/test').Page) {
  // 注入测试 token（绕过 checkAuth→login 链路，直接进入 ensureLatestSession 续聊）
  // 注意：Taro H5 getStorageSync 只认 {"data": <value>} 格式（由 Taro.setStorage 写入）；
  // token 需为三段式 JWT 且无 exp（checkTokenValidity 无 exp 视为有效）
  await page.addInitScript(() => {
    const b64 = (s: string) => btoa(unescape(encodeURIComponent(s)))
    const fakeJwt = `${b64('{"alg":"none","typ":"JWT"}' as any)}.${b64('{"userId":"u-visual"}' as any)}.sig`
    localStorage.setItem('auth_token', JSON.stringify({ data: fakeJwt }))
    // auth_user 的形状 = 后端登录响应 data.user 的 JSON 原样（camelCase，见 mini-app
    // src/types 的 `User`）：租户 ID 键名是 `tenantId`，生产从不产生 `tenant_id`
    // （下一行的 `tenant_id` 是 Taro storage 键，与 user 对象字段无关，勿混同）
    localStorage.setItem('auth_user', JSON.stringify({ data: JSON.stringify({ id: 'u-visual', nickname: '视觉测试', avatar: null, tenantId: 1, tenantName: '米高窗帘' }) }))
    localStorage.setItem('tenant_id', JSON.stringify({ data: '1' }))
  })

  // 无会话 UX：latest 返回会话（续聊）
  await page.route('**/api/chat/sessions/latest', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: { session: MOCK_SESSION } }),
    })
  })
  // 会话历史为空（空态欢迎屏 → 展示新品推荐）
  await page.route('**/api/chat/history/*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: { items: [] } }),
    })
  })
  // M1-A（issue #3978）：空态已移除商品推荐卡 → 不再 mock /chat/products/new-arrivals
}

// ═══════════════════════════════════════════════════════════════
// 测试
// ═══════════════════════════════════════════════════════════════

test.describe('小布 H5 视觉回归', () => {
  test('空态欢迎屏：横滑推荐胶囊 + 六格等权入口（无商品推荐卡）', async ({ page }) => {
    await setupMocks(page)
    await page.goto('/#/pages/chat/index/index')

    // 品牌区（导航栏标题）
    await expect(page.locator('.chat-page__navbar-name')).toBeVisible()
    // UI-016：副标题企业名来自企业设置（mock tenantName='米高窗帘'），非硬编码默认值
    await expect(page.getByText('米高窗帘 · 智能购物助手')).toBeVisible()

    // UI-044（issue #4236 定稿文案）：顶部横滑推荐胶囊 —— 纯前端静态策划文案
    // 文案方向 = 能力钩子 + 场景痛点（每条指向不同能力）
    await expect(page.locator('.recommend-chips__chip')).toHaveCount(5)
    await expect(page.getByText('报个尺寸，我算你要几米布')).toBeVisible()
    await expect(page.getByText('客厅西晒？先看遮光率')).toBeVisible()

    // UI-014（issue #4236 回退）：六格等权（2 列 × 3 行），原标题「您可以试试以下问题」
    await expect(page.getByText('您可以试试以下问题')).toBeVisible()
    await expect(page.locator('.quick-actions__item')).toHaveCount(6)
    // 两栏分组结构（#4209）已按用户裁定撤下 —— 负向断言防止半回退/死代码
    await expect(page.locator('.quick-actions__group')).toHaveCount(0)
    await expect(page.locator('.quick-actions__row')).toHaveCount(0)
    await expect(page.getByText('下单小助手')).toHaveCount(0)
    await expect(page.getByText('专属推荐师')).toHaveCount(0)
    // UI-014：六入口能力面不收缩（回退前后逐个仍在）
    for (const label of ['算料报价', '推荐热门商品', '查订单', '找产品', '售后咨询', '查物流']) {
      await expect(page.getByText(label, { exact: true })).toBeVisible()
    }
    // 无「会话」tab（2 tab：对话/我的）
    await expect(page.getByText('会话', { exact: true })).toHaveCount(0)

    // UI-044：空态**不得**出现商品推荐卡。判据是**结构性**的 ——
    // 「遮光窗帘」子串代理已不可用（推荐胶囊文案可能合法含该词），
    // 故直接断言商品卡容器 / 商品图 / 价格三者都不存在。
    await expect(page.locator('.new-arrivals')).toHaveCount(0)
    await expect(page.locator('.new-arrivals__card')).toHaveCount(0)
    await expect(page.getByText(/新品推荐/)).toHaveCount(0)
    await expect(page.getByText('¥')).toHaveCount(0)

    // 视觉基线
    await expect(page).toHaveScreenshot('xiaobu-empty-welcome.png', {
      maxDiffPixelRatio: 0.02,
    })
  })

  test('推荐胶囊点击唤起对话（横滑入口，纯前端文案）', async ({ page }) => {
    await setupMocks(page)
    await page.goto('/#/pages/chat/index/index')

    // UI-044：点胶囊 = 发送对应 prompt 进对话（与快捷入口同语义）
    const chip = page.getByText('报个尺寸，我算你要几米布')
    await expect(chip).toBeVisible()
    await chip.click()
    await expect(page.getByText('帮我算一下窗帘用料和价格')).toBeVisible()
  })

  test('快捷入口「推荐热门商品」点击唤起对话（替代已移除的商品卡入口）', async ({ page }) => {
    await setupMocks(page)
    await page.goto('/#/pages/chat/index/index')

    // UI-044：推荐能力由快捷对话入口承载 —— 点击后应发送推荐 prompt（用户气泡可见）
    const entry = page.getByText('推荐热门商品', { exact: true })
    await expect(entry).toBeVisible()
    await entry.click()
    await expect(page.getByText('推荐一下热门商品')).toBeVisible()
  })

  test('对话页无「会话列表」入口（2 tab 结构）', async ({ page }) => {
    await setupMocks(page)
    await page.goto('/#/pages/chat/index/index')
    // tabBar 只应有「对话」和「我的」
    await expect(page.getByText('对话', { exact: true })).toBeVisible()
    await expect(page.getByText('我的', { exact: true })).toBeVisible()
    await expect(page.getByText('会话', { exact: true })).toHaveCount(0)
  })

  test('订单卡片渲染（OrderCard 视觉验收）', async ({ page }) => {
    await setupMocks(page)
    // 等待 latest 请求完成（会话建立 → currentSessionId 生效 → input 可用）
    const latestDone = page.waitForResponse(
      (r) => r.url().includes('/api/chat/sessions/latest') && r.status() === 200,
    )
    await page.goto('/#/pages/chat/index/index')
    await latestDone
    await expect(page.locator('.chat-page__navbar-name')).toBeVisible()

    // 等待会话就绪（latest mock 返回 session → ensureLatestSession 建立 currentSessionId → input 可用）
    const input = page.locator('input, textarea').first()
    await expect(input).toBeEnabled({ timeout: 10_000 })

    // 注册订单卡片 SSE mock（发消息时才被请求）
    // 注意：X-Client-Type 自定义头会触发浏览器 CORS preflight（OPTIONS），需一并 mock
    await page.route('**/api/chat/send', async (route) => {
      const method = route.request().method()
      if (method === 'OPTIONS') {
        await route.fulfill({
          status: 204,
          headers: {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type, X-Client-Type, Authorization',
            'Access-Control-Allow-Methods': 'POST, OPTIONS',
          },
        })
        return
      }
      const card = JSON.stringify(MOCK_ORDER_CARD)
      const done = JSON.stringify({ session_id: 'sess-vr-001', message_id: 'm1' })
      // 标准 SSE 格式：每个事件以空行分隔（Taro 按行解析 event:/data:）
      const body = [
        `event: card\ndata: ${card}\n`,
        `event: done\ndata: ${done}\n`,
      ].join('\n')
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        headers: {
          'Content-Type': 'text/event-stream',
          'Cache-Control': 'no-cache',
          'Access-Control-Allow-Origin': '*',
        },
        body,
      })
    })

    // 发消息触发订单卡片渲染
    await input.fill('查我的订单')
    await input.press('Enter')

    // 订单号 + 状态 + 金额可见
    await expect(page.getByText(/ORD-20260601-001/)).toBeVisible()
    await expect(page.getByText('已发货')).toBeVisible()
    await expect(page.getByText(/299\.50/)).toBeVisible()
    // 视觉基线（订单卡片样式）
    await expect(page).toHaveScreenshot('xiaobu-order-card.png', {
      maxDiffPixelRatio: 0.02,
    })
  })

  test('收款码卡真渲染（#4085 第 1 项「补发射点」：payment 卡型已放行，C 端不再落占位）', async ({ page }) => {
    await setupMocks(page)
    const latestDone = page.waitForResponse(
      (r) => r.url().includes('/api/chat/sessions/latest') && r.status() === 200,
    )
    await page.goto('/#/pages/chat/index/index')
    await latestDone
    await expect(page.locator('.chat-page__navbar-name')).toBeVisible()

    const input = page.locator('input, textarea').first()
    await expect(input).toBeEnabled({ timeout: 10_000 })

    await page.route('**/api/chat/send', async (route) => {
      if (route.request().method() === 'OPTIONS') {
        await route.fulfill({
          status: 204,
          headers: {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type, X-Client-Type, Authorization',
            'Access-Control-Allow-Methods': 'POST, OPTIONS',
          },
        })
        return
      }
      const body = [
        `event: card\ndata: ${JSON.stringify(MOCK_PAYMENT_CARD)}\n`,
        `event: done\ndata: ${JSON.stringify({ session_id: 'sess-vr-001', message_id: 'm2' })}\n`,
      ].join('\n')
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        headers: {
          'Content-Type': 'text/event-stream',
          'Cache-Control': 'no-cache',
          'Access-Control-Allow-Origin': '*',
        },
        body,
      })
    })

    await input.fill('怎么付款')
    await input.press('Enter')

    // **真渲染**（新真值）：卡片标题 + 微信/支付宝切换 + 收款方 + 二清提示可见
    await expect(page.getByText(/扫码支付/).first()).toBeVisible()
    await expect(page.getByText('微信', { exact: true })).toBeVisible()
    await expect(page.getByText('支付宝', { exact: true })).toBeVisible()
    await expect(page.getByText(/亿家纺织/).first()).toBeVisible()
    await expect(page.getByText(/款项直接支付给商家/).first()).toBeVisible()
    // 不再落「暂不支持预览」占位，也不泄漏内部卡型名
    await expect(page.getByText('📎 消息内容暂不支持预览')).toHaveCount(0)
    await expect(page.getByText(/payment/)).toHaveCount(0)
  })

  test('收款码卡无码时走空态（商家未设码 = 合法答案，不落占位）', async ({ page }) => {
    await setupMocks(page)
    // 卡片在载荷无码时自取 /chat/payment-qrcodes（issue #3990）：mock 成空 ⇒ 确定性走空态
    await page.route('**/api/chat/payment-qrcodes', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, data: {} }),
      })
    })
    const latestDone = page.waitForResponse(
      (r) => r.url().includes('/api/chat/sessions/latest') && r.status() === 200,
    )
    await page.goto('/#/pages/chat/index/index')
    await latestDone
    await expect(page.locator('.chat-page__navbar-name')).toBeVisible()

    const input = page.locator('input, textarea').first()
    await expect(input).toBeEnabled({ timeout: 10_000 })

    await page.route('**/api/chat/send', async (route) => {
      if (route.request().method() === 'OPTIONS') {
        await route.fulfill({
          status: 204,
          headers: {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type, X-Client-Type, Authorization',
            'Access-Control-Allow-Methods': 'POST, OPTIONS',
          },
        })
        return
      }
      const body = [
        `event: card\ndata: ${JSON.stringify(MOCK_PAYMENT_CARD_EMPTY)}\n`,
        `event: done\ndata: ${JSON.stringify({ session_id: 'sess-vr-001', message_id: 'm2b' })}\n`,
      ].join('\n')
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        headers: {
          'Content-Type': 'text/event-stream',
          'Cache-Control': 'no-cache',
          'Access-Control-Allow-Origin': '*',
        },
        body,
      })
    })

    await input.fill('怎么付款')
    await input.press('Enter')

    // 空态提示可见（ST-011「无收款码时展示降级提示」），且**不**落占位
    await expect(page.getByText(/暂未设置收款码/).first()).toBeVisible()
    await expect(page.getByText('📎 消息内容暂不支持预览')).toHaveCount(0)
  })

  test('生产进度卡真渲染（#4016 P14「补发射点」：后端已能下发，C 端不再落占位）', async ({ page }) => {
    await setupMocks(page)
    const latestDone = page.waitForResponse(
      (r) => r.url().includes('/api/chat/sessions/latest') && r.status() === 200,
    )
    await page.goto('/#/pages/chat/index/index')
    await latestDone
    await expect(page.locator('.chat-page__navbar-name')).toBeVisible()

    const input = page.locator('input, textarea').first()
    await expect(input).toBeEnabled({ timeout: 10_000 })

    await page.route('**/api/chat/send', async (route) => {
      if (route.request().method() === 'OPTIONS') {
        await route.fulfill({
          status: 204,
          headers: {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type, X-Client-Type, Authorization',
            'Access-Control-Allow-Methods': 'POST, OPTIONS',
          },
        })
        return
      }
      const body = [
        `event: card\ndata: ${JSON.stringify(MOCK_PRODUCTION_PROGRESS_CARD)}\n`,
        `event: done\ndata: ${JSON.stringify({ session_id: 'sess-vr-001', message_id: 'm3' })}\n`,
      ].join('\n')
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        headers: {
          'Content-Type': 'text/event-stream',
          'Cache-Control': 'no-cache',
          'Access-Control-Allow-Origin': '*',
        },
        body,
      })
    })

    await input.fill('我的订单做到哪道工序了')
    await input.press('Enter')

    // **真渲染**：进度/当前工序/预计交付可见，且**不再**落占位
    await expect(page.getByText('生产进度')).toBeVisible()
    await expect(page.getByText('40%')).toBeVisible()
    await expect(page.getByText('当前工序：韩褶')).toBeVisible()
    await expect(page.getByText('预计交付 2026-09-25')).toBeVisible()
    await expect(page.getByText('📎 消息内容暂不支持预览')).toHaveCount(0)
  })
})
