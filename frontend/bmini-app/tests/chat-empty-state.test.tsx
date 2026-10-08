// case_ids: BM-028
/**
 * B 端「问黄金策」空态契约 —— **不得混入 C 端 agent 的内容**（issue #5747）
 *
 * ## 治的形态
 *
 * B 端 agent 页（`src/pages/chat/index/index.tsx`）**照抄了 C 端元元主页的旧版本**：
 * 空态渲染 `NewArrivals`（商品卡，拉 **C 端端点** `/api/chat/products/new-arrivals`，
 * 提示「点一下问问元元」）⇒ 商家在 `/b/` 里看到的是**顾客端的入口与商品展示**。
 *
 * C 端（`frontend/mini-app`）早在 issue #3978 / #4236 就删掉了这块（判据 =
 * `tests/e2e/specs/xiaobu/xiaobu-h5.spec.ts` 的 `.new-arrivals` 为零 / `¥` 为零负向断言）。
 *
 * ## 两层判据
 *
 * 1. **行为层**（渲染出来是什么）：空态不得出现商品卡容器 / 价格符号 / 「新品推荐」文本 /
 *    C 端 agent 名（「元元」）；欢迎语是 B 端语义（商家经营助手），不是「专属智能购物助手」。
 * 2. **源码层（类级元守卫）**：B 端整个 `src/**` 不得再引用 C 端商品推荐端点
 *    （`new-arrivals`）；聊天面（`components/chat` / `pages/chat`）不得出现 C 端 agent 名
 *    ——「再抄一次 C 端页面」会**当场变红**，而不是等用户在小程序里看见。
 *
 * ⚠️ 边界（照实登记）：源码层只扫 `src/**` 的**代码**（块注释与整行 `//` 注释先剔除）——
 * 它管不住文档 / 注释里的引用，也不判「文案是否得体」（那是人读的事）。
 */
import React from 'react'
import fs from 'fs'
import path from 'path'
import { render, screen } from '@testing-library/react'

jest.mock('../src/store/authStore', () => ({
  useAuthStore: jest.fn((selector: any) =>
    typeof selector === 'function'
      ? selector({ user: { id: 'u1', nickname: '运营小王', tenantId: 1, tenantName: '词元通达', botName: null } })
      : { user: { id: 'u1', nickname: '运营小王', tenantId: 1, tenantName: '词元通达', botName: null } },
  ),
}))

import MessageList from '../src/components/chat/MessageList'
import TypingIndicator from '../src/components/chat/TypingIndicator'

const SRC_ROOT = path.resolve(__dirname, '../src')
/** C 端 agent（元元）的默认名 —— B 端默认「黄金策」，出现在 B 端聊天面即为串味 */
const C_END_AGENT_NAME = '元元'
/** C 端商品推荐端点（B 端消费它 = 把顾客端的商品展示搬进商家端） */
const C_END_PRODUCT_ENDPOINT = 'new-arrivals'
/**
 * C 端**顾客口吻**的快捷入口问句（issue #6468）：B 端入口曾逐字抄这几条，
 * 内容真值现在只在服务端（`backend/ai-agent-service/app/api/chat.py` 的 `QUICK_ACTIONS`）
 * ⇒ H5 代码里再出现它们 = 又抄了一份。
 */
const C_END_QUICK_PROMPTS = [
  '推荐一下热门窗帘产品',
  '帮我查一下物流',
  '我想咨询售后问题',
  '帮我算一下窗帘用料和价格',
]

function listSourceFiles(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) return listSourceFiles(full)
    return /\.(ts|tsx)$/.test(entry.name) ? [full] : []
  })
}

/** 剔除块注释与整行 `//` 注释后的**代码**（只看代码里有没有引用，注释里的说明不算） */
function codeOnly(file: string): string {
  return fs
    .readFileSync(file, 'utf-8')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .split('\n')
    .filter((line) => !line.trim().startsWith('//'))
    .join('\n')
}

/**
 * 空态里**渲染出来**的第二行文案（读渲染结果，不读源码 —— 判的是商家真看到的那句）
 *
 * 直接用 `textContent ?? ''`：元素缺失时下面 `toContain` 会给出「差在哪」的 diff，
 * 比再加一条「元素存在」的存在性断言更有信息量。
 */
function emptyStateCopy(): string {
  const { container } = render(<MessageList messages={[]} isStreaming={false} onInteract={jest.fn()} />)
  return container.querySelector('.message-list__empty-text')?.textContent ?? ''
}

/**
 * 六格快捷入口的 id（**真值 = 服务端单一源** `QUICK_ACTIONS`，issue #6468 起的同一份内容源）
 *
 * 从 Python 常量里现取，不在这里再抄一份 —— 抄一份就等于又造了一个会腐烂的副本。
 */
function serverQuickActionIds(): string[] {
  const py = fs.readFileSync(
    path.resolve(__dirname, '../../../backend/ai-agent-service/app/api/chat.py'),
    'utf-8',
  )
  const block = py.slice(py.indexOf('QUICK_ACTIONS'), py.indexOf('async def get_quick_actions'))
  return [...block.matchAll(/"id":\s*"([a-z_]+)"/g)].map((m) => m[1])
}

/**
 * 每个快捷入口对应空态文案里必须出现的一个业务域词（逐条可指认）
 *
 * 这张表是**故意的第二处人工映射**：空态那句是中文句子、入口 id 是机器名，
 * 没有映射就没法机械对账。它的作用 = 服务端新增/改名一条入口时，
 * 要么补这里、要么补文案，两条路都必须动代码 ⇒ 不可能「悄悄不覆盖」。
 */
const ENTRY_DOMAIN_KEYWORD: Record<string, string> = {
  daily_business: '经营',
  delivery_risk: '交付',
  low_stock: '库存',
  product_health: '商品',
  after_sales_todo: '售后',
  customer_churn: '客户',
}

describe('B 端「问黄金策」空态：不得混入 C 端 agent 内容（issue #5747）', () => {
  it('空态渲染：无商品卡 / 无价格 / 无「新品推荐」/ 无 C 端 agent 名', () => {
    const { container } = render(<MessageList messages={[]} isStreaming={false} onInteract={jest.fn()} />)

    // 结构性负向断言（不用商品名子串代理 —— 文案可能合法含商品词，那会假红）
    expect(container.querySelector('.new-arrivals')).toBeNull()
    expect(container.querySelector('.new-arrivals__card')).toBeNull()
    expect(container.querySelector('.new-arrivals__img')).toBeNull()
    expect(screen.queryByText(/新品推荐/)).toBeNull()
    expect(screen.queryByText('¥')).toBeNull()
    // C 端 agent 名（元元）不得出现在 B 端聊天面
    expect(screen.queryByText(new RegExp(C_END_AGENT_NAME))).toBeNull()
  })

  it('空态欢迎语是 B 端语义（商家经营助手），不是 C 端「专属智能购物助手」', () => {
    render(<MessageList messages={[]} isStreaming={false} onInteract={jest.fn()} />)

    expect(screen.getByText(/商家经营助手/)).toBeTruthy()
    expect(screen.queryByText(/专属智能购物助手/)).toBeNull()
    // 未配置 botName ⇒ B 端默认「黄金策」（与 C 端默认「元元」区分，见 src/utils/brand.ts）
    expect(screen.getByText(/你好，我是黄金策/)).toBeTruthy()
  })

  it('空态那句「都可以问我」必须覆盖快捷入口的每一组业务域（真值 = 服务端 QUICK_ACTIONS）', () => {
    // 治的形态（issue #6476）：空态写着「查订单、查库存、**算料报价**、售后与物流」，
    // 而六格入口是 今日经营/交付风险/库存告急/商品健康度/售后待办/客户回访 —— 两处**没有交集**，
    // 且「算料报价」在 B 端没有对应能力（引导了却答不出来，比不引导更伤）。
    const copy = emptyStateCopy()
    const ids = serverQuickActionIds()

    // ① 服务端改了入口集（新增 / 改名 / 删除）⇒ 先在这里红：要么补映射表，要么补文案，没有第三条路
    expect(ids).toEqual(Object.keys(ENTRY_DOMAIN_KEYWORD))
    // ② 文案必须逐组都提到（缺哪一组由 diff 具名给出）
    expect(ids.filter((id) => !copy.includes(ENTRY_DOMAIN_KEYWORD[id]))).toEqual([])
    // ③ 负向：B 端没有的能力不得再出现在引导里
    expect(copy).not.toContain('算料报价')
  })

  it('「思考中」默认文案用 B 端 agent 名', () => {
    render(<TypingIndicator />)
    expect(screen.getByText('黄金策正在思考...')).toBeTruthy()
  })

  it('类级元守卫：B 端源码不得再消费 C 端商品推荐端点', () => {
    const offenders = listSourceFiles(SRC_ROOT).filter((file) =>
      codeOnly(file).includes(C_END_PRODUCT_ENDPOINT),
    )
    expect(offenders.map((f) => path.relative(SRC_ROOT, f))).toEqual([])
  })

  it('类级元守卫：聊天面代码不得出现 C 端 agent 名', () => {
    const chatSurface = [path.join(SRC_ROOT, 'components', 'chat'), path.join(SRC_ROOT, 'pages', 'chat')]
    const offenders = chatSurface
      .flatMap(listSourceFiles)
      .filter((file) => codeOnly(file).includes(C_END_AGENT_NAME))
    expect(offenders.map((f) => path.relative(SRC_ROOT, f))).toEqual([])
  })

  it('类级元守卫：聊天面不得再硬编码 C 端顾客口吻的快捷入口（issue #6468）', () => {
    const chatSurface = [path.join(SRC_ROOT, 'components', 'chat'), path.join(SRC_ROOT, 'pages', 'chat')]
    const offenders = chatSurface
      .flatMap(listSourceFiles)
      .filter((file) => C_END_QUICK_PROMPTS.some((p) => codeOnly(file).includes(p)))
    expect(offenders.map((f) => path.relative(SRC_ROOT, f))).toEqual([])
  })
})
