// case_ids: UI-081
//
// issue #5983（P2·权限·UI）：**列表页写按钮随权限显隐**。
// 判据 = 「写按钮**可用**（存在且未禁用） ⟺ 账号持有对应写权限码」。
//
// 病（issue #5983 的 12 格）：`/orders`、`/products`、`/inbound-orders` 三页的**页面守卫取的是读码**
// （`order:list` / `product:list` / `inbound:view` ⇒ 页面可进），而建单/建品入口（`/orders/new` 等）
// 的提交要写码（`order:create` / `product:create` / `inbound:create`）⇒ 无写码的岗位（客服/销售/财务…）
// 也能看到并点中按钮，**填完表单提交时才 403**（"白点一下"，按钮级权限未生效）。
//
// 正确范式（对照 `frontend/admin-web/src/app/(dashboard)/employees/page.tsx`）：
// `canWrite = hasPermission('employee:create')` ⇒ 无码时按钮**不渲染**。本文件按同一范式守三页。
//
// 🔴 每页**两条读数缺一不可**：① 无写码 ⇒ 按钮不在；② 有写码 ⇒ 按钮在。
// 只写 ① 会退化成「按钮永远不渲染」也照样绿的恒真断言（`migao-acceptance`「空断言」形态）；
// 只写 ② 则完全守不到本单的缺陷。
import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

// 登录态（按用例改写 permissions）—— 必须**按 zustand 选择器**返回：
// `usePermission()` 走 `useAuthStore(s => s.user)`，无视入参的整份 state mock 会让 `user` 恒 undefined
// ⇒ `has()` 恒 false ⇒ ① 恒真、② 恒假（实证见 tests/unit/pages/production-board.test.tsx 的注释）。
const authMock = vi.hoisted(() => ({
  state: {
    user: {
      id: '1',
      username: 'tester',
      name: '测试账号',
      permissions: ['*'] as string[],
      roles: [] as string[],
    },
  },
}))
vi.mock('@/store/auth', () => ({
  useAuthStore: (selector?: (s: unknown) => unknown) =>
    typeof selector === 'function' ? selector(authMock.state) : authMock.state,
}))

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  usePathname: () => '/orders',
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
}))

const mockGetOrders = vi.fn()
const mockGetProducts = vi.fn()
const mockGetCategories = vi.fn()
const mockInboundList = vi.fn()

vi.mock('@/lib/api', () => ({
  orderApi: { getOrders: (...a: unknown[]) => mockGetOrders(...a) },
  productApi: { getProducts: (...a: unknown[]) => mockGetProducts(...a) },
  categoryApi: { getCategories: (...a: unknown[]) => mockGetCategories(...a) },
  inboundOrderApi: { list: (...a: unknown[]) => mockInboundList(...a) },
}))

// 三个页面的重组件（表格）与按钮显隐无关 ⇒ 打桩，避免把无关依赖拖进本判据
vi.mock('@/components/orders', () => ({
  OrderTable: () => <div data-testid="order-table" />,
  CloseOrderModal: () => null,
  RemarkModal: () => null,
  RefundOrderModal: () => null,
}))
vi.mock('@/components/products/ProductTable', () => ({
  default: () => <div data-testid="product-table" />,
}))

import OrdersPage from '@/app/(dashboard)/orders/page'
import ProductsPage from '@/app/(dashboard)/products/page'
import InboundOrdersPage from '@/app/(dashboard)/inbound-orders/page'

// 真实岗位权限集（口径 = docs/wiki/RBAC.md「岗位（实际生效）」；租户侧是**快照**，此处只取判据相关的码）
// 客服 / 销售 / 财务 = issue #5983 点名「页面可进 + 按钮可点 + 账号无写权限」的三个岗位。
const ROLE_PERMS = {
  客服: ['dashboard:view', 'order:list', 'order:detail', 'customer:view', 'agent:session', 'processing:view', 'inbound:view', 'after_sales:view', 'knowledge:view'],
  销售: ['dashboard:view', 'product:list', 'order:list', 'order:detail', 'customer:view', 'processing:view'],
  财务: ['dashboard:view', 'order:list', 'order:detail', 'finance:view', 'processing:view', 'inbound:view', 'finance:create'],
  // 运营：三张写码都有（`order:create` / `product:create` / `inbound:create`，见 RBAC.md）
  运营: ['dashboard:view', 'order:list', 'order:create', 'product:list', 'product:create', 'inbound:view', 'inbound:create', 'processing:view'],
} as const

// ⚠️ 读码必须在场（否则连页面都进不去 —— 那是**路由守卫**的事，#5976/#5977 单独处理）：
// 本判据只裁「读码在场时，写按钮是否随写码显隐」。
const setPerms = (permissions: readonly string[]) => {
  authMock.state.user = { ...authMock.state.user, permissions: [...permissions], roles: [] }
}

beforeEach(() => {
  vi.clearAllMocks()
  mockGetOrders.mockResolvedValue({ data: { data: [], total: 0 } })
  mockGetProducts.mockResolvedValue({ data: { data: [], total: 0 } })
  mockGetCategories.mockResolvedValue({ data: { data: [] } })
  mockInboundList.mockResolvedValue({ data: { data: [] } })
  setPerms(['*'])
})

describe('#5983 列表页写按钮随权限显隐（判据：按钮可用 ⟺ 持有对应写码）', () => {
  it('判据 1：/orders —— 客服（有 order:list、无 order:create）看不到「新增订单」；运营（有码）看得到', () => {
    setPerms(ROLE_PERMS.客服)
    const first = render(<OrdersPage />)
    expect(screen.queryByRole('button', { name: /新增订单/ })).not.toBeInTheDocument()
    first.unmount()

    setPerms(ROLE_PERMS.运营)
    render(<OrdersPage />)
    expect(screen.getByRole('button', { name: /新增订单/ })).toBeInTheDocument()
  })

  it('判据 2：/products —— 销售（有 product:list、无 product:create）看不到「新增商品」；运营（有码）看得到', () => {
    setPerms(ROLE_PERMS.销售)
    const first = render(<ProductsPage />)
    expect(screen.queryByRole('button', { name: /新增商品/ })).not.toBeInTheDocument()
    first.unmount()

    setPerms(ROLE_PERMS.运营)
    render(<ProductsPage />)
    expect(screen.getByRole('button', { name: /新增商品/ })).toBeInTheDocument()
  })

  it('判据 3：/inbound-orders —— 财务（有 inbound:view、无 inbound:create）看不到「新建入库单」；运营（有码）看得到', () => {
    setPerms(ROLE_PERMS.财务)
    const first = render(<InboundOrdersPage />)
    expect(screen.queryByRole('button', { name: /新建入库单/ })).not.toBeInTheDocument()
    first.unmount()

    setPerms(ROLE_PERMS.运营)
    render(<InboundOrdersPage />)
    expect(screen.getByRole('button', { name: /新建入库单/ })).toBeInTheDocument()
  })

  it('判据 4（对照，防「一刀切隐藏」）：三个写码齐全但**只**缺对方写码时，各自按钮只受自己那把码控制', () => {
    // 只有 order:create（无 product:create / inbound:create）⇒ 只有订单页按钮在场
    setPerms(['order:list', 'product:list', 'inbound:view', 'order:create'])
    const a = render(<OrdersPage />)
    expect(screen.getByRole('button', { name: /新增订单/ })).toBeInTheDocument()
    a.unmount()

    const b = render(<ProductsPage />)
    expect(screen.queryByRole('button', { name: /新增商品/ })).not.toBeInTheDocument()
    b.unmount()

    const c = render(<InboundOrdersPage />)
    expect(screen.queryByRole('button', { name: /新建入库单/ })).not.toBeInTheDocument()
    c.unmount()
  })
})
