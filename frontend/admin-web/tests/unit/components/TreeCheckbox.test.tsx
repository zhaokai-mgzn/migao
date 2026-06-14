// @vitest-environment jsdom
import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import type { TreeNode } from '../../../src/components/ui/TreeCheckbox'
import { TreeCheckbox } from '../../../src/components/ui/TreeCheckbox'

const MOCK_MENUS: TreeNode[] = [
  { code: 'dashboard', label: '工作台', children: [{ code: 'dashboard.view', label: '数据看板' }] },
  { code: 'orders', label: '订单管理', children: [
    { code: 'orders.list', label: '订单列表' }, { code: 'orders.detail', label: '订单详情' }, { code: 'orders.refund', label: '退换货' },
  ]},
  { code: 'products', label: '商品管理', children: [
    { code: 'products.list', label: '商品列表' }, { code: 'products.create', label: '新增商品' },
  ]},
  { code: 'agent', label: '客服工作台', children: [] },
]

/** 通过 label 文字找最近的 checkbox */
const cb = (text: string): HTMLInputElement => {
  const el = screen.getAllByText(text)
    .find(e => e.tagName === 'SPAN' && e.parentElement?.tagName === 'LABEL') || screen.getAllByText(text)[0]
  return (el.closest('label') || el.parentElement!).querySelector('input') as HTMLInputElement
}

describe('TreeCheckbox', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
  })

  it('renders 11 checkboxes', () => {
    render(<TreeCheckbox tree={MOCK_MENUS} selected={[]} onChange={() => {}} />)
    expect(screen.getAllByRole('checkbox')).toHaveLength(11)
  })

  it('clicking parent selects all children', () => {
    const onChange = vi.fn()
    render(<TreeCheckbox tree={MOCK_MENUS} selected={[]} onChange={onChange} />)
    const el = cb('订单管理')
    expect(el).toBeTruthy()
    fireEvent.click(el)
    // Check that onChange was called
    expect(onChange).toHaveBeenCalledTimes(1)
    const called = onChange.mock.calls[0][0] as string[]
    expect(called.sort()).toEqual(['orders.detail', 'orders.list', 'orders.refund'].sort())
  })

  it('clicking checked parent deselects all children', () => {
    const onChange = vi.fn()
    render(<TreeCheckbox tree={MOCK_MENUS} selected={['orders.list', 'orders.detail', 'orders.refund']} onChange={onChange} />)
    fireEvent.click(cb('订单管理'))
    expect(onChange.mock.calls[0][0]).not.toContain('orders.list')
  })

  it('parent checked when all children selected', () => {
    render(<TreeCheckbox tree={MOCK_MENUS} selected={['orders.list', 'orders.detail', 'orders.refund']} onChange={() => {}} />)
    expect(cb('订单管理').checked).toBe(true)
  })

  it('parent indeterminate when partial children selected', () => {
    render(<TreeCheckbox tree={MOCK_MENUS} selected={['orders.list']} onChange={() => {}} />)
    expect(cb('订单管理').indeterminate).toBe(true)
  })

  it('master selects all leaves', () => {
    const onChange = vi.fn()
    render(<TreeCheckbox tree={MOCK_MENUS} selected={[]} onChange={onChange} />)
    fireEvent.click(cb('全部权限'))
    const all = MOCK_MENUS.flatMap(n => n.children?.length ? n.children.map(c => c.code) : n.code)
    expect(onChange).toHaveBeenCalledWith(expect.arrayContaining(all))
  })

  it('master checked when all selected', () => {
    const all = MOCK_MENUS.flatMap(n => n.children?.length ? n.children.map(c => c.code) : n.code)
    render(<TreeCheckbox tree={MOCK_MENUS} selected={all} onChange={() => {}} />)
    expect(cb('全部权限').checked).toBe(true)
  })

  it('master indeterminate when partial', () => {
    render(<TreeCheckbox tree={MOCK_MENUS} selected={['orders.list']} onChange={() => {}} />)
    expect(cb('全部权限').indeterminate).toBe(true)
  })

  it('leaf toggle adds code', () => {
    const onChange = vi.fn()
    render(<TreeCheckbox tree={MOCK_MENUS} selected={[]} onChange={onChange} />)
    fireEvent.click(cb('数据看板'))
    expect(onChange).toHaveBeenCalledWith(['dashboard.view'])
  })

  it('leaf toggle removes code', () => {
    const onChange = vi.fn()
    render(<TreeCheckbox tree={MOCK_MENUS} selected={['dashboard.view']} onChange={onChange} />)
    fireEvent.click(cb('数据看板'))
    expect(onChange).toHaveBeenCalledWith([])
  })
})
