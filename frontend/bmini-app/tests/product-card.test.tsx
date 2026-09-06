// case_ids: PR-001, PR-003, OR-010
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
