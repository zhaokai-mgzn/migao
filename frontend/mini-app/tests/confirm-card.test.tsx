// case_ids: OR-010, CH-010
/**
 * ConfirmCard 交互测试 — 订单确认附加交互（参考瑞幸 C 端 agent）
 *
 * 覆盖：普通 confirm 字段+确认/取消；orderConfirm 时渲染
 * 配送方式(自提/外送) 分段选择 + 支付方式 + 应付金额；
 * 点确认/取消把选中值拼到 confirmValue 一并回传，供 LLM 带到下单流程。
 */
import React from 'react'
import '@testing-library/jest-dom'
import { render, screen, fireEvent } from '@testing-library/react'
import ConfirmCard from '../src/components/cards/ConfirmCard'
import type { InteractiveData } from '../src/types'

describe('ConfirmCard — 订单确认附加交互', () => {
  const onAction = jest.fn()

  afterEach(() => {
    jest.clearAllMocks()
  })

  it('普通 confirm：渲染 title/fields 与确认、取消按钮', () => {
    const data: InteractiveData = {
      type: 'confirm',
      component: 'confirm',
      title: '确认订单信息',
      fields: [
        { label: '商品', value: '遮光窗帘' },
        { label: '总价', value: '¥973.6' },
      ],
      confirmLabel: '确认下单',
      cancelLabel: '取消',
      confirmValue: '确认下单',
      cancelValue: '取消',
    }
    render(<ConfirmCard data={data} onAction={onAction} />)
    expect(screen.getByText('确认订单信息')).toBeInTheDocument()
    expect(screen.getByText('遮光窗帘')).toBeInTheDocument()
    expect(screen.getByText('确认下单')).toBeInTheDocument()
    expect(screen.getByText('取消')).toBeInTheDocument()
  })

  it('orderConfirm：渲染自提/外送分段开关、支付方式与应付金额', () => {
    const data: InteractiveData = {
      type: 'confirm',
      component: 'confirm',
      title: '请确认订单信息',
      orderConfirm: true,
      amount: '¥16.9',
      deliveryOptions: [
        { label: '自提', value: '自提' },
        { label: '外送', value: '外送' },
      ],
      paymentOptions: [
        { label: '微信支付', value: '微信支付' },
        { label: '支付宝', value: '支付宝' },
      ],
      fields: [{ label: '商品', value: '生椰拿铁 ×1' }],
      confirmLabel: '确认下单',
      confirmValue: '确认下单',
      cancelValue: '取消',
    }
    render(<ConfirmCard data={data} onAction={onAction} />)
    expect(screen.getByText('自提')).toBeInTheDocument()
    expect(screen.getByText('外送')).toBeInTheDocument()
    expect(screen.getByText('微信支付')).toBeInTheDocument()
    expect(screen.getByText('支付宝')).toBeInTheDocument()
    expect(screen.getByText('¥16.9')).toBeInTheDocument()
  })

  it('点确认：把选中的配送方式+支付方式拼进 confirmValue 回传', () => {
    const data: InteractiveData = {
      type: 'confirm',
      component: 'confirm',
      title: '请确认订单信息',
      orderConfirm: true,
      amount: '¥16.9',
      deliveryOptions: [
        { label: '自提', value: '自提' },
        { label: '外送', value: '外送' },
      ],
      paymentOptions: [
        { label: '微信支付', value: '微信支付' },
        { label: '支付宝', value: '支付宝' },
      ],
      fields: [],
      confirmLabel: '确认下单',
      confirmValue: '确认下单',
      cancelValue: '取消',
    }
    render(<ConfirmCard data={data} onAction={onAction} />)
    // 选「外送」+「支付宝」
    fireEvent.click(screen.getByText('外送'))
    fireEvent.click(screen.getByText('支付宝'))
    fireEvent.click(screen.getByText('确认下单'))
    expect(onAction).toHaveBeenCalledTimes(1)
    const sent = onAction.mock.calls[0][0] as string
    expect(sent).toContain('外送')
    expect(sent).toContain('支付宝')
  })

  it('非 orderConfirm 不渲染配送/支付控件', () => {
    const data: InteractiveData = {
      type: 'confirm',
      component: 'confirm',
      title: '确认信息',
      fields: [{ label: '姓名', value: '张三' }],
      confirmValue: '确认',
      cancelValue: '取消',
    }
    render(<ConfirmCard data={data} onAction={onAction} />)
    expect(screen.queryByText('自提')).not.toBeInTheDocument()
    expect(screen.queryByText('外送')).not.toBeInTheDocument()
    expect(screen.queryByText('微信支付')).not.toBeInTheDocument()
  })
})
