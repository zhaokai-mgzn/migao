// case_ids: OR-001
/**
 * OrderCard 组件测试（小布机器人回复中的订单卡片）
 *
 * 修复背景：order_query 下发 card type="order"（归一化后为
 * {"order": {...}} 单订单 / {"orders": [...]} 列表），但 MessageBubble
 * 的 renderCard 没有 order 分支，落入 default 占位符渲染「📎 order」，
 * 用户实测看到莫名 order 字样且订单列表无卡片样式（issue 反馈）。
 */
import React from 'react'
import { render, screen } from '@testing-library/react'
import OrderCard from '../src/components/cards/OrderCard'

describe('OrderCard', () => {
  it('单订单（{"order": ...} 归一化载荷）应渲染订单号/状态/金额', () => {
    render(<OrderCard data={{ order: { order_no: 'ORD-1001', status: 'shipped', status_text: '已发货', total_amount: 299.5, customer_name: '张三' } }} />)
    expect(screen.getByText(/ORD-1001/)).toBeTruthy()
    expect(screen.getByText('已发货')).toBeTruthy()
    expect(screen.getByText(/299\.50/)).toBeTruthy()
  })

  it('应渲染商品明细行（名称 ×数量 与 小计）', () => {
    render(
      <OrderCard
        data={{
          order: {
            order_no: 'ORD-1001',
            status: 'shipped',
            status_text: '已发货',
            total_amount: 299.5,
            items_count: 2,
            items: [
              { product_name: '北欧风窗帘', quantity: 2, unit_price: 99.5, amount: 199 },
              { product_name: '遮光帘', quantity: 1, unit_price: 100.5, amount: 100.5 },
            ],
          },
        }}
      />,
    )
    expect(screen.getByText('北欧风窗帘')).toBeTruthy()
    expect(screen.getByText('×2')).toBeTruthy()
    expect(screen.getByText('遮光帘')).toBeTruthy()
    expect(screen.getByText(/199\.00/)).toBeTruthy()
    expect(screen.getByText(/100\.50/)).toBeTruthy()
  })

  it('商品超过 3 行时应显示「等N件商品」', () => {
    const items = Array.from({ length: 5 }, (_, i) => ({
      product_name: `商品${i + 1}`,
      quantity: 1,
      amount: 10,
    }))
    render(<OrderCard data={{ order: { order_no: 'ORD-3003', status: 'completed', items_count: 5, items } }} />)
    expect(screen.getByText('等5件商品')).toBeTruthy()
  })

  it('兼容 camelCase 字段（orderNo/totalAmount/customerName）', () => {
    render(<OrderCard data={{ order: { orderNo: 'ORD-2002', status: 'completed', totalAmount: 128, customerName: '李四' } }} />)
    expect(screen.getByText(/ORD-2002/)).toBeTruthy()
    expect(screen.getByText(/128\.00/)).toBeTruthy()
    expect(screen.getByText(/李四/)).toBeTruthy()
  })

  it('订单列表（{"orders": [...]} 归一化载荷）应逐单渲染', () => {
    render(
      <OrderCard
        data={{
          orders: [
            { order_no: 'ORD-A', status: 'pending', status_text: '待付款', total_amount: 50 },
            { order_no: 'ORD-B', status: 'producing', status_text: '生产中', total_amount: 88 },
          ],
        }}
      />,
    )
    expect(screen.getByText(/ORD-A/)).toBeTruthy()
    expect(screen.getByText(/ORD-B/)).toBeTruthy()
    expect(screen.getByText('待付款')).toBeTruthy()
    expect(screen.getByText('生产中')).toBeTruthy()
  })

  it('无有效订单数据时不应渲染（避免空盒子）', () => {
    const { container } = render(<OrderCard data={{}} />)
    expect(container.firstChild).toBeNull()
  })

  it('手机号应脱敏展示（CH-011 数据安全）：13800138000 → 138****8000', () => {
    render(
      <OrderCard
        data={{
          order: {
            order_no: 'ORD-1001',
            status: 'shipped',
            status_text: '已发货',
            total_amount: 299.5,
            customer_name: '张三',
            customer_phone: '13800138000',
          },
        }}
      />,
    )
    expect(screen.getByText('138****8000')).toBeTruthy()
    // 明文手机号不得出现在卡片中
    expect(screen.queryByText('13800138000')).toBeNull()
  })

  it('无手机号时仅展示客户名（不渲染脱敏空串）', () => {
    render(
      <OrderCard
        data={{
          order: { order_no: 'ORD-1002', status: 'pending', status_text: '待付款', customer_name: '李四' },
        }}
      />,
    )
    expect(screen.getByText(/李四/)).toBeTruthy()
    expect(screen.queryByText('****')).toBeNull()
  })
})
