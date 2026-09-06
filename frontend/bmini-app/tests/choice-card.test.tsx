// case_ids: API-006
/**
 * ChoiceCard 组件测试（choice 交互组件：选项列表 + 翻页）
 *
 * 修复背景：后端翻页查询（查订单/商品）下发 SSE interactive("choice") 事件，
 * 前端此前只渲染 confirm 类型，choice 直接 return null → 控件整体消失（用户实测 bug）。
 */
import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import ChoiceCard from '../src/components/cards/ChoiceCard'
import type { InteractiveData } from '../src/types'

describe('ChoiceCard', () => {
  const baseChoice: InteractiveData = {
    type: 'choice',
    component: 'choice',
    title: '窗帘有哪些款式？(第1/3页)',
    options: [
      { label: '现代简约', value: '现代简约', description: '百搭耐看' },
      { label: '北欧风', value: '北欧风', description: '清新自然' },
    ],
  }

  it('应渲染标题和选项列表', () => {
    render(<ChoiceCard data={baseChoice} onAction={jest.fn()} />)
    expect(screen.getByText('窗帘有哪些款式？(第1/3页)')).toBeTruthy()
    expect(screen.getByText('现代简约')).toBeTruthy()
    expect(screen.getByText('北欧风')).toBeTruthy()
  })

  it('点击选项应触发 onAction 并回传 value', () => {
    const onAction = jest.fn()
    render(<ChoiceCard data={baseChoice} onAction={onAction} />)
    fireEvent.click(screen.getByText('现代简约'))
    expect(onAction).toHaveBeenCalledWith('现代简约')
  })

  it('选项有 description 时应渲染描述', () => {
    render(<ChoiceCard data={baseChoice} onAction={jest.fn()} />)
    expect(screen.getByText('百搭耐看')).toBeTruthy()
  })

  it('无 pageMeta 时不应显示翻页控件', () => {
    const { queryByText } = render(
      <ChoiceCard data={baseChoice} onAction={jest.fn()} />,
    )
    expect(queryByText('下一页')).toBeNull()
  })

  it('有 pageMeta 且非首页时应渲染上一页/下一页按钮', () => {
    const paged: InteractiveData = {
      ...baseChoice,
      pageMeta: {
        current: 2,
        total: 3,
        totalCount: 30,
        tool: 'product_search',
        params: 'page=1&keyword=窗帘',
      },
    }
    const onAction = jest.fn()
    render(<ChoiceCard data={paged} onAction={onAction} />)

    expect(screen.getByText('上一页')).toBeTruthy()
    expect(screen.getByText('下一页')).toBeTruthy()
    expect(screen.getByText('2/3')).toBeTruthy()

    fireEvent.click(screen.getByText('下一页'))
    // 翻页动作以可读文本形式回传，由 AI 处理
    expect(onAction).toHaveBeenCalled()
  })
})
