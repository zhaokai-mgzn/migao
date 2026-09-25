// case_ids: API-006, CH-030, UI-043
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

describe('ChoiceCard — 点击协议回传人话 label（UI-043，对齐 issue #3365 与 admin-web InteractiveMessage 单一事实源）', () => {
  afterEach(() => {
    jest.clearAllMocks()
  })

  const procCard: InteractiveData = {
    type: 'choice',
    component: 'choice',
    title: '请选择需要的加工项（可多选，不需要请点右下角按钮）',
    options: [
      { label: '压褶定型 ¥12/米', value: 'proc_item_craft_press' },
      { label: 'LG工艺 ¥50/件', value: 'proc_item_craft_lg' },
    ],
  }

  it('点击选项回传 label（人话），不得发内部编码 value', () => {
    const onAction = jest.fn()
    render(<ChoiceCard data={procCard} onAction={onAction} />)
    fireEvent.click(screen.getByText('LG工艺 ¥50/件'))
    expect(onAction).toHaveBeenCalledWith('LG工艺 ¥50/件')
    expect(onAction).not.toHaveBeenCalledWith('proc_item_craft_lg')
  })

  it('选项缺 label 时回退 value（协议：label || value）', () => {
    const noLabel: InteractiveData = {
      type: 'choice',
      component: 'choice',
      title: '请选择',
      options: [{ value: 'fallback_value', label: '' }],
    }
    const onAction = jest.fn()
    const { container } = render(<ChoiceCard data={noLabel} onAction={onAction} />)
    fireEvent.click(container.querySelector('.choice-card__option') as HTMLElement)
    expect(onAction).toHaveBeenCalledWith('fallback_value')
  })
})

describe('ChoiceCard — 多选卡：勾选积累 + 「完成选择(N)」一次性提交（UI-043 / CH-030，issue #3947）', () => {
  afterEach(() => {
    jest.clearAllMocks()
  })

  // 与后端 interact(multiSelect=true) 下发的载荷同形（interact.py 在 multiSelect 时
  // 一定补齐 prefix/label/skipLabel 三个文案字段；C 端加工项兜底卡只带 multiSelect）
  const multiCard: InteractiveData = {
    type: 'choice',
    component: 'choice',
    multiSelect: true,
    multiSelectSubmitPrefix: '已选加工项：',
    multiSelectSubmitLabel: '完成选择',
    multiSelectSkipLabel: '不需要加工项',
    title: '这款商品支持以下加工项，需要哪些呢？（可多选）',
    options: [
      { label: '压褶定型（米）', value: 'proc_item_craft_press' },
      { label: 'LG工艺（件）', value: 'proc_item_craft_lg' },
      { label: '打孔（米）', value: 'proc_item_craft_hole' },
    ],
  }

  it('勾选 A、B 后提交：一次性回传 prefix + 已选项集合（点第一项不得提交/锁卡）', () => {
    const onAction = jest.fn()
    render(<ChoiceCard data={multiCard} onAction={onAction} />)

    fireEvent.click(screen.getByText('压褶定型（米）'))
    fireEvent.click(screen.getByText('LG工艺（件）'))
    // 勾选阶段必须**零提交**：改前点第一项即 onAction + 锁卡 ⇒ 多选意图被吞
    expect(onAction).not.toHaveBeenCalled()

    fireEvent.click(screen.getByText('完成选择（2）'))
    expect(onAction).toHaveBeenCalledTimes(1)
    expect(onAction).toHaveBeenCalledWith('已选加工项：压褶定型（米）、LG工艺（件）')
  })

  it('再点已选项 = 取消勾选，提交载荷随之收缩', () => {
    const onAction = jest.fn()
    render(<ChoiceCard data={multiCard} onAction={onAction} />)
    fireEvent.click(screen.getByText('压褶定型（米）'))
    fireEvent.click(screen.getByText('LG工艺（件）'))
    fireEvent.click(screen.getByText('压褶定型（米）'))
    fireEvent.click(screen.getByText('完成选择（1）'))
    expect(onAction).toHaveBeenCalledTimes(1)
    expect(onAction).toHaveBeenCalledWith('已选加工项：LG工艺（件）')
  })

  it('未勾选任何项时不渲染提交按钮（不给「空的提交」）', () => {
    render(<ChoiceCard data={multiCard} onAction={jest.fn()} />)
    expect(screen.queryByText('完成选择（0）')).toBeNull()
    expect(screen.queryByText(/完成选择（/)).toBeNull()
  })

  it('提交后锁卡：再点选项不再触发 onAction（CH-030 不回归）', () => {
    const onAction = jest.fn()
    render(<ChoiceCard data={multiCard} onAction={onAction} />)
    fireEvent.click(screen.getByText('压褶定型（米）'))
    fireEvent.click(screen.getByText('完成选择（1）'))
    fireEvent.click(screen.getByText('LG工艺（件）'))
    expect(onAction).toHaveBeenCalledTimes(1)
  })

  it('跳过：卡自带 multiSelectSkipLabel 时渲染跳过按钮并原样回传该文案', () => {
    const onAction = jest.fn()
    render(<ChoiceCard data={multiCard} onAction={onAction} />)
    fireEvent.click(screen.getByText('不需要加工项'))
    expect(onAction).toHaveBeenCalledWith('不需要加工项')
  })

  it('卡未带 multiSelectSkipLabel 时不渲染跳过按钮（凭空发默认文案会让答卡轮失配）', () => {
    const noSkip: InteractiveData = { ...multiCard }
    delete noSkip.multiSelectSkipLabel
    render(<ChoiceCard data={noSkip} onAction={jest.fn()} />)
    expect(screen.queryByText('不需要加工项')).toBeNull()
    // 提交能力不受影响（前缀仍是协议默认值，AI 侧 _card_accepts_answer 按前缀识别）
    fireEvent.click(screen.getByText('压褶定型（米）'))
    expect(screen.getByText('完成选择（1）')).toBeTruthy()
  })

  it('提交文案后端驱动：自定义 prefix/label 生效（色号/规格等非加工项场景）', () => {
    const onAction = jest.fn()
    const custom: InteractiveData = {
      ...multiCard,
      multiSelectSubmitPrefix: '已选色号：',
      multiSelectSubmitLabel: '确定',
    }
    render(<ChoiceCard data={custom} onAction={onAction} />)
    fireEvent.click(screen.getByText('压褶定型（米）'))
    fireEvent.click(screen.getByText('确定（1）'))
    expect(onAction).toHaveBeenCalledWith('已选色号：压褶定型（米）')
  })

  it('单选卡（无 multiSelect）点第一项立即提交，且不渲染多选提交按钮（防回归）', () => {
    const onAction = jest.fn()
    render(<ChoiceCard data={baseChoice} onAction={onAction} />)
    fireEvent.click(screen.getByText('现代简约'))
    expect(onAction).toHaveBeenCalledTimes(1)
    expect(onAction).toHaveBeenCalledWith('现代简约')
    expect(screen.queryByText(/完成选择/)).toBeNull()
  })
})
