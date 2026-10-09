// case_ids: PP-006, PG-040, PR-106
// PP-006（加工项目录 CRUD / 计价方式）+ PG-040（加工费**组合**定价）在 issue #4490 合并后的**单页形态**：
// 「加工项管理」(/processing) 与「加工费管理」(/production/processing-fees) 合并为单一菜单入口
// /production/processing（用户 2026-09-19 **规格修订**后归**商品管理**组；#4542 起菜单名 =「加工项管理」）。
//
// 本文件钉的是**合并本身的判据**（两半能力各自的断言在 processing.test.tsx / processing-fees.test.tsx）：
// ① 菜单结构（用户 2026-09-19 **规格修订**：合并后的菜单放**商品管理**大菜单下）：
//    **商品管理组含合并项**且路径/权限码正确；**生产管理组不含它**（issue #5034 后本组为四项）；
//    全站不再有指向 /processing 或 /production/processing-fees 的菜单项，也不再有独立的
//    「加工费管理」项（#4542 后菜单名 =「加工项管理」，只有一项）；
// ② 两个旧路径都**重定向**到新入口（旧深链不 404）；加工费旧路径带 `?tab=fees` 直达第二栏；
// ③ 页面**两个 tab**（加工项 / 加工费组合），默认落在「加工项」，切换后内容**互斥**（不平铺）；
// ④ **切 tab 不丢状态**（两栏 state 挂在同一组件上：加工项表单草稿 / 加工费就地改价草稿）；
// ⑤ `?tab=fees` 直达（后端未定价提示里的旧链接走这条）。
// 反 placeholder：断言落**真实数据行**、**重定向目标**与**互斥的 DOM 形态**，不断言「页面存在」。
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const mockGetProcessingItems = vi.fn()
const mockGetProcessingCategories = vi.fn()
const mockGetFeeCombinations = vi.fn()
const mockGetFeeGaps = vi.fn()
const mockRedirect = vi.fn()
/** `?tab=` 直达（默认无参 ⇒ 落在「加工项」） */
let mockSearch = ''

vi.mock('@/lib/api', () => ({
  processingItemApi: {
    getProcessingItems: (...args: unknown[]) => mockGetProcessingItems(...args),
    createProcessingItem: vi.fn(),
    updateProcessingItem: vi.fn(),
    deleteProcessingItem: vi.fn(),
  },
  processingCategoryApi: {
    getProcessingCategories: (...args: unknown[]) => mockGetProcessingCategories(...args),
    createProcessingCategory: vi.fn(),
  },
  productionApi: {
    getFeeCombinations: (...args: unknown[]) => mockGetFeeCombinations(...args),
    getFeeGaps: (...args: unknown[]) => mockGetFeeGaps(...args),
    createFeeCombination: vi.fn(),
    updateFeeCombination: vi.fn(),
    disableFeeCombination: vi.fn(),
  },
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

vi.mock('next/navigation', () => ({
  redirect: (...args: unknown[]) => mockRedirect(...args),
  useSearchParams: () => new URLSearchParams(mockSearch),
}))

import ProcessingPage from '@/app/(dashboard)/production/processing/page'
import ProcessingRedirectPage from '@/app/(dashboard)/processing/page'
import ProcessingFeesRedirectPage from '@/app/(dashboard)/production/processing-fees/page'
import { menuGroups, standaloneTopItems, standaloneItems } from '@/config/menu'

const ok = (data: unknown) => ({ data: { success: true, data } })

const ITEMS = {
  total: 2,
  items: [
    { id: 'pi-1', name: '韩褶', categoryId: 'cat-1', categoryName: '窗帘加工', unit: '米', status: 'active' },
    { id: 'pi-2', name: '打孔', categoryId: 'cat-1', categoryName: '窗帘加工', unit: '米', status: 'active' },
  ],
}

const COMBINATIONS = {
  total: 1,
  combinations: [
    { id: 'fc-1', composition_key: '打孔+韩褶', items: ['韩褶', '打孔'], unit_price: 12, unit: '元/米', status: 'active', source: '实证' },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
  mockSearch = ''
  mockGetProcessingItems.mockResolvedValue(ok(ITEMS))
  mockGetProcessingCategories.mockResolvedValue(ok([{ id: 'cat-1', name: '窗帘加工' }]))
  mockGetFeeCombinations.mockResolvedValue(ok(COMBINATIONS))
  mockGetFeeGaps.mockResolvedValue(ok({ unpriced_combinations: [], unpriced_combination_total: 0 }))
})

const productionGroup = () => menuGroups.find((g) => g.key === 'production-center')
const inventoryGroup = () => menuGroups.find((g) => g.key === 'inventory-center')
const productGroup = () => menuGroups.find((g) => g.key === 'product-center')

// ────────────────────────── ① 菜单结构（侧边栏 IA） ──────────────────────────

describe('菜单结构（#5778 用户裁定：加工项管理归**生产管理**组；`product-center` 组撤销、商品列表升为一级项）', () => {
  // ⚠️ #5877 / 2026-10-06：该一级项现名**「商品管理」**，且渲染在**所有分组之后**（原为「工作台组之后」、
  // 更早为所有分组之前）—— 本文件的判据只看**归属**（它不在任何组里），故不需改断言；此处更正表述以免自相矛盾。
  // 🔴 2026-10-09（issue #6580，用户裁定「移除加工项管理和工艺配置这两个菜单」）**改判**：
  // 本判据原断言「加工项管理**是**生产管理组的组内第一条」；现在它**不再是菜单项**
  //（功能体并入一级项「企业基础设置」`/settings` 页内的配置域）⇒ 判据反转为**不存在**：
  // 全站（三处菜单数组）都不得再有指向 `/production/processing` 或 `/production/routings` 的菜单项。
  // ⚠️ 断言强度**不降**：原断言钉「这条存在且字段正确」，新断言钉「这条不存在 + 两个路径仍由页面承载」
  //（页面存在性由文件头的 `PAGES`/路由断言与本文件的 tab 用例承担，见下）。
  it('「加工项管理」不再是菜单项（#6580）：三处菜单数组都不再有 /production/processing', () => {
    const allItems = [
      ...menuGroups.flatMap((g) => g.children),
      ...standaloneTopItems,
      ...standaloneItems,
    ]
    expect(allItems.find((c) => c.key === 'processing')).toBeUndefined()
    expect(allItems.find((c) => c.path === '/production/processing')).toBeUndefined()
    expect(allItems.find((c) => c.path === '/production/routings')).toBeUndefined()
    // #5778：原「商品与加工项」组已撤销（商品列表升为**一级项**，现名「商品管理」）
    expect(productGroup()).toBeUndefined()
    // 生产管理组（#6580 起 **3 项**；两项已移除）
    expect(productionGroup()!.children.map((c) => c.key)).toEqual([
      'production-board', 'production-pool', 'production-piecework',
    ])
  })

  it('生产管理组现为 **3 项**（#6580 移除两个菜单项）；面料三项仍在「仓储与物料」组（#5778 + issue #5271）', () => {
    // 🔴 #6580：本组由 5 项收拢为 3 项（「加工项管理」「工艺配置」菜单项已移除、功能体并入
    // 一级项「企业基础设置」页）；而面料进出与消耗（入库单 / 余料台账 / 省料看板）
    // 仍归**「仓储与物料」**组（issue #5271 的拆组保留，本轮不动）。
    // 断言的是**路径清单**（顺序敏感）。
    const productionPaths = productionGroup()!.children.map((c) => c.path)
    expect(productionPaths).toEqual([
      '/production',
      '/production/pool',
      '/production/piecework',
    ])
    // 反向：面料三项**不得**在本科目里（它们属「仓储与物料」）
    expect(productionPaths).not.toContain('/inbound-orders')
    expect(productionPaths).not.toContain('/production/remnants')
    expect(productionPaths).not.toContain('/production/saving-board')
    // issue #5291：生产看板/工艺配置/计件工资 = 读码 production:view；
    // 🔴 issue #5699（P4）：智能派单 = 该页读码 processing:view（节点码 ≡ 页面第一屏读码）；
    // #5778：加工项管理 = production:view。
    expect(productionGroup()!.children.map((c) => c.permissionCode)).toEqual([
      'production:view',    // 生产看板
      'processing:view',    // 智能派单
      'production:view',    // 计件工资
    ])
    // 拆出去的三项落在「仓储与物料」组，且**权限码不统一是有意的**：
    // 入库单 = inbound:view（仓储动作，仓管/财务要看入库单却不需要 processing:manage）、
    // 余料台账 = processing:manage（`RemnantController` 类级码）、
    // 🔴 省料看板 = product:list（issue #5699 P4：该页两个读端点在 `StockBatchController` 上是方法级 product:list）。
    // #5939：入库单之后新增「发货单」（`/shipments`，码 = 既有 `order:list`）——
    // 出口单据与入口单据对称，仍与「生产管理」组无关。
    // #6404：组尾再加「库存明细」（`/stock-ledger`，同取 `product:list`）。
    expect(inventoryGroup()!.children.map((c) => c.path)).toEqual([
      '/inbound-orders',
      '/stock-ledger',
      '/shipments',
      '/production/remnants',
      '/production/saving-board',
    ])
    // #5939：发货单取**既有** order:list（不新造 shipment:view —— 新码今天没有岗位持有 ⇒ 菜单对
    // 所有人不可见，见 #4203 同族坑）。
    expect(inventoryGroup()!.children.map((c) => c.permissionCode)).toEqual([
      'inbound:view',
      'product:list',   // 库存明细（#6404：同取既有 product:list ⇒ 零授权 delta；2026-10-06 起紧随入库单）
      'order:list',     // 发货单（#5939：取既有 order:list ⇒ 与订单列表同码、零授权 delta）
      'processing:manage',
      'product:list',   // 省料看板（#5699 P4）
    ])
    // 全站不再有指向两个旧路径的菜单项，也不再有独立的「加工费管理」项；
    // ⚠️ 「加工项管理」是**合并后的唯一入口**（#4542 起菜单名）⇒ **必须**在菜单里，不得写成负断言。
    const allPaths = menuGroups.flatMap((g) => g.children.map((c) => c.path))
    expect(allPaths).not.toContain('/processing')
    expect(allPaths).not.toContain('/production/processing-fees')
    const allNames = menuGroups.flatMap((g) => g.children.map((c) => c.name))
    expect(allNames).not.toContain('加工费管理')
    // #4542：旧菜单名（#4490 的合并名，U+52A0 U+5DE5 U+9879 U+4E0E U+52A0 U+5DE5 U+8D39）
    // 已不存在 —— 用码点构造，避免在源码里再写出该旧名（issue #4542 判据 1：零命中）
    expect(allNames).not.toContain('\u52a0\u5de5\u9879\u4e0e\u52a0\u5de5\u8d39')
    // 🔴 #6580：菜单项「加工项管理」**已移除** ⇒ 组内命中数 1 → **0**（反向断言，强度不降：
    // 从「恰好有一条」变成「一条都没有」；旧路径不 404 由下面的重定向用例承担）。
    expect(allNames.filter((n) => n === '加工项管理')).toHaveLength(0)
    // 一项不少不减：组内项 21 → **18** 项（#6580 移除生产管理组的两个菜单项；
    // #5778/#5939「+发货单」/#6404「+库存明细」的历次增减见 menu-nav.test.ts）
    expect(menuGroups.flatMap((g) => g.children.map((c) => c.key))).toHaveLength(18)
    expect(allNames).toHaveLength(18)
  })
})

// ────────────────────────── ② 旧路径重定向 ──────────────────────────

describe('两个旧路径都重定向到新入口（旧深链不 404）', () => {
  it('旧「加工项管理」/processing → /production/processing', () => {
    ProcessingRedirectPage()
    expect(mockRedirect).toHaveBeenCalledTimes(1)
    expect(mockRedirect).toHaveBeenCalledWith('/production/processing')
  })

  it('旧「加工费管理」/production/processing-fees → /production/processing?tab=fees（直达定价面）', () => {
    ProcessingFeesRedirectPage()
    expect(mockRedirect).toHaveBeenCalledTimes(1)
    expect(mockRedirect).toHaveBeenCalledWith('/production/processing?tab=fees')
  })
})

// ────────────────────────── ③④⑤ 两个 tab ──────────────────────────

describe('合并页 /production/processing（两个 tab，不平铺）', () => {
  it('两个 tab 存在且默认落在「加工项」；切换后内容互斥（不是两个域堆在一屏）', async () => {
    render(<ProcessingPage />)
    await waitFor(() => expect(screen.getByTestId('processing-tabs')).toBeInTheDocument())

    const itemsTab = screen.getByTestId('processing-tab-items')
    const feesTab = screen.getByTestId('processing-tab-fees')
    // tab 标题是**用户能一眼懂的业务名**（不是技术名）
    expect(itemsTab).toHaveTextContent('加工项')
    expect(feesTab).toHaveTextContent('加工费组合')
    expect(itemsTab).toHaveAttribute('data-state', 'active')
    expect(feesTab).toHaveAttribute('data-state', 'inactive')

    // 默认：加工项列表在、「加工费组合」面不在（可见）
    await waitFor(() => expect(screen.getByTestId('processing-items-total')).toHaveTextContent('2'))
    expect(screen.getByTestId('processing-item-pi-1')).toHaveTextContent('韩褶')
    // 🔴 #6585：两栏的功能体各成**独立面板**，且**都保持挂载**（非激活那个 `hidden`）——
    // 「切 tab 不丢状态」（下一条用例）靠的就是这一点。⇒ 互斥判据从「不在 DOM 里」改判为
    // 「**不可见**」：jsdom 里 `queryByTestId` **不**过滤 hidden 元素，旧写法在新形态下必红；
    // 而断言强度**不降反升**（旧写法只判「没挂载」，根本判不了可见性）。
    expect(screen.queryByTestId('fee-combinations')).not.toBeVisible()
    expect(screen.queryByTestId('fee-gaps')).not.toBeVisible()

    await userEvent.click(feesTab)
    expect(feesTab).toHaveAttribute('data-state', 'active')
    expect(screen.queryByTestId('processing-items')).not.toBeVisible()
    await waitFor(() => expect(screen.getByTestId('fee-combinations-total')).toHaveTextContent('1'))
    expect(screen.getByTestId('fee-combination-fc-1')).toHaveTextContent('¥12.00')
    // 未定价缺口仍在（#4386 交付物不退化）
    expect(screen.getByTestId('fee-gaps')).toBeInTheDocument()
  })

  it('切 tab **不丢状态**：加工项表单草稿与加工费就地改价草稿，切走再切回都还在', async () => {
    render(<ProcessingPage />)
    await waitFor(() => expect(screen.getByTestId('processing-items-total')).toHaveTextContent('2'))

    // ① 加工项：打开新增弹窗并填名称
    await userEvent.click(screen.getByTestId('processing-item-new'))
    const nameInput = screen.getByPlaceholderText('请输入加工项名称（最多20个字符）')
    await userEvent.type(nameInput, '定型')

    // ② 切到加工费组合：进入 fc-1 的就地改价
    await userEvent.click(screen.getByTestId('processing-tab-fees'))
    await waitFor(() => expect(screen.getByTestId('fee-combination-fc-1')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('fee-combination-edit-fc-1'))
    const priceInput = screen.getByTestId('fee-combination-edit-price-fc-1')
    await userEvent.clear(priceInput)
    await userEvent.type(priceInput, '13.5')

    // ③ 切回加工项：表单草稿仍在
    await userEvent.click(screen.getByTestId('processing-tab-items'))
    expect(screen.getByPlaceholderText('请输入加工项名称（最多20个字符）')).toHaveValue('定型')

    // ④ 再切回加工费组合：改价草稿仍在（两栏 state 挂在同一组件上，不随 tab 重置）
    await userEvent.click(screen.getByTestId('processing-tab-fees'))
    expect(screen.getByTestId('fee-combination-edit-price-fc-1')).toHaveValue('13.5')
  })

  it('`?tab=fees` 直达「加工费组合」（旧 /production/processing-fees 的深链意图不丢）', async () => {
    mockSearch = 'tab=fees'
    render(<ProcessingPage />)

    await waitFor(() => expect(screen.getByTestId('processing-tab-fees')).toHaveAttribute('data-state', 'active'))
    expect(screen.getByTestId('fee-combinations')).toBeInTheDocument()
    // #6585：非激活面板仍挂载但**不可见**（同上一条的互斥判据口径）
    expect(screen.queryByTestId('processing-items')).not.toBeVisible()
  })

  it('加工项加载失败：只在「加工项」tab 给可读提示 + 重试，另一栏照常渲染（不整页白屏）', async () => {
    // 🔴 #6585：两栏各拉各的（加工费面板的**勾选源目录**也走这个端点）⇒ 必须让**两次**调用都失败，
    // 才能判到「同一端点故障 ⇒ 两栏都说『加载失败』、都不说『目录为空』」。旧写法
    // `mockRejectedValueOnce` 只喂失败给 board 的那一次，在新形态下第二栏会拿到成功响应 ⇒ 判据漏。
    mockGetProcessingItems.mockRejectedValue(new Error('500'))
    render(<ProcessingPage />)

    await waitFor(() => expect(screen.getByTestId('processing-items-error')).toHaveTextContent('加工项加载失败'))
    // 加工费半边不受影响（各拉各的，一条失败不吞整页）
    await userEvent.click(screen.getByTestId('processing-tab-fees'))
    await waitFor(() => expect(screen.getByTestId('fee-combinations-total')).toHaveTextContent('1'))
    // 勾选源目录与「加工项」tab 是**同一端点** ⇒ 它失败**不得**说成「目录为空」
    // （说成空会让商家去建一个其实已存在的加工项 —— 合并后新引入的形态；两栏同端点同故障，必须同词）
    await userEvent.click(screen.getByTestId('fee-combination-new'))
    expect(screen.getByTestId('fee-combination-catalog-empty')).toHaveTextContent('加工项目录加载失败')
    await userEvent.click(screen.getByRole('button', { name: '取消' }))

    // 重试后渲染出真实数据（错误态消失）
    mockGetProcessingItems.mockResolvedValue(ok(ITEMS))
    await userEvent.click(screen.getByTestId('processing-tab-items'))
    await userEvent.click(screen.getByTestId('processing-items-retry'))
    await waitFor(() => expect(screen.getByTestId('processing-items-total')).toHaveTextContent('2'))
    expect(screen.queryByTestId('processing-items-error')).not.toBeInTheDocument()
    expect(screen.getByTestId('processing-item-pi-2')).toHaveTextContent('打孔')
  })

  it('两半能力**同页都在**：加工项 CRUD 入口 + 加工分类抽屉 + 加工费组合定价与缺口', async () => {
    render(<ProcessingPage />)
    await waitFor(() => expect(screen.getByTestId('processing-items-total')).toHaveTextContent('2'))

    // 加工项半边：新增入口 + 行内编辑/删除（CRUD）+ 分类抽屉
    expect(screen.getByTestId('processing-item-new')).toHaveTextContent('新增加工项')
    const row = screen.getByTestId('processing-item-pi-1')
    expect(within(row).getByText('编辑')).toBeInTheDocument()
    expect(within(row).getByText('删除')).toBeInTheDocument()
    // 加工分类（次区走抽屉，不占主列表）
    expect(screen.queryByTestId('processing-categories-list')).not.toBeInTheDocument()
    await userEvent.click(screen.getByTestId('processing-categories-open'))
    expect(await screen.findByTestId('processing-categories-list')).toHaveTextContent('窗帘加工')

    // 加工费半边：新建组合入口 + 缺口区（辅助告警）
    await userEvent.click(screen.getByTestId('processing-tab-fees'))
    expect(screen.getByTestId('fee-combination-new')).toHaveTextContent('新建组合')
    expect(screen.getByTestId('fee-gaps-total')).toBeInTheDocument()
  })
})

// ────────────────────────── 顶层分组顺序（issue #4510） ──────────────────────────

describe('顶层分组顺序（issue #4510 立判据；issue #5271 按业务动线重排）', () => {
  it('完整序列 = 工作台 → 客户服务 → 交易管理 → 生产管理 → 仓储与物料 → 组织管理（#5778：6 组）', () => {
    // ⚠️ 断言**完整序列**，不是只断言相邻两项 —— 否则「把生产管理挪到别处」这类改动会漏网。
    // （实测：本单只做重排时，全量 157 文件 2092 条**一条都没红** ⇒ 顺序此前**无人守**，
    //   这条判据是本单新加的承重面。）
    // issue #5271 变化：组 key `production` → `production-center`；「商品管理」→「商品与加工项」；
    // 「订单管理」+「客户管理」→「交易管理」（`customer-center` 组消失）；**新建** `inventory-center`。
    expect(menuGroups.map((g) => g.key)).toEqual([
      'workspace',
      'customer-service',
      'trade-center',
      'production-center',
      'inventory-center',
      'org-center',
    ])
    expect(menuGroups.map((g) => g.name)).toEqual([
      '工作台',
      '客户服务',
      '交易管理',
      '生产管理',
      '仓储与物料',
      '组织管理',
    ])
    // 旧 IA 的钉子（防止把旧组名/旧 key 再写回来）
    expect(menuGroups.map((g) => g.key)).not.toContain('customer-center')
    expect(menuGroups.map((g) => g.key)).not.toContain('production')
    // 🔴 #5778：`product-center` / `smart-customer-service` 两组已撤销/改判 —— 不得长回来
    expect(menuGroups.map((g) => g.key)).not.toContain('product-center')
    expect(menuGroups.map((g) => g.key)).not.toContain('smart-customer-service')
    expect(menuGroups.map((g) => g.name)).not.toContain('商品与加工项')
    expect(menuGroups.map((g) => g.name)).not.toContain('智能客服')
    expect(menuGroups.map((g) => g.name)).not.toContain('订单管理')
    expect(menuGroups.map((g) => g.name)).not.toContain('客户管理')
  })

  it('相对位置关系（承重面：拆组与并组后的三处相邻约束）', () => {
    const keys = menuGroups.map((g) => g.key)
    // 生产管理在交易管理之下（动线：谁下单 → 单到哪 → 售后 → 收款 → 加工执行）
    expect(keys.indexOf('production-center')).toBeGreaterThan(keys.indexOf('trade-center'))
    // 仓储与物料紧随生产管理之后（面料进出从生产管理拆出，紧挨着放）
    expect(keys.indexOf('inventory-center')).toBe(keys.indexOf('production-center') + 1)
    // 组织管理仍是**最后一个分组**
    expect(menuGroups[menuGroups.length - 1].key).toBe('org-center')
    // #5778：客户服务在交易管理**之上**（先服务客户 → 再谈交易）
    expect(keys.indexOf('customer-service')).toBeLessThan(keys.indexOf('trade-center'))
    // 面非空自检：6 组（不是解析失灵造成的空序列）
    expect(menuGroups).toHaveLength(6)
  })

  it('通知中心仍是 `standaloneItems`（渲染在分组之后）—— 「最下面」= 最后一个**分组**', () => {
    // Sidebar 渲染顺序：menuGroups → standaloneItems ⇒ 通知中心作为一级独立项仍在组织管理下面
    // （既有形态，本单不改）。显式钉住这个口径，避免将来被误读成「组织管理没放到底」。
    expect(menuGroups[menuGroups.length - 1].key).toBe('org-center')
    expect(menuGroups.map((g) => g.key)).not.toContain('notifications')
  })
})
