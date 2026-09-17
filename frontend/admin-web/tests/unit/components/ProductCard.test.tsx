// case_ids: UI-006
/**
 * 米宝（B 端）会话内商品卡超链接（issue #4016 P14 第四节）
 *
 * ## 用户要求与现状（实测 @ origin/main 8cca7664）
 *
 * 用户明确要求「商品 / 订单列表卡支持超链接点击」——现状是米宝会话里的商品清单**完全不可点**
 * （`frontend/admin-web/src/components/chat/ProductCard.tsx` 无任何 `<a>`，
 * `grep href|Link|router` 为空），用户被迫手打商品名。订单卡早已可点
 * （同文件内联 `OrderRow` 的 `/orders/{id}`），商品卡是缺口。
 *
 * ## 三条硬约束（#4016 第五节，逐条落成断言）
 *
 * 1. **两端路由不同**（admin-web `/products/{id}`；mini-app 是 Taro 路由且当前**无**商品详情页
 *    ⇒ C 端没有目的地，故本项只交付 B 端）⇒ agent 侧只下发不可变标识 `id`，
 *    **路由由本端各自拼**（`_detect_card_type` / `chat.py` 内 `grep "/products/"` 为空，
 *    该不变式由 `backend/ai-agent-service/tests/test_card_type_cross_end_contract.py`
 *    的同族口径把关，本文件只钉前端侧）。
 * 2. **C 端不得暴露内部 ID**：`_mask_card_for_customer` 只脱敏**可见文本**、明确不动
 *    `options[].value`/`confirmValue` ⇒ href **绝不能放进 label**。本文件的 href 走
 *    `<Link href>`，不进任何可见文案（下条「不泄漏」断言即此约束的常驻检验）。
 * 3. **href 必须事实驱动**（只能由工具结果真值映射生成，不得模型编造）：
 *    卡数据里任何 `href`/`url`/`link` 字段一律**不采信**，否则就是「声称有链接但打不开」，
 *    与 #3970「声称发卡但没发」同族。
 *
 * ## 红证
 *
 * 给 `ProductCard` 加上「有 id 即包 `<Link>`」之前实测：3 条断言红
 * （`expected [] to deeply equal [ '/products/p-123', … ]`）；两条负例（无 id / 伪造 href）
 * 在实现前后都绿 —— 它们防的是**过度生成**（凭空造路由 / 采信模型字段）。
 *
 * ## 用例库登记（未占用 cases/ 所有权）
 *
 * 理想宿主是新建用例「卡内超链接契约」；本轮按批次口径**不改 `cases/**`**
 * （用例库正被在飞包使用 + Case Trust Gate burn-down 预算），故声明最接近的存量用例
 * `UI-006`（会话工作台）并把「补一条超链接专项用例」登记为 follow-up：见 PR 描述。
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import ProductCard from '@/components/chat/ProductCard'

/** 卡片里真实渲染出的链接目标（读 DOM 真值，非实现细节） */
const hrefs = (c: HTMLElement) =>
  Array.from(c.querySelectorAll('a')).map((a) => a.getAttribute('href'))

describe('B 端会话商品卡超链接（路由本端生成 + href 事实驱动）', () => {
  it('商品整卡可点：href = /products/{id}，id 取自工具结果真值', () => {
    const { container } = render(
      <ProductCard data={{ id: 'p-123', name: '遮光窗帘', price: 100 }} />,
    )
    expect(hrefs(container)).toEqual(['/products/p-123'])
    // 可见文案仍是商品信息本身（href 不污染 label/文本）
    expect(screen.getByText('遮光窗帘')).toBeInTheDocument()
  })

  it('product_detail 形态（data.product 包裹）同样可点', () => {
    const { container } = render(
      <ProductCard data={{ product: { id: 'p-777', name: '常青藤', price: 300 } }} />,
    )
    expect(hrefs(container)).toEqual(['/products/p-777'])
  })

  it('负例（R2）：商品没有 id 时**不生成**链接 —— 不得凭空造路由', () => {
    const { container } = render(
      <ProductCard data={{ name: '无 id 商品', price: 100 }} />,
    )
    expect(hrefs(container)).toEqual([])
    expect(screen.getByText('无 id 商品')).toBeInTheDocument()
  })

  it('事实驱动负例：卡数据里模型可得的 href/url/link 一律不被采信', () => {
    const { container } = render(
      <ProductCard
        data={{
          id: 'p-1',
          name: '窗帘A',
          price: 100,
          href: '/products/EVIL',
          url: 'https://evil.example/url',
          link: 'https://evil.example/link',
        }}
      />,
    )
    expect(hrefs(container)).toEqual(['/products/p-1'])
    expect(container.innerHTML).not.toContain('evil.example')
    expect(container.innerHTML).not.toContain('EVIL')
  })

  it('内部 ID 不进可见文案（C 端脱敏口径同族：href 绝不放进 label）', () => {
    const { container } = render(
      <ProductCard data={{ id: 'p-internal-42', name: '窗帘B', price: 200 }} />,
    )
    // id 只出现在 href 属性里；可见文本里不得出现（否则 C 端会把内部 ID 读给顾客）
    const anchor = container.querySelector('a')!
    expect(anchor.getAttribute('href')).toBe('/products/p-internal-42')
    expect(anchor.textContent || '').not.toContain('p-internal-42')
  })
})