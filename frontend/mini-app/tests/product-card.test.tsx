// case_ids: PR-001, PR-003, OR-010, CH-030
/**
 * 商品卡片交互测试 — 瑞幸式商品卡（参考 C 端 agent 设计）
 *
 * 覆盖：商品名/价格/销量渲染、规格行（specifications/规格数组）、
 * 「预计到手」价（original_price 划线）与到手价展示、
 * 「去下单」CTA 触发 onOrder（把商品名带入对话下单流程）。
 */
import React from 'react'
import '@testing-library/jest-dom'
import { render, screen, fireEvent } from '@testing-library/react'
import ProductCard from '../src/components/cards/ProductCard'

describe('ProductCard — 瑞幸式商品卡交互', () => {
  const baseProduct = {
    id: 'p-001',
    name: '遮光窗帘',
    price: 199,
  }

  afterEach(() => {
    jest.clearAllMocks()
  })

  it('渲染商品名、价格、销量', () => {
    render(
      <ProductCard data={{ ...baseProduct, price: 199, sales_count: 28 }} />
    )
    expect(screen.getByText('遮光窗帘')).toBeInTheDocument()
    expect(screen.getByText('199.00')).toBeInTheDocument()
    expect(screen.getByText(/已售 28 件/)).toBeInTheDocument()
  })

  it('渲染规格行（specifications 对象）', () => {
    render(
      <ProductCard
        data={{
          ...baseProduct,
          specifications: { colorName: '深灰', doorWidth: '2.8米', sellMethod: '整幅' },
        }}
      />
    )
    const spec = screen.getByText(/深灰/)
    expect(spec).toBeInTheDocument()
    expect(screen.getByText(/2.8米/)).toBeInTheDocument()
  })

  it('渲染「预计到手」价与划线原价', () => {
    render(<ProductCard data={{ ...baseProduct, price: 139, original_price: 199 }} />)
    // 到手价（当前价）与划线原价都可见
    expect(screen.getByText('预计到手')).toBeInTheDocument()
    expect(screen.getByText('139.00')).toBeInTheDocument()
    expect(screen.getByText('¥199.00')).toBeInTheDocument()
  })

  it('点击「去下单」CTA 触发 onOrder（携带商品名）', () => {
    const onOrder = jest.fn()
    render(<ProductCard data={baseProduct} onOrder={onOrder} />)
    fireEvent.click(screen.getByText('去下单'))
    expect(onOrder).toHaveBeenCalledTimes(1)
    expect(onOrder).toHaveBeenCalledWith('遮光窗帘')
  })

  it('无 original_price 时不显示划线原价', () => {
    render(<ProductCard data={baseProduct} />)
    expect(screen.queryByText('预计到手')).not.toBeInTheDocument()
  })
})

describe('ProductCard — 下单防连点锁（issue #3040 收尾）', () => {
  afterEach(() => {
    jest.clearAllMocks()
  })

  it('点「下单」后锁卡：第二次点击不再触发 onOrder（防重复下单）', () => {
    const onOrder = jest.fn()
    render(<ProductCard data={{ id: 'p-001', name: '遮光窗帘', price: 199 }} onOrder={onOrder} />)
    fireEvent.click(screen.getByText(/去下单/))
    fireEvent.click(screen.getByText(/去下单/))
    expect(onOrder).toHaveBeenCalledTimes(1)
  })
})

describe('ProductCard — 内部 ID 不外显 / 无链路（#4016 P14 第四节约束）', () => {
  it('C 端商品卡不渲染任何超链接（本端无商品详情页 ⇒ 没有目的地）', () => {
    // 两端路由不同：admin-web 有 /products/{id}，mini-app 只有 chat/auth/profile 三个页面
    // （`app.config.ts` 实证）⇒ C 端**没有**可跳转目的地。硬造 href 会落到 404，
    // 属「声称有链接但打不开」（#3970 同族）。故本端锁「无链接」真值；
    // 待产品补 C 端商品详情页后再放开（已登记 follow-up）。
    const { container } = render(<ProductCard data={{ id: 'p-001', name: '遮光窗帘', price: 199 }} />)
    expect(container.querySelectorAll('a')).toHaveLength(0)
  })

  it('内部 ID（product_id/id）不进可见文案 —— 脱敏只覆盖可见文本', () => {
    // 约束 2：`_mask_card_for_customer` 只脱敏**可见文本**（title/fields/options.label），
    // 明确不动协议值 ⇒ 一旦把内部 ID 渲染成文案，顾客就会看到内部 ID。
    const { container } = render(
      <ProductCard data={{ id: 'p-internal-42', product_id: 'p-internal-42', name: '窗帘B', price: 200 }} />,
    )
    const text = container.textContent || ''
    expect(text).not.toContain('p-internal-42')
    expect(text).not.toContain('product_id')
  })
})
