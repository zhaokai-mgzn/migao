// case_ids: HR-013
// @vitest-environment jsdom
import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import type { TreeNode } from '../../../src/components/ui/TreeCheckbox'
import { TreeCheckbox } from '../../../src/components/ui/TreeCheckbox'
import * as TreeCheckboxModule from '../../../src/components/ui/TreeCheckbox'

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

// ==================== #6083: 同码多节点（same-code multi-node） ====================
// #5699/#5291 设计：后端菜单树允许同码多节点（workspace 组 2 个 dashboard:view、
// production-center 组 4 个 production:view）。前端不得假设 code 唯一：
//   ① key 只用 code ⇒ React「Encountered two children with the same key」（/employees 控制台 6 条报错）
//   ② 徽标 labelMap 后写覆盖先写 ⇒ dashboard:view 徽标显示「每日简报」而非「经营看板」
describe('TreeCheckbox #6083 同码多节点', () => {
  const SAME_CODE_TREE: TreeNode[] = [
    { code: 'workspace', label: '工作台', children: [
      { code: 'dashboard:view', label: '经营看板' },
      { code: 'dashboard:view', label: '每日简报' },
    ]},
    { code: 'production-center', label: '生产中心', children: [
      { code: 'production:view', label: '生产看板' },
      { code: 'production:view', label: '加工项管理' },
      { code: 'production:view', label: '工艺配置' },
      { code: 'production:view', label: '计件工资' },
    ]},
  ]
  const ALL_LEAF_LABELS = ['经营看板', '每日简报', '生产看板', '加工项管理', '工艺配置', '计件工资']

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  it('#6083: 同码多节点渲染不触发 React duplicate-key 告警，且 6 个 label 全部渲染', () => {
    // spy 必须在 render 之前装上（duplicate-key 告警在 render 期间经 console.error 发出）
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    render(<TreeCheckbox tree={SAME_CODE_TREE} selected={[]} onChange={() => {}} />)
    ALL_LEAF_LABELS.forEach(label => {
      expect(screen.getByText(label)).toBeInTheDocument()
    })
    const dupKeys = errorSpy.mock.calls
      .map(args => args.map(String).join(' '))
      .filter(msg => msg.includes('Encountered two children with the same key'))
    expect(dupKeys).toEqual([])
  })

  it('#6083: treeNodeKey 由 code+label 派生唯一 key（同码不同 label ⇒ key 不同，幂等）', () => {
    const keyA = TreeCheckboxModule.treeNodeKey({ code: 'dashboard:view', label: '经营看板' })
    const keyB = TreeCheckboxModule.treeNodeKey({ code: 'dashboard:view', label: '每日简报' })
    expect(keyA).not.toBe(keyB)
    expect(keyA).toContain('dashboard:view')
    // 幂等：同输入同输出（重渲染时 key 稳定，不丢挂载状态）
    expect(TreeCheckboxModule.treeNodeKey({ code: 'dashboard:view', label: '经营看板' })).toBe(keyA)
  })

  it('#6083 类级守卫: 同码勾选语义不回退 —— 勾选其一上抛共享 code，同码节点一起高亮', () => {
    const onChange = vi.fn()
    const { rerender } = render(<TreeCheckbox tree={SAME_CODE_TREE} selected={[]} onChange={onChange} />)
    fireEvent.click(cb('经营看板'))
    // 同码 = 同权限：上抛的是共享 code
    expect(onChange).toHaveBeenCalledWith(['dashboard:view'])
    rerender(<TreeCheckbox tree={SAME_CODE_TREE} selected={['dashboard:view']} onChange={onChange} />)
    // 同码各节点一起高亮（该语义是正确设计，禁因修 key 而改坏）
    expect(cb('经营看板').checked).toBe(true)
    expect(cb('每日简报').checked).toBe(true)
  })
})

// ==================== issue #6759: 手机端可见面标注 ====================
// 真值只在服务端：`GET /api/admin/menus` 的节点带 `mobileTitles`（由 MobileSurfaces 派生）。
// 组件**只渲染服务端给的**：有就追加 ` · 手机端：X`，没有（缺字段 / 空数组）**一个字符都不追加**。
// 语料里的手机端面名是**判据夹具**（模拟服务端下发），不是前端映射表。
describe('TreeCheckbox #6759 手机端可见面标注', () => {
  const MOBILE_TREE: TreeNode[] = [
    { code: 'production-center', label: '生产管理', children: [
      { code: 'processing:view', label: '智能派单', mobileTitles: ['智能派单'] },
      { code: 'production:view', label: '生产看板', mobileTitles: [] },
    ]},
    { code: 'inventory-center', label: '仓储与物料', children: [
      { code: 'inbound:view', label: '入库单', mobileTitles: ['入库过账'] },
      // 同一码挂两个手机端面 ⇒ 用 `、` 连接
      { code: 'dashboard:view', label: '经营看板', mobileTitles: ['数据'] },
      { code: 'order:list', label: '发货单' },
    ]},
  ]

  it('#6759 判据 1: 有手机端面的码渲染 ` · 手机端：X`；空数组 / 缺字段的码**不渲染**', () => {
    render(<TreeCheckbox tree={MOBILE_TREE} selected={[]} onChange={() => {}} />)
    // 有面 ⇒ 逐字渲染（含前置分隔符，与员工管理页一致）
    expect(screen.getByTestId('tree-mobile-processing:view')).toHaveTextContent('· 手机端：智能派单')
    expect(screen.getByTestId('tree-mobile-inbound:view')).toHaveTextContent('· 手机端：入库过账')
    expect(screen.getByTestId('tree-mobile-dashboard:view')).toHaveTextContent('· 手机端：数据')
    // 空数组 / 缺字段 ⇒ 零标注（负控：不是「一律加个空标注」）
    expect(screen.queryByTestId('tree-mobile-production:view')).toBeNull()
    expect(screen.queryByTestId('tree-mobile-order:list')).toBeNull()
  })

  it('#6759 判据 2: 多个手机端面用 `、` 连接（顺序 = 服务端给的顺序）', () => {
    const tree: TreeNode[] = [
      { code: 'g', label: '组', children: [
        { code: 'production:view', label: '计件工资', mobileTitles: ['计件工资报表', '生产待办'] },
      ]},
    ]
    render(<TreeCheckbox tree={tree} selected={[]} onChange={() => {}} />)
    expect(screen.getByTestId('tree-mobile-production:view'))
      .toHaveTextContent('· 手机端：计件工资报表、生产待办')
  })

  it('#6759 判据 3（对照读数）: 服务端不下发 mobileTitles ⇒ 树上零改动（标注不是前端自造的）', () => {
    const bare: TreeNode[] = [
      { code: 'production-center', label: '生产管理', children: [
        { code: 'processing:view', label: '智能派单' },
      ]},
    ]
    render(<TreeCheckbox tree={bare} selected={[]} onChange={() => {}} />)
    expect(screen.getByText('智能派单')).toBeInTheDocument()
    expect(screen.queryAllByText(/手机端：/)).toHaveLength(0)
    expect(screen.queryByTestId(/^tree-mobile-/)).toBeNull()
  })
})
