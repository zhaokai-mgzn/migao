// @vitest-environment jsdom
// case_ids: UI-102
/**
 * `src/components/chat/CustomerPanel.tsx` —— issue #7007「冷色收口到暖色 token」的**实例判据**。
 *
 * ## 为什么是 `.test.ts`（不是 `.tsx`）
 *
 * `docs/testing/mibao-verification-cases.md` / ticket #7007 的闸门按**精确路径**
 * `frontend/admin-web/tests/unit/components/CustomerPanel.test.ts` 检查存在性
 * ⇒ 扩展名必须是 `.ts`；而 esbuild 的 ts loader **不解析 JSX** ⇒ 本文件一律用
 * `React.createElement`（同族先例：`tests/unit/pages/after-sales-detail.test.tsx` 的
 * `React.createElement('span', {...}, label)`）。
 *
 * ## 被测组件的行为契约（逐条对源码，`src/components/chat/CustomerPanel.tsx`）
 *
 * | 契约 | 源码处 | 本文件判据 |
 * |---|---|---|
 * | 无 `currentSessionId` ⇒ 整个面板不渲染（`return null`） | L37 | `✗ 无当前会话 ⇒ 面板整体不渲染` |
 * | 初始展开态 = `w-[280px]` 侧栏 + `<h3>客户信息</h3>` | L54 / L57 | `✓ 初始展开态…` |
 * | 点 `title="收起"` ⇒ 只留折叠条（`title="展开客户信息"` + `flex-shrink-0 border-l border-neutral-200 bg-white`），再点回展开态 | L39-51 / L58-64 | `✓ 收起 / 展开往返` |
 * | `sessions.find(s => s.session_id === currentSessionId)` 决定 `currentSession`；命中 `active` ⇒ 「在线中」`green-*`，未命中/非 active ⇒ 「已结束」`neutral-*` | L26-28 / L92-99 | `✓ 会话状态徽标…` |
 * | 复制按钮只在有会话时渲染，点它把 `currentSessionId` 写进剪贴板并切 `Check` 图标 | L31-35 / L123-129 | `✗ 无会话时无复制按钮…` + `✓ 点复制…` |
 * | `RecentOrder` 的 `statusMap` 六态**暖色 token**（冷色收口的主判据） | L196-204 | `RecentOrder 六态状态色逐字收口暖色 token（源码级）` |
 * | `RecentOrder` 的可达性（当前**不可达**，如实登记） | L24 / L150-166 | `RecentOrder 当前不可达…（如实登记，不是遍历断言）` |
 *
 * ## 断言必须「会红」（红证）
 *
 * 每条判据的红证写在其 `it` 内/上（把哪个类名 / 哪个分支改掉会让它当场红）；
 * **禁止**凑数断言（`not.toBeNull()` / 裸 `toBeTruthy()` / 空 pass）—— 本仓 CI
 * `growth_gate.find_weak_asserts` / 新增文件弱断言锚点会对新增测试文件 fail-closed。
 *
 * ## 断言类名 ≠ 断言像素（边界，照实登记）
 *
 * jsdom **不加载 Tailwind**（无 `@tailwind` 产物）⇒ 本文件断言的是**类名字面量**，
 * 不是渲染出来的颜色。「好不好看」仍由 `migao-dev-flow` §15.7 真机读图 + 人裁定；
 * 本文件只保证「**这一处没退回另一个产品的配色**」。
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

// ─── mock 状态（`vi.hoisted` ⇒ `vi.mock` 工厂提升后仍可用，同族：ChatArea.test.tsx）───

const h = vi.hoisted(() => ({
  useChatStore: null as unknown as () => Record<string, unknown>,
  clipboard: null as unknown as { writeText: (t: string) => Promise<void> },
}))

vi.mock('@/store/chat', () => ({
  useChatStore: () => h.useChatStore(),
}))

// lucide-react：仓内既有 helper（不逐个列图标名 —— 列全了会在组件新增图标时炸 mock 维护问题）
vi.mock('lucide-react', async (importOriginal) =>
  (await import('../helpers/lucide-mock')).lucideMock((await importOriginal()) as Record<string, unknown>))

import CustomerPanel from '@/components/chat/CustomerPanel'

// ─── 最小 chat store 形状（组件是**整体调用** `useChatStore()`，不传 selector）───

interface FakeSession {
  session_id: string
  status: 'active' | 'closed'
}

function chatState(currentSessionId: string | null, sessions: FakeSession[] = []) {
  h.useChatStore = () => ({ currentSessionId, sessions })
}

/** 渲染入口：`.ts` 文件**不能**写 JSX ⇒ 一律走 `React.createElement` */
function renderPanel() {
  return render(React.createElement(CustomerPanel))
}

const SESSION_ID = 'sess-0123456789abcdef'

beforeEach(() => {
  h.clipboard = { writeText: vi.fn().mockResolvedValue(undefined) }
  Object.defineProperty(navigator, 'clipboard', {
    value: h.clipboard,
    writable: true,
    configurable: true,
  })
})

// ─── 一、无当前会话 ⇒ 面板整体不渲染（源码 L37：`if (!currentSessionId) return null`）───

describe('CustomerPanel —— 无当前会话（源码 L37 的早退分支）', () => {
  it('✗ 无当前会话 ⇒ 面板整体不渲染（连折叠条都没有）', () => {
    // 判据（源码 L37 `if (!currentSessionId) return null`）：
    //   无会话时不得留下任何面板残影（侧栏 / 折叠条 / 头部）。
    // 红证：把 L37 那行早退删掉（或改成 `if (!collapsed)`），本判据当场红
    //   —— `container.firstChild` 会变成展开态侧栏、`getByTitle('收起')` 会命中。
    chatState(null, [{ session_id: SESSION_ID, status: 'active' }])

    const { container } = renderPanel()

    expect(container.firstChild).toBeNull()
    expect(screen.queryByTitle('收起')).toBeNull()
    expect(screen.queryByTitle('展开客户信息')).toBeNull()
    expect(screen.queryByText('客户信息')).toBeNull()
  })

  it('✗ 无当前会话 ⇒ 无复制按钮，也不存在「暂无订单数据」区块（早退发生在任何内容渲染之前）', () => {
    // 判据（源码 L37）：早退在**整个** return 之前 ⇒ 复制按钮（L123）与最近订单区块（L146）都不可达。
    // 红证：把早退挪到 `collapsed` 分支之后（例如只对展开态生效），本判据当场红
    //   —— 折叠分支会渲染出按钮。
    chatState(null)

    renderPanel()

    expect(screen.queryByTitle('复制会话ID')).toBeNull()
    expect(screen.queryByText('暂无订单数据')).toBeNull()
  })
})

// ─── 二、折叠 / 展开往返（源码 L39-51 / L58-64）───

describe('CustomerPanel —— 收起 / 展开往返', () => {
  it('✓ 初始展开态：280px 侧栏 + `<h3>客户信息</h3>` + 收起按钮（标题逐字「收起」）', () => {
    // 判据（源码 L54 / L57 / L58-64）：初始 `collapsed === false` ⇒ 展开态，
    //   侧栏宽度类逐字 `w-[280px]`、头部标题逐字「客户信息」、收起按钮 `title="收起"`。
    // 红证：把 L54 的 `w-[280px]` 改掉（或 L57 的标题改字）、把 L61 的 `title="收起"` 改掉 ⇒ 本判据当场红。
    chatState(SESSION_ID, [{ session_id: SESSION_ID, status: 'active' }])

    const { container } = renderPanel()
    const panel = container.firstChild as HTMLElement

    expect(panel.className).toContain('w-[280px]')
    expect(panel.className).toContain('flex-shrink-0')
    expect(panel.className).toContain('border-l')
    expect(panel.className).toContain('border-neutral-200')
    expect(panel.className).toContain('bg-white')

    expect(screen.getByRole('heading', { level: 3 }).textContent).toBe('客户信息')
    expect(screen.getByTitle('收起')).toBeTruthy()
    // 展开态**没有**折叠条（两态互斥；否则「收起」是空操作）
    expect(screen.queryByTitle('展开客户信息')).toBeNull()
  })

  it('✓ 点「收起」⇒ 只剩折叠条（`flex-shrink-0 border-l border-neutral-200 bg-white`），再点回展开态', () => {
    // 判据（源码 L39-51 / L58-64）：
    //   ① 点 `title="收起"` ⇒ 渲染折叠条：`title="展开客户信息"`、类名**恰好**
    //      `flex-shrink-0 border-l border-neutral-200 bg-white`（L41，逐字），280px 侧栏消失；
    //   ② 点折叠条 ⇒ 回到展开态（`w-[280px]` 与 `<h3>客户信息</h3>` 回来）。
    // 红证：把 L41 的类名改成 `bg-neutral-50`（或删掉 `border-l`）⇒ ① 当场红；
    //   把 L43 的 `onClick={() => setCollapsed(false)}` 去掉 ⇒ ② 当场红。
    chatState(SESSION_ID, [{ session_id: SESSION_ID, status: 'active' }])

    const { container } = renderPanel()
    fireEvent.click(screen.getByTitle('收起'))

    const collapsedBar = container.firstChild as HTMLElement
    expect(collapsedBar.className).toBe('flex-shrink-0 border-l border-neutral-200 bg-white')
    expect(screen.queryByRole('heading', { level: 3 })).toBeNull()
    expect(screen.getByTitle('展开客户信息')).toBeTruthy()

    fireEvent.click(screen.getByTitle('展开客户信息'))

    const expanded = container.firstChild as HTMLElement
    expect(expanded.className).toContain('w-[280px]')
    expect(screen.getByRole('heading', { level: 3 }).textContent).toBe('客户信息')
    expect(screen.queryByTitle('展开客户信息')).toBeNull()
  })
})

// ─── 三、会话状态徽标：`sessions.find(...)` 的命中 / 未命中（源码 L26-28 / L92-99）───

describe('CustomerPanel —— 会话状态徽标（源码 L26-28 的 find + L92-99 的两分支）', () => {
  it('✓ 会话 status 为 active ⇒ 徽标逐字「在线中」且用 `green-*` 语义色', () => {
    // 判据（源码 L94-98）：命中 currentSession 且 `status === 'active'` ⇒ 文案「在线中」，
    //   类名同时含 `bg-green-50` / `text-green-700` / `border-green-200`（语义成功色，**不是**冷色族）。
    // 红证：把 L94 的条件改成 `status === 'closed'`（或把 `'在线中'` 改字）⇒ 本判据当场红。
    chatState(SESSION_ID, [{ session_id: SESSION_ID, status: 'active' }])

    renderPanel()

    const badge = screen.getByText('在线中')
    expect(badge.className).toContain('bg-green-50')
    expect(badge.className).toContain('text-green-700')
    expect(badge.className).toContain('border-green-200')
    // 两态互斥：active 时不得同时出现「已结束」
    expect(screen.queryByText('已结束')).toBeNull()
  })

  it('✓ `sessions.find(...)` 未命中（currentSessionId 不在 sessions 里）⇒ 回落到「已结束」+ `neutral-*`，**不抛不崩**', () => {
    // 判据（源码 L26-28 `sessions.find(...)` 可返回 undefined；L94-98 用可选链读 `currentSession?.status`）：
    //   未命中 ⇒ 走 else 分支（「已结束」+ `neutral-*`），面板其余部分照常渲染。
    //   ⚠️ 这一条是**据实断言**（读了源码确认走 else，不是猜的），不是「找不到也要有内容」的期望。
    // 红证：把 L94 的三元条件改成 `currentSession !== undefined` ⇒ 本判据当场红（未命中会变「在线中」）。
    chatState('sess-not-in-list', [{ session_id: SESSION_ID, status: 'active' }])

    renderPanel()

    const badge = screen.getByText('已结束')
    expect(badge.className).toContain('bg-neutral-50')
    expect(badge.className).toContain('text-neutral-500')
    expect(badge.className).toContain('border-neutral-200')
    expect(screen.queryByText('在线中')).toBeNull()
    // 未命中时面板仍完整渲染（不是静默塌成空白）
    expect(screen.getByText('客户信息')).toBeTruthy()
  })

  it('✓ 命中但 status 为 closed ⇒ 同样走「已结束」分支（命中 ≠ 在线）', () => {
    // 判据（源码 L94-98）：分支条件是 `status === 'active'` 而**不是**「find 命中」⇒ closed 也必须读「已结束」。
    // 红证：把条件写成 `currentSession !== undefined ? … : …` ⇒ 本判据当场红（会渲染「在线中」）。
    chatState(SESSION_ID, [{ session_id: SESSION_ID, status: 'closed' }])

    renderPanel()

    expect(screen.getByText('已结束').className).toContain('bg-neutral-50')
    expect(screen.queryByText('在线中')).toBeNull()
  })
})

// ─── 四、复制会话 ID（源码 L31-35 / L123-129）───

describe('CustomerPanel —— 复制会话 ID（源码 L31-35）', () => {
  it('✓ 点复制按钮 ⇒ 把 `currentSessionId` 整串写进剪贴板，并把图标切成 `Check`', () => {
    // 判据（源码 L31-35 / L128）：`handleCopy` 先把 `currentSessionId` **原样**写入 clipboard，
    //   并置 `copied = true` ⇒ 按钮内图标由 `Copy` 换成 `Check`（`text-green-500`）。
    // 红证：把 L32 的 `navigator.clipboard.writeText(currentSessionId)` 改成写 `''`
    //   （或删掉 `setCopied(true)`）⇒ 本判据当场红。
    chatState(SESSION_ID, [{ session_id: SESSION_ID, status: 'active' }])

    renderPanel()
    fireEvent.click(screen.getByTitle('复制会话ID'))

    expect(h.clipboard.writeText).toHaveBeenCalledWith(SESSION_ID)
    expect(screen.getByTitle('复制会话ID').querySelector('.text-green-500')).toBeTruthy()
  })

  it('✓ 会话 ID 展示为前 14 位 + 省略号，且完整串挂在 `title` 上（L120-122）', () => {
    // 判据（源码 L120-122）：可见文本 = `currentSessionId.slice(0, 14) + '…'`，
    //   `title` 属性 = **完整** ID（不截断）—— 截断只是显示肽，不是数据丢失。
    // 红证：把 L121 的 `slice(0, 14)` 去掉（或把 L120 的 `title={currentSessionId}` 改成硬编码）⇒ 本判据当场红。
    chatState(SESSION_ID, [{ session_id: SESSION_ID, status: 'active' }])

    renderPanel()

    expect(screen.getByText(`${SESSION_ID.slice(0, 14)}…`)).toBeTruthy()
    expect(screen.getByTitle(SESSION_ID).textContent).toBe(`${SESSION_ID.slice(0, 14)}…`)
  })

  it('✓ 复制后的「已复制」态 2 秒后自动复位（源码 L34 的 setTimeout）', async () => {
    // 判据（源码 L33-34）：`setCopied(true)` 之后 `setTimeout(() => setCopied(false), 2000)`
    //   ⇒ 到点后图标必须回到 `Copy`（否则按钮永远显示「已复制」，用户以为复制失效）。
    // 红证：把 L34 的 `setTimeout(..., 2000)` 删掉（或把 `setCopied(false)` 去掉）⇒ 本判据当场红
    //   （`vi.getTimerCount()` 会是 0 / `.text-green-500` 仍在）。
    // 边界（照实登记）：本条钉的是「**存在**一个到点复位定时器」；具体 2000ms 这个数在本用例里
    //   由 `advanceTimersByTime(2000)` 隐含，改短/改长不会被本条判红（要钉时长需再断言 1999ms 时仍绿）。
    vi.useFakeTimers()
    try {
      chatState(SESSION_ID, [{ session_id: SESSION_ID, status: 'active' }])
      renderPanel()
      fireEvent.click(screen.getByTitle('复制会话ID'))
      expect(screen.getByTitle('复制会话ID').querySelector('.text-green-500')).toBeTruthy()

      expect(vi.getTimerCount()).toBe(1)
      // 用 `advanceTimersByTimeAsync` + `await`（本仓既有口径，见 SessionInsight.test.tsx）：
      // 它既推进假时钟、又冲刷 React 的更新队列。`act()` 包同步版也能过，但 async 版与仓内
      // 其它用例同形；实测同步版**与其它组件测试同批跑时会红**（读到上一帧 DOM），
      // 那正是「断言依赖未定义的时序」。
      // `await act(async () => …)`：既推进假时钟、又**冲刷 React 的提交**（async act 在回调
      // 结束后会 await 微任务队列）。实测三种写法在同一文件里只有这一种在同批跑时稳定：
      //   · 同步 `vi.advanceTimersByTime` ⇒ 单跑能过、与其它文件同批跑时红（读到上一帧 DOM）；
      //   · `await vi.advanceTimersByTimeAsync` ⇒ 同样红（它冲刷的是**定时器**队列，不是 React 提交）；
      //   · `await act(async () => …)` ⇒ 绿（本仓 `tests/unit/hooks/use-typewriter.test.tsx`
      //     用的是同步 `act()` 包推进，同一族口径）。
      await act(async () => {
        vi.advanceTimersByTime(2000)
      })

      expect(vi.getTimerCount()).toBe(0)
      expect(screen.getByTitle('复制会话ID').querySelector('.text-green-500')).toBeNull()
    } finally {
      vi.useRealTimers()
    }
  })
})

// ─── 五、最近订单区块：当前**只有空态可达**（源码 L24 / L150-166）───

describe('CustomerPanel —— 最近订单区块的现网可达面（源码 L24 / L150-166）', () => {
  it('✓ 无论 store 给什么会话数据，最近订单恒为空态「暂无订单数据」（实心内容分支当前不可达）', () => {
    // 判据（源码 L24 + L150）：`customerInfo` 由 `useState<ChatCustomerInfo | null>(null)` 取得，
    //   且**没有任何 setter 调用**（见下一条判据）⇒ L150 的条件恒假 ⇒ 只能渲染 L162-166 的空态。
    //   这一条是**可达面的据实断言**：它不假装订单卡片能渲染出来。
    // 红证：若将来有人接上 `customerInfo` 的数据源（setter + recentOrders），L150 条件可能为真
    //   ⇒ 本判据当场红 ⇒ 提醒把「六态暖色 token」从源码级判据升级为渲染级判据。
    chatState(SESSION_ID, [{ session_id: SESSION_ID, status: 'active' }])

    renderPanel()

    expect(screen.getByText('暂无订单数据')).toBeTruthy()
    // 订单卡片里的金额形态（`¥xx.xx`，源码 L157 / L215）此刻一个都不该有
    expect(screen.queryByText(/^¥\d/)).toBeNull()
  })
})

// ─── 六、冷色收口主判据：`RecentOrder.statusMap` 六态逐字暖色 token（源码 L196-204）───

/** 组件源码（源码级判据用；`process.cwd()` = 前端包目录 frontend/admin-web） */
const SOURCE_PATH = join(process.cwd(), 'src/components/chat/CustomerPanel.tsx')
const SOURCE = readFileSync(SOURCE_PATH, 'utf-8')

/** 裁掉 `//` 起的行尾注释与 `/* … *​/` 块注释：注释里的旧写法不是实现（本仓口径，见 warm-token-palette-guard） */
function stripComments(code: string): string {
  return code.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '')
}

const SOURCE_CODE = stripComments(SOURCE)
/** `statusMap` 字面量块（L196-203） */
const STATUS_MAP_BLOCK = SOURCE_CODE.match(/const statusMap[\s\S]*?\n {2}\}/)?.[0] ?? ''

/** 取某状态的 `{ label, className }` 条目源码 */
function statusEntry(status: string): string {
  return STATUS_MAP_BLOCK.match(new RegExp(`\\b${status}:\\s*\\{[^}]*\\}`))?.[0] ?? ''
}

/**
 * 「冷色收口」主判据。`issue #7007` 之前这六态的类名是
 * `confirmed → bg-blue-*` / `producing → bg-purple-*` / `shipped → bg-indigo-*`
 * ⇒ 它们在暖色底（`neutral-50 = #faf7f2`）旁边读起来像**另一个产品的颜色**。
 *
 * 映射依据（`frontend/admin-web/src/lib/status-chip.ts` 的既有语义约定 + `warm-token-palette-guard.test.ts`）：
 * `blue/sky/cyan → primary`、`indigo/purple/violet → accent`；`amber/green/neutral` 是语义色，**不动**。
 */
describe('CustomerPanel —— RecentOrder 六态状态色逐字收口暖色 token（issue #7007 实例判据）', () => {
  it('✓ confirmed 用 `primary-*`（改前 `blue-*`）—— 且全文不再出现冷色族字面量', () => {
    // 判据（源码 L198）：`confirmed` 的 className 逐字含 `bg-primary-50 text-primary-700 border-primary-200`。
    // 红证：把 L198 改回 `bg-blue-50 text-blue-700 border-blue-200` ⇒ 本判据**两条断言同时**当场红
    //   （既不再含 primary-*，又命中冷色族字面量 blue-*）。
    const entry = statusEntry('confirmed')
    expect(entry).toContain('label: \'已确认\'')
    expect(entry).toContain('bg-primary-50 text-primary-700 border-primary-200')

    // 冷色收口的面：整个组件（去注释后）不得再出现 `blue|indigo|purple|violet|sky|cyan|gray|slate|zinc|stone` 族工具类。
    expect(SOURCE_CODE).not.toMatch(
      /\b(?:bg|text|border|ring|from|via|to|divide|outline|shadow|decoration|accent|caret|fill|stroke)-(?:blue|sky|cyan|indigo|purple|violet|gray|slate|zinc|stone)-\d/,
    )
  })

  it('✓ producing 与 shipped 都收口到 `accent-*`（改前分别是 `purple-*` / `indigo-*`，颜色数 3 → 2）', () => {
    // 判据（源码 L199-200）：producing / shipped 的 className 逐字含
    //   `bg-accent-50 text-accent-700 border-accent-200`（=== 同一组 token）。
    // 红证：把 L199 改回 `bg-purple-50 …` 或把 L200 改回 `bg-indigo-50 …` ⇒ 本判据当场红
    //   （并且上一条 `not.toMatch` 冷色族也会红）。
    const producing = statusEntry('producing')
    const shipped = statusEntry('shipped')

    expect(producing).toContain('label: \'生产中\'')
    expect(producing).toContain('bg-accent-50 text-accent-700 border-accent-200')
    expect(shipped).toContain('label: \'已发货\'')
    expect(shipped).toContain('bg-accent-50 text-accent-700 border-accent-200')
  })

  it('✓ pending / completed / cancelled 三个语义色**保持不动**（amber / green / neutral，本轮不改造）', () => {
    // 判据（源码 L197 / L201 / L202）：这三态未被 #7007 触及，**不得**被顺手改成暖色 token：
    //   pending = `bg-amber-50 text-amber-700 border-amber-200`（待确认）
    //   completed = `bg-green-50 text-green-700 border-green-200`（已完成）
    //   cancelled = `bg-neutral-50 text-neutral-600 border-neutral-200`（已取消）
    // 红证：把 L197 的 `amber` 改成 `primary`（或 L201 的 `green` 改成 `accent`）⇒ 本判据当场红。
    expect(statusEntry('pending')).toContain('label: \'待确认\'')
    expect(statusEntry('pending')).toContain('bg-amber-50 text-amber-700 border-amber-200')
    expect(statusEntry('completed')).toContain('label: \'已完成\'')
    expect(statusEntry('completed')).toContain('bg-green-50 text-green-700 border-green-200')
    expect(statusEntry('cancelled')).toContain('label: \'已取消\'')
    expect(statusEntry('cancelled')).toContain('bg-neutral-50 text-neutral-600 border-neutral-200')
  })
})

// ─── 七、`RecentOrder` 的可达性（如实登记：当前**不可达**）───

describe('CustomerPanel —— RecentOrder 的可达性（如实登记 §19.1，不是遍历断言）', () => {
  it('✓ 现网数据管线上 `RecentOrder` 不可达：`customerInfo` 无数据源、`RecentOrder` 只有一处渲染点', () => {
    // ## 为什么这条判据存在
    //
    // 「六态暖色 token」最有价值的形态本是**渲染级**判据（渲染出六张订单卡片，逐张断言类名）。
    // 但读了源码后确认它在**当前组件里不可达**，因此**不**去 mock 组件内部实现细节硬造可达性
    // （那会让判据变成「测试自己的 mock 是对的」= 假绿）。两条结构性事实足以钉住「不可达」：
    //
    //   ① `customerInfo` 的初始值恒为 `null`，且**全组件没有任何 setter 调用**
    //      （源码 L24 `const [customerInfo] = useState<ChatCustomerInfo | null>(null)` ——
    //       解构里只有值、没有 setter）⇒ L150 的 `customerInfo?.recentOrders && …` 恒假；
    //   ② `<RecentOrder` 在全文件**只出现 1 次**（L153，位于那个恒假分支内，JSX 形态 `<RecentOrder … />`）
    //      ⇒ 没有第二条渲染路径。
    //
    // 红证：① 若有人把 L24 改成 `const [customerInfo, setCustomerInfo] = useState…`（= 真接上了数据源，
    //   解构出 setter，本判据第一条当场红）；② 若有人把 `<RecentOrder …/>` 搬到别处渲染
    //   （出现第 2 处），第二条当场红。**任一条红 ⇒ 说明渲染级判据现在写得了** ⇒
    //   把上一节（六态暖色 token）从源码级升级为「渲染 + 断言类名」的渲染级判据，并把本节删掉。
    expect(SOURCE_CODE).toContain('const [customerInfo] = useState<ChatCustomerInfo | null>(null)')
    expect(SOURCE_CODE).not.toMatch(/\bsetCustomerInfo\b/)

    const recentOrderRenderPoints = SOURCE_CODE.match(/<RecentOrder\b/g) ?? []
    expect(recentOrderRenderPoints).toHaveLength(1)
  })
})

// ─── 六、行内占位不得写成**事实性断言**（issue #8062）───

describe('CustomerPanel —— 行内字段占位（issue #8062 裁定为「非列表体空态」）', () => {
  it('✓ 电话 / 注册天数无数据 ⇒ 占位 `—`，不印「暂无」（那是在断言「客户没有」）', () => {
    // 判据（源码「基本信息」段）：`customerInfo` 随会话载荷下发且当前恒为 `null`
    //   （`useState(null)` 从未被赋值）⇒ 这两行**从来没有读过任何数据**，
    //   既不能说「客户没提供」也不能说「没读到」⇒ 占位必须是**不做断言**的 `—`。
    // 红证：把 `'—'` 改回 `'暂无'` ⇒ 本判据当场红（`queryByText('暂无')` 命中 2 处），
    //   且 `read-failure-empty-state-scan` 会把它重新判成「无失败锚的空态断言」（那条已删的台账条目回来）。
    chatState(SESSION_ID, [{ session_id: SESSION_ID, status: 'active' }])
    renderPanel()

    expect(screen.getByText('电话')).toBeTruthy()
    expect(screen.getAllByText('—')).toHaveLength(2)
    expect(screen.queryByText('暂无')).toBeNull()
  })
})
