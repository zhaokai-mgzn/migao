// case_ids: PR-001, PR-003, OR-010
/**
 * 商品表单列表测试 — 瑞幸式选品列表（参考 C 端 agent 选品交互）
 *
 * 覆盖：多商品紧凑行渲染（图/名称/规格/价格）、可点规格 chips（点击发送规格选择）、
 * 「预计到手」划线价、「去下单」CTA、空列表不渲染。
 */
import React from 'react'
import '@testing-library/jest-dom'
import { render, screen, fireEvent } from '@testing-library/react'
import ProductFormList from '../src/components/cards/ProductFormList'

describe('ProductFormList — 瑞幸式商品表单列表', () => {
  const products = [
    {
      id: 'p-1',
      name: '遮光窗帘',
      price: 199,
      original_price: 299,
      sales_count: 28,
      specifications: { colorName: '深灰', doorWidth: '2.8米' },
    },
    {
      id: 'p-2',
      name: '纱帘',
      price: 89,
      specifications: { colorName: '米白' },
    },
  ]

  const onInteract = jest.fn()

  afterEach(() => {
    jest.clearAllMocks()
  })

  it('渲染多商品紧凑行（名称/价格/销量）', () => {
    render(<ProductFormList products={products} onInteract={onInteract} />)
    expect(screen.getByText('遮光窗帘')).toBeInTheDocument()
    expect(screen.getByText('纱帘')).toBeInTheDocument()
    expect(screen.getByText('199.00')).toBeInTheDocument()
    expect(screen.getByText('89.00')).toBeInTheDocument()
    expect(screen.getByText(/已售 28 件/)).toBeInTheDocument()
  })

  it('渲染规格行与划线原价（预计到手）', () => {
    render(<ProductFormList products={products} onInteract={onInteract} />)
    expect(screen.getByText(/深灰/)).toBeInTheDocument()
    expect(screen.getByText(/2.8米/)).toBeInTheDocument()
    expect(screen.getByText('预计到手')).toBeInTheDocument()
    expect(screen.getByText('¥299.00')).toBeInTheDocument()
  })

  it('点击「去下单」触发 onInteract（携带商品名）', () => {
    render(<ProductFormList products={products} onInteract={onInteract} />)
    const orderBtns = screen.getAllByText('去下单')
    fireEvent.click(orderBtns[0])
    expect(onInteract).toHaveBeenCalledWith('我要下单遮光窗帘')
  })

  it('点击规格 chip 触发 onInteract（发送规格选择）', () => {
    render(<ProductFormList products={products} onInteract={onInteract} />)
    // 规格 chip 文案（点「深灰」→ 发送选规格消息）
    fireEvent.click(screen.getByText('深灰'))
    expect(onInteract).toHaveBeenCalledTimes(1)
    expect(onInteract.mock.calls[0][0]).toContain('深灰')
    expect(onInteract.mock.calls[0][0]).toContain('遮光窗帘')
  })

  it('空列表不渲染', () => {
    const { container } = render(<ProductFormList products={[]} onInteract={onInteract} />)
    expect(container.firstChild).toBeNull()
  })
})
