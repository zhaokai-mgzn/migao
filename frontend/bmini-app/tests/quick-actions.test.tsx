// case_ids: BM-028
/**
 * B 端「问米宝」快捷入口组件测试（issue #5747 建，issue #6468 改内容来源）
 *
 * ## 两层判据
 *
 * 1. **形态**（#5747，未变）：**六格等权、2 列 × 3 行**，无全宽主入口、无分组结构
 *    （用户 2026-09-18 裁定「上个 2 列 × 3 行更好看」）。
 * 2. **内容来源**（#6468，本次）：入口内容 = **服务端单一真值**
 *    （`GET /api/chat/quick-actions`），组件只渲染传入的 `actions`。
 *    旧形态是**组件里硬编码六条 C 端顾客口吻**的入口（「推荐一下热门窗帘产品」「帮我查一下物流」…）
 *    —— 那正是 #6468 的病灶，判据 2 就是让它进不来。
 *
 * ⚠️ 本文件此前声明 `# case_ids: UI-010, UI-014` —— 那是 **C 端（小布）的用例号**：
 * 连用例号一起被抄进 B 端，正是 issue #5747 的形态。现改钉 B 端自己的用例 BM-028。
 *
 * 服务端那半（六条内容 + 「每条必须追溯到真实能力」的机械投影）判据在
 * `backend/ai-agent-service/tests/test_chat.py::TestQuickActions`。
 */
import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import QuickActions from '../src/components/chat/QuickActions'
import type { QuickAction } from '../src/types'

/** 服务端 `QUICK_ACTIONS` 的 B 端场景六条（`backend/ai-agent-service/app/api/chat.py`） */
const SERVER_ACTIONS: QuickAction[] = [
  { id: 'daily_business', name: '今日经营', icon: 'bar-chart-3', emoji: '📊', prompt: '今天经营怎么样？' },
  { id: 'delivery_risk', name: '交付风险', icon: 'clipboard-list', emoji: '🚨', prompt: '哪些订单快到交期还卡着工序？' },
  { id: 'low_stock', name: '库存告急', icon: 'package', emoji: '📦', prompt: '有哪些低库存的商品？' },
  { id: 'product_health', name: '商品健康度', icon: 'tag', emoji: '🏷️', prompt: '哪些商品卖得好但退货高？' },
  { id: 'after_sales_todo', name: '售后待办', icon: 'headphones', emoji: '🛠️', prompt: '有哪些售后工单还没处理？' },
  { id: 'customer_churn', name: '客户回访', icon: 'users', emoji: '👥', prompt: '哪些老客户最近不下单了？' },
]

describe('QuickActions（B 端六格 · 内容来自服务端单一真值）', () => {
  const mockOnAction = jest.fn()

  beforeEach(() => {
    jest.clearAllMocks()
  })

  it('应渲染标题', () => {
    render(<QuickActions actions={SERVER_ACTIONS} onAction={mockOnAction} />)
    expect(screen.getByText('您可以试试以下问题')).toBeTruthy()
  })

  it('恰好六格等权（2 列 × 3 行）', () => {
    const { container } = render(<QuickActions actions={SERVER_ACTIONS} onAction={mockOnAction} />)
    const items = container.querySelectorAll('.quick-actions__item')
    expect(items.length).toBe(6)
    for (const item of Array.from(items)) {
      // 全宽主入口已撤下（C 端 #4236 同款裁定）—— 留在 B 端就是「旧版 C 端页面」
      expect(item.className).not.toContain('quick-actions__item--wide')
    }
    // 负向：两栏分组结构（C 端 #4209 中间态）不得残留
    expect(container.querySelector('.quick-actions__group')).toBeNull()
    expect(container.querySelector('.quick-actions__row')).toBeNull()
  })

  it('渲染服务端下发的名称与 emoji（不是本地清单）', () => {
    render(<QuickActions actions={SERVER_ACTIONS} onAction={mockOnAction} />)

    for (const label of ['今日经营', '交付风险', '库存告急', '商品健康度', '售后待办', '客户回访']) {
      expect(screen.getByText(label)).toBeTruthy()
    }
    for (const emoji of ['📊', '🚨', '📦', '🏷️', '🛠️', '👥']) {
      expect(screen.getByText(emoji)).toBeTruthy()
    }

    // 负向：C 端顾客口吻的旧入口名与旧 prompt 一律不得出现
    for (const cEndLabel of ['算料报价', '找产品', '售后咨询', '查物流', '退换货', '转人工']) {
      expect(screen.queryByText(cEndLabel)).toBeNull()
    }
  })

  it('点击各入口应发送服务端给的 prompt（逐格可断言）', () => {
    render(<QuickActions actions={SERVER_ACTIONS} onAction={mockOnAction} />)

    for (const action of SERVER_ACTIONS) {
      mockOnAction.mockClear()
      fireEvent.click(screen.getByText(action.name))
      expect(mockOnAction).toHaveBeenCalledWith(action.prompt)
    }
  })

  it('内容为空时不渲染 —— 不退回一份本地兜底清单（#6468 的病灶形态）', () => {
    const { container } = render(<QuickActions actions={[]} onAction={mockOnAction} />)

    expect(container.querySelectorAll('.quick-actions__item').length).toBe(0)
    // 空态不是「渲染出另一套写死的内容」：标题与格位都不该出现
    expect(screen.queryByText('您可以试试以下问题')).toBeNull()
  })

  it('类级元守卫：组件源码不得再自带入口内容（本地清单 / emoji 字面量 = 又抄一份）', () => {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const fs = require('fs') as typeof import('fs')
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const path = require('path') as typeof import('path')
    const source = fs.readFileSync(
      path.resolve(__dirname, '../src/components/chat/QuickActions.tsx'),
      'utf-8',
    )
    // 只扫代码（整行注释里的说明不算）：注释里会逐字引用旧入口作为病历
    const code = source
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .split('\n')
      .filter((line) => !line.trim().startsWith('//'))
      .join('\n')

    // 本地常量清单（`const X = [...]`）—— 内容一旦写回组件就是第二份真值
    expect(code).not.toMatch(/ACTIONS\s*[:=]\s*\[/)
    // emoji 图标字面量 —— 图标同样由服务端下发（旧形态的六条各带一个 emoji）
    expect(code).not.toMatch(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u)
  })
})
