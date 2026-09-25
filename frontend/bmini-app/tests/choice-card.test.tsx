// case_ids: API-006, CH-030
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

const baseChoice: InteractiveData = {
  type: 'choice',
  component: 'choice',
  title: '窗帘有哪些款式？(第1/3页)',
  options: [
    { label: '现代简约', value: '现代简约', description: '百搭耐看' },
    { label: '北欧风', value: '北欧风', description: '清新自然' },
  ],
}

describe('ChoiceCard', () => {

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

describe('ChoiceCard — 提交锁（CH-030 防重复提交）', () => {
  afterEach(() => {
    jest.clearAllMocks()
  })

  it('点选项后锁卡：后续点击不再触发 onAction', () => {
    const onAction = jest.fn()
    render(<ChoiceCard data={baseChoice} onAction={onAction} />)
    fireEvent.click(screen.getByText('现代简约'))
    fireEvent.click(screen.getByText('北欧风'))
    expect(onAction).toHaveBeenCalledTimes(1)
  })

  it('disabled=true（历史已答只读）：点击选项不触发 onAction', () => {
    const onAction = jest.fn()
    render(<ChoiceCard data={baseChoice} onAction={onAction} disabled />)
    fireEvent.click(screen.getByText('现代简约'))
    expect(onAction).not.toHaveBeenCalled()
  })
})

describe('ChoiceCard — 多选卡：勾选积累 + 「完成选择(N)」一次性提交（CH-030 同一协议面，issue #3947）', () => {
  afterEach(() => {
    jest.clearAllMocks()
  })

  // 与后端 interact(multiSelect=true) 下发的载荷同形（interact.py 在 multiSelect 时
  // 一定补齐 prefix/label/skipLabel 三个文案字段）
  const multiCard: InteractiveData = {
    type: 'choice',
    component: 'choice',
    multiSelect: true,
    multiSelectSubmitPrefix: '已选商品：',
    multiSelectSubmitLabel: '完成选择',
    multiSelectSkipLabel: '不需要加工项',
    title: '请勾选要批量修改的商品（可多选）',
    options: [
      { label: '亚麻窗帘 A', value: 'sku_1001' },
      { label: '雪尼尔窗帘 B', value: 'sku_1002' },
    ],
  }

  it('勾选 A、B 后提交：一次性回传 prefix + 已选名称集合（点第一项不得提交/锁卡）', () => {
    const onAction = jest.fn()
    render(<ChoiceCard data={multiCard} onAction={onAction} />)

    fireEvent.click(screen.getByText('亚麻窗帘 A'))
    fireEvent.click(screen.getByText('雪尼尔窗帘 B'))
    expect(onAction).not.toHaveBeenCalled()

    fireEvent.click(screen.getByText('完成选择（2）'))
    expect(onAction).toHaveBeenCalledTimes(1)
    expect(onAction).toHaveBeenCalledWith('已选商品：亚麻窗帘 A、雪尼尔窗帘 B')
  })

  it('未勾选任何项时不渲染提交按钮；提交后锁卡（CH-030 不回归）', () => {
    const onAction = jest.fn()
    render(<ChoiceCard data={multiCard} onAction={onAction} />)
    expect(screen.queryByText(/完成选择（/)).toBeNull()

    fireEvent.click(screen.getByText('亚麻窗帘 A'))
    fireEvent.click(screen.getByText('完成选择（1）'))
    fireEvent.click(screen.getByText('雪尼尔窗帘 B'))
    expect(onAction).toHaveBeenCalledTimes(1)
  })

  it('跳过按钮只在卡自带 multiSelectSkipLabel 时渲染并原样回传该文案', () => {
    const onAction = jest.fn()
    const { unmount } = render(<ChoiceCard data={multiCard} onAction={onAction} />)
    fireEvent.click(screen.getByText('不需要加工项'))
    expect(onAction).toHaveBeenCalledWith('不需要加工项')
    unmount()

    const noSkip: InteractiveData = { ...multiCard }
    delete noSkip.multiSelectSkipLabel
    render(<ChoiceCard data={noSkip} onAction={jest.fn()} />)
    expect(screen.queryByText('不需要加工项')).toBeNull()
  })

  it('单选卡（无 multiSelect）点第一项仍立即回传 value，且不渲染多选提交按钮（防回归）', () => {
    const onAction = jest.fn()
    render(<ChoiceCard data={baseChoice} onAction={onAction} />)
    fireEvent.click(screen.getByText('现代简约'))
    expect(onAction).toHaveBeenCalledTimes(1)
    expect(onAction).toHaveBeenCalledWith('现代简约')
    expect(screen.queryByText(/完成选择/)).toBeNull()
  })
})
