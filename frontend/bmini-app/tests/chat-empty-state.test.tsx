// case_ids: BM-028
/**
 * B 端「问米宝」空态契约 —— **不得混入 C 端 agent 的内容**（issue #5747）
 *
 * ## 治的形态
 *
 * B 端 agent 页（`src/pages/chat/index/index.tsx`）**照抄了 C 端小布主页的旧版本**：
 * 空态渲染 `NewArrivals`（商品卡，拉 **C 端端点** `/api/chat/products/new-arrivals`，
 * 提示「点一下问问小布」）⇒ 商家在 `/b/` 里看到的是**顾客端的入口与商品展示**。
 *
 * C 端（`frontend/mini-app`）早在 issue #3978 / #4236 就删掉了这块（判据 =
 * `tests/e2e/specs/xiaobu/xiaobu-h5.spec.ts` 的 `.new-arrivals` 为零 / `¥` 为零负向断言）。
 *
 * ## 两层判据
 *
 * 1. **行为层**（渲染出来是什么）：空态不得出现商品卡容器 / 价格符号 / 「新品推荐」文本 /
 *    C 端 agent 名（「小布」）；欢迎语是 B 端语义（商家经营助手），不是「专属智能购物助手」。
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
/** C 端 agent（小布）的默认名 —— B 端默认「米宝」，出现在 B 端聊天面即为串味 */
const C_END_AGENT_NAME = '小布'
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

describe('B 端「问米宝」空态：不得混入 C 端 agent 内容（issue #5747）', () => {
  it('空态渲染：无商品卡 / 无价格 / 无「新品推荐」/ 无 C 端 agent 名', () => {
    const { container } = render(<MessageList messages={[]} isStreaming={false} onInteract={jest.fn()} />)

    // 结构性负向断言（不用商品名子串代理 —— 文案可能合法含商品词，那会假红）
    expect(container.querySelector('.new-arrivals')).toBeNull()
    expect(container.querySelector('.new-arrivals__card')).toBeNull()
    expect(container.querySelector('.new-arrivals__img')).toBeNull()
    expect(screen.queryByText(/新品推荐/)).toBeNull()
    expect(screen.queryByText('¥')).toBeNull()
    // C 端 agent 名（小布）不得出现在 B 端聊天面
    expect(screen.queryByText(new RegExp(C_END_AGENT_NAME))).toBeNull()
  })

  it('空态欢迎语是 B 端语义（商家经营助手），不是 C 端「专属智能购物助手」', () => {
    render(<MessageList messages={[]} isStreaming={false} onInteract={jest.fn()} />)

    expect(screen.getByText(/商家经营助手/)).toBeTruthy()
    expect(screen.queryByText(/专属智能购物助手/)).toBeNull()
    // 未配置 botName ⇒ B 端默认「米宝」（与 C 端默认「小布」区分，见 src/utils/brand.ts）
    expect(screen.getByText(/你好，我是米宝/)).toBeTruthy()
  })

  it('「思考中」默认文案用 B 端 agent 名', () => {
    render(<TypingIndicator />)
    expect(screen.getByText('米宝正在思考...')).toBeTruthy()
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
