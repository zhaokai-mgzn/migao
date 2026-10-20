// @vitest-environment jsdom
// case_ids: UI-103, UI-130
/**
 * `SearchPanel` 共享原语判据（issue #7007）。
 *
 * ## 为什么这个文件存在（两重理由，都要写清楚）
 *
 * ① **实例判据**：本原语是「筛选区在仓里有三种互不相同的形态」这条病根的唯一修法 ——
 *    `SearchBar`（`flex flex-wrap` + `min-w-[200px]`，冷灰底）/ 手写 `grid-cols-1 md:grid-cols-2`
 *    （标签顶置）/ 订单页那版手写 `grid-cols-1 md:grid-cols-2 2xl:grid-cols-4`（标签左置）。
 *    用户 2026-10-16 反馈「订单页精美、其它页平淡」，可归因差异之一就是它。
 *    故判据钉的是**版式不变量 + 交互契约**（行行对齐的机制 / 按钮行的分层），不是实现细节。
 * ② **CI QA Growth Gate**：新增的组件源码必须有同名测试，且闸门按**精确路径**查存在性
 *    （`frontend/admin-web/src/components/(.+/)?(\w+)\.tsx` → `tests/unit/components/{2}.test.ts`）
 *    ⇒ 只有 `tests/unit/components/SearchPanel.test.ts` 这一个文件名算数。
 *
 * ## 类名判据一律**按 token** 断言（不是 `toContain` 子串）
 *
 * 实测踩过（本文件的自我红证矩阵）：`expect(className).toContain('w-[4.5em]')` 对
 * **`min-w-[4.5em]`** 也成立 —— 而 `min-w` 恰恰就是被修的病灶（`min-w` 只是下限、实际宽度
 * 仍随 label 内容变 ⇒ 各格 label 宽度不同、行间起点参差）⇒ 子串写法**当场假绿**。
 * 故本文件统一用 `tokens()`（把 className 切词后 `toContain` 精确 token）。
 *
 * ## 红证矩阵（**已执行**，不是纸上声明）
 *
 * 把 `src/components/ui/SearchPanel.tsx` 复制到 `/tmp` 后逐条注入变异、跑本文件（原仓文件零改动）。
 * 基线（未变异）全绿 ⇒ 变异真的注入了 `/tmp` 的副本：
 *
 * | 变异 | 转红判据 |
 * |---|---|
 * | 删掉 `testId = 'search-area'` 默认值 | 判据 1（页面级判据全靠这个锚定位搜索区） |
 * | grid 退回单档 `grid-cols-1` | 判据 2（行与行不再天然对齐） |
 * | `field.span === 2` 写成真值判断 | 判据 3（`span: 1` 的格子被误跨轨） |
 * | `w-[4.5em]` 退回 `min-w-[4.5em]` | 判据 4（**本仓实测过的假绿形态**，token 断言才拦得住） |
 * | 按钮行去掉 `col-span-full` | 判据 5 |
 * | `onReset &&` 条件去掉 | 判据 6（没传回调也渲染出按钮） |
 * | 刷新外层 `span` 去掉 `border-l` | 判据 7（列表动作与筛选动作的分层没了） |
 * | 去掉 `disabled={loading}` | 判据 8（防重复提交失效） |
 * | 写成 `disabled={true}`（恒禁用） | 判据 8 的反面（两态必须由 `loading` 驱动） |
 * | 外层 `cn(…)` 吞掉调用方的 `className` | 判据 11（调用方要加外层修饰时不被迫退回手写 `div`） |
 * | `SEARCH_CONTROL_CLASS` 里 `border-neutral-300` → `gray-300` | 判据 9 |
 * | `h-9` 旁边多加一个 `min-h-9` / `w-full` 旁边多加 `max-w-full` | 判据 9（token 断言拦超集 token） |
 * | 原语不渲染传入的 `control` | 判据 10（原语只管版式） |
 *
 * ## 边界（如实登记，§19.1）
 *
 * - 判据 2/4/5/9 钉的是**类名 token**（版式不变量），不是**几何读数**：`h-9` 是否真等于 36px、
 *   label 起点是否真对齐、按钮行是否真在右侧，jsdom 量不到 ⇒ 真几何由
 *   `frontend/admin-web/scripts/design-baseline-geometry-probe.mjs` 与 `migao-dev-flow` §15.7
 *   的真浏览器读图覆盖；
 * - 判据只针对**本原语**，不判「哪个页面该迁移到它」—— 那是产品口径。
 *
 * ⚠️ 文件名是 `.test.ts`（Growth Gate 按精确路径查存在性，只认 `.ts`）⇒ 本文件**不能用 JSX**，
 * 一律 `React.createElement`。仓内先例：`tests/unit/pages/after-sales-detail.test.tsx`。
 */
import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { createElement as h } from 'react'
import SearchPanel, { SEARCH_CONTROL_CLASS, type SearchFieldSpec } from '@/components/ui/SearchPanel'

vi.mock('lucide-react', async (importOriginal) =>
  (await import('../helpers/lucide-mock')).lucideMock((await importOriginal()) as Record<string, unknown>))

/** className → token 集合。**必须按 token 断言**：子串写法对超集 token 会假绿（见文件头）。 */
const tokens = (el: { className: string }): string[] => el.className.split(/\s+/).filter(Boolean)

/** 控件由**调用方**渲染（原语无状态）⇒ 判据里也用调用方的形状造 control。 */
const control = (name: string, extra: Record<string, unknown> = {}) =>
  h('input', { 'aria-label': name, readOnly: true, ...extra })

/** 三格：未给 `span` / `span: 1`（显式）/ `span: 2` —— 判据 3 的双向都要有样本。 */
const fields = (): SearchFieldSpec[] => [
  { key: 'keyword', label: '客户名称', control: control('客户名称输入') },
  { key: 'phone', label: '手机号', control: control('手机号输入'), span: 1 },
  { key: 'created', label: '下单时间', control: control('下单时间输入'), span: 2 },
]

/** 字段单元格 = `<label>` 的直接父节点（原语里就是那个 `flex items-center gap-2 min-w-0`）。 */
const cellOf = (labelText: string): HTMLElement => {
  const label = screen.getByText(labelText)
  return label.parentElement as HTMLElement
}

describe('SearchPanel —— 列表页筛选区共享原语（issue #7007）', () => {
  it('data-testid 默认 `search-area`，显式 testId 覆盖它 —— 页面级判据的锚', () => {
    const { unmount } = render(h(SearchPanel, { fields: [], onSearch: () => {} }))
    // 红证（已执行）：删掉 `testId = 'search-area'` 这个默认值 ⇒ 当场红 ——「全仓页面级判据以它定位搜索区」。
    const root = screen.getByTestId('search-area')
    expect(root.tagName).toBe('DIV')
    unmount()

    render(h(SearchPanel, { fields: [], onSearch: () => {}, testId: 'orders-search-area' }))
    expect(screen.getByTestId('orders-search-area')).toBeTruthy()
    // 覆盖的口径是「替换」而不是「两者并存」：透传后默认锚不得残留（否则同页会有两个搜索区锚）。
    expect(screen.queryByTestId('search-area')).toBeNull()
  })

  it('单一响应式 grid：三条轨道挂在同一个容器上，字段单元格带 min-w-0', () => {
    const { container } = render(h(SearchPanel, { fields: fields(), onSearch: () => {} }))
    // 「单一」是本原语的核心：不是每行一个 grid、也不是 flex-wrap（那种换行点随视口漂）。
    // 红证（已执行）：把 grid 退回单档 `grid-cols-1` ⇒ 当场红（行与行不再天然对齐）。
    const grids = container.querySelectorAll('.grid')
    expect(grids).toHaveLength(1)
    const gridTokens = tokens(grids[0] as HTMLElement)
    expect(gridTokens).toContain('grid-cols-1')
    expect(gridTokens).toContain('md:grid-cols-2')
    expect(gridTokens).toContain('2xl:grid-cols-4')

    // `min-w-0` ⇒ 宽度由**轨道**给，不靠 `min-w-[200px]` 撑（旧形态会把控件压扁）。
    // 红证：单元格去掉 `min-w-0` ⇒ 这里红。
    for (const label of ['客户名称', '手机号', '下单时间']) {
      expect(tokens(cellOf(label))).toContain('min-w-0')
    }
  })

  it('span === 2 才跨轨：span=2 多一个 md:col-span-2，span=1 / 未给都不带', () => {
    render(h(SearchPanel, { fields: fields(), onSearch: () => {} }))
    // 红证（已执行，两个方向）：① 去掉 `md:col-span-2` ⇒ 第一段红；
    //   ② 把 `field.span === 2` 写成真值判断（`field.span && …`）⇒ `span: 1` 的格子被误跨轨 ⇒ 第二段红。
    expect(tokens(cellOf('下单时间'))).toContain('md:col-span-2')
    expect(tokens(cellOf('手机号'))).not.toContain('md:col-span-2')
    expect(tokens(cellOf('客户名称'))).not.toContain('md:col-span-2')
  })

  it('label 左置且定宽右对齐：w-[4.5em] + text-right + shrink-0 —— 各行 label 起点对齐的机制', () => {
    render(h(SearchPanel, { fields: fields(), onSearch: () => {} }))
    const label = screen.getByText('下单时间')
    expect(label.tagName).toBe('LABEL')
    // 红证（已执行）：`w-[4.5em]` 退回 `min-w-[4.5em]` ⇒ 当场红 —— `min-w` 只是**下限**、实际宽度
    // 仍随 label 内容变（「下单时间」4 字 vs「手机号」3 字）⇒ 各行列起点参差，正是被修的病灶。
    // ⚠️ 这条**必须按 token 断言**：`'min-w-[4.5em]'.includes('w-[4.5em]')` 为真 ⇒ 子串写法会假绿
    //    （本包实测，见文件头「红证矩阵」M4）。
    const labelTokens = tokens(label)
    expect(labelTokens).toContain('w-[4.5em]')
    expect(labelTokens).not.toContain('min-w-[4.5em]')
    expect(labelTokens).toContain('text-right')
    expect(labelTokens).toContain('shrink-0')
    expect(labelTokens).toContain('whitespace-nowrap')
    // 定宽是**每格同一个 token** 才对得上：三格 label 的宽度类必须逐字相同。
    for (const name of ['客户名称', '手机号', '下单时间']) {
      expect(tokens(screen.getByText(name))).toContain('w-[4.5em]')
    }
  })

  it('按钮行 col-span-full 独占一行 + justify-end 主操作在右，相对顺序 = 查询 → 重置 ｜ 刷新', () => {
    render(
      h(SearchPanel, { fields: fields(), onSearch: () => {}, onReset: () => {}, onRefresh: () => {} }),
    )
    const row = screen.getByRole('button', { name: '查询' }).parentElement as HTMLElement
    // 红证（已执行）：去掉 `col-span-full` ⇒ 按钮行掉进某一格轨道（列数越多越挤）；
    // 去掉 `justify-end` ⇒ 主操作跑到左侧。
    const rowTokens = tokens(row)
    expect(rowTokens).toContain('col-span-full')
    expect(rowTokens).toContain('justify-end')
    // 相对顺序也是契约（源码注释钉的 `查询 → 重置 ｜ 刷新`）：红证 = 调换 查询 / 重置 的书写顺序 ⇒ 红。
    const order = (a: HTMLElement, b: HTMLElement) =>
      (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) === Node.DOCUMENT_POSITION_FOLLOWING
    const search = screen.getByRole('button', { name: '查询' })
    const reset = screen.getByRole('button', { name: '重置' })
    const refresh = screen.getByRole('button', { name: '刷新' })
    expect(order(search, reset)).toBe(true)
    expect(order(reset, refresh)).toBe(true)
  })

  it('「查询」永远在且点击调 onSearch；「重置」只有传了 onReset 才在（反面：不传就不渲染）', () => {
    const onSearch = vi.fn()
    const { unmount } = render(h(SearchPanel, { fields: [], onSearch }))
    screen.getByRole('button', { name: '查询' }).click()
    expect(onSearch).toHaveBeenCalledTimes(1)
    // 红证（已执行）：去掉 `onReset &&` 这个条件 ⇒ 没传回调也渲染出「重置」按钮，这里当场红。
    expect(screen.queryByRole('button', { name: '重置' })).toBeNull()
    expect(screen.queryByRole('button', { name: '刷新' })).toBeNull()
    unmount()

    const onReset = vi.fn()
    render(h(SearchPanel, { fields: [], onSearch: () => {}, onReset }))
    screen.getByRole('button', { name: '重置' }).click()
    expect(onReset).toHaveBeenCalledTimes(1)
    // 给了 onReset **不改**「刷新」的在场条件：列表动作仍要单独传。
    expect(screen.queryByRole('button', { name: '刷新' })).toBeNull()
  })

  it('「刷新」只有传了 onRefresh 才在，且套在带 border-l 的 span 里 —— 列表动作与筛选动作分层', () => {
    const onRefresh = vi.fn()
    const { unmount } = render(h(SearchPanel, { fields: [], onSearch: () => {}, onRefresh }))
    const refresh = screen.getByRole('button', { name: '刷新' })
    refresh.click()
    expect(onRefresh).toHaveBeenCalledTimes(1)
    // 红证（已执行）：去掉 `onRefresh &&` ⇒ 上一段红；去掉那层 `<span className="… border-l …">`
    //（或把刷新直接放进按钮行）⇒ 这里红 ——「刷新是列表动作、与筛选动作分层」就没了可见的分隔线。
    const wrapper = refresh.parentElement as HTMLElement
    expect(wrapper.tagName).toBe('SPAN')
    expect(tokens(wrapper)).toContain('border-l')
    unmount()

    render(h(SearchPanel, { fields: [], onSearch: () => {} }))
    expect(screen.queryByRole('button', { name: '刷新' })).toBeNull()
  })

  it('loading === true ⇒ 三个按钮全 disabled（防重复提交）；不 loading 时不 disabled', () => {
    const { unmount } = render(
      h(SearchPanel, {
        fields: fields(),
        onSearch: () => {},
        onReset: () => {},
        onRefresh: () => {},
        loading: true,
      }),
    )
    // 红证（已执行）：任一个按钮去掉 `disabled={loading}` ⇒ 当场红（提交在途时可重复点）。
    for (const name of ['查询', '重置', '刷新']) {
      expect((screen.getByRole('button', { name }) as HTMLButtonElement).disabled).toBe(true)
    }
    unmount()

    // 反面（红证已执行：写成 `disabled={true}` ⇒ 这一段红）：恒禁用 / 条件取反都过不了 ——
    // 两态必须由 `loading` 驱动。
    render(
      h(SearchPanel, { fields: fields(), onSearch: () => {}, onReset: () => {}, onRefresh: () => {}, loading: false }),
    )
    for (const name of ['查询', '重置', '刷新']) {
      expect((screen.getByRole('button', { name }) as HTMLButtonElement).disabled).toBe(false)
    }
  })

  it('SEARCH_CONTROL_CLASS：h-9（桌面主控件下限）+ 暖色 token，且不含 Tailwind 默认冷灰 / 冷色', () => {
    expect(typeof SEARCH_CONTROL_CLASS).toBe('string')
    const cls = SEARCH_CONTROL_CLASS.split(/\s+/).filter(Boolean)
    // 红证（已执行）：去掉 `h-9` ⇒ 红 —— 36px 是 `scripts/design-baseline-geometry-probe.mjs` 的
    // `GEOMETRY_LIMITS.minControlHeight`（桌面主控件下限），低于它 = 鼠标点不准。
    expect(cls).toContain('h-9')
    expect(cls).toContain('w-full')
    expect(cls).toContain('border-neutral-300')
    expect(cls).toContain('focus:ring-primary-500/15')
    // 按 token 断言的反向（红证已执行：`h-9` 旁多加 `min-h-9`、`w-full` 旁多加 `max-w-full` ⇒ 红）：
    // 超集 token 会让「下限 / 宽度由轨道给」这两个契约悄悄失效，子串写法拦不住。
    expect(cls).not.toContain('min-h-9')
    expect(cls).not.toContain('max-w-full')
    // 暖色 token 收口（红证已执行：`border-neutral-300` 换回 `border-gray-300` ⇒ 红）：
    // 本仓暖色族是 `primary` / `accent` / `neutral`，`gray` 落回 Tailwind 默认**冷灰**，
    // 在全站暖亚麻底上是一块另一个产品的颜色（`SearchBar` 被修的正是这一处）。
    for (const coldToken of ['gray-', 'blue-', 'indigo-', 'purple-']) {
      expect(SEARCH_CONTROL_CLASS).not.toContain(coldToken)
    }
  })

  it('无状态：调用方传的 control 节点被原样渲染，原语不改写它的 value —— 原语只管版式', () => {
    const controlNode = h('input', { 'aria-label': '关键词', value: 'x', readOnly: true })
    const { container } = render(
      h(SearchPanel, {
        fields: [{ key: 'keyword', label: '客户名称', control: controlNode }],
        onSearch: () => {},
      }),
    )
    const input = screen.getByLabelText('关键词') as HTMLInputElement
    // 红证（已执行）：原语若不渲染传入的 `control`（照 `SearchBar` 那样自己渲染
    // `<Input value={values[key] || ''}>`）⇒ 传进来的 `value: 'x'` 与 `readOnly` 都被洗掉 ⇒ 当场红。
    expect(input.value).toBe('x')
    expect(input.readOnly).toBe(true)
    // 原语也不改写 node 的版式归属：它的外层就是原语的单元格容器（`flex-1 min-w-0`）。
    const wrapTokens = tokens(input.parentElement as HTMLElement)
    expect(wrapTokens).toContain('flex-1')
    expect(wrapTokens).toContain('min-w-0')
    // 整块面板（**渲染输出**，不只是常量）里不得出现任何冷色族。
    for (const coldToken of ['gray-', 'blue-', 'indigo-', 'purple-']) {
      expect(container.innerHTML).not.toContain(coldToken)
    }
  })

  it('className 透传：调用方要加自己的外层修饰时不被迫退回手写 div', () => {
    const { container } = render(
      h(SearchPanel, { fields: [], onSearch: () => {}, className: 'mb-2' }),
    )
    const root = container.firstElementChild as HTMLElement
    expect(root.getAttribute('data-testid')).toBe('search-area')
    // 红证（已执行）：外层 `cn(…)` 吞掉 `className` ⇒ 当场红 —— 透传断了，调用方就只能自己再包一层
    // `div`（那正是本原语要消灭的手写形态）；同时"原语自带底版"必须还在（透传 ≠ 替换）。
    expect(tokens(root)).toContain('mb-2')
    expect(tokens(root)).toContain('bg-white')
    expect(tokens(root)).toContain('rounded-lg')
  })
})

/**
 * 可折叠（issue #7388）：判据一律落在 **DOM 在场性**上，不是类名 ——
 * 折叠若只是 CSS 隐藏，页面高度与无障碍树都还在涨（§31 P1 的机器读数 = `queryBy*` 为 `null`）。
 */
describe('SearchPanel —— collapsible（issue #7388）', () => {
  const collapsibleProps = {
    fields: fields(),
    onSearch: () => {},
    onReset: () => {},
    onRefresh: () => {},
    collapsible: true,
    summary: '近一个月 · 收货人',
  }

  it('不传 collapsible ⇒ 字段常驻、没有折叠开关（存量页面行为逐字不变）', () => {
    render(h(SearchPanel, { fields: fields(), onSearch: () => {} }))
    // 红证（已执行）：把 `collapsible = false` 的默认值改成 `true` ⇒ 这里当场红
    // —— 客户 / 售后 / 品检 / 员工四页会在没人要求的情况下一起改成折叠。
    expect(screen.getByLabelText('客户名称输入')).toBeTruthy()
    expect(screen.getByRole('button', { name: '查询' })).toBeTruthy()
    expect(screen.queryByTestId('search-panel-toggle')).toBeNull()
  })

  it('collapsible 默认收起：字段与按钮行**不在 DOM**，摘要与展开入口在', () => {
    render(h(SearchPanel, collapsibleProps))
    // 红证（已执行）：把 body 改成常驻 + `hidden` / CSS 隐藏 ⇒ 这两条当场红（DOM 还在 = 假折叠）。
    expect(screen.queryByLabelText('客户名称输入')).toBeNull()
    expect(screen.queryByLabelText('下单时间输入')).toBeNull()
    expect(screen.queryByRole('button', { name: '查询' })).toBeNull()
    expect(screen.queryByRole('button', { name: '刷新' })).toBeNull()

    const toggle = screen.getByTestId('search-panel-toggle')
    expect(toggle.tagName).toBe('BUTTON')
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    // 收起态必须说清「在筛什么」：只有一行标题的折叠条会让商家以为列表是全部订单。
    expect(screen.getByTestId('search-panel-summary').textContent).toContain('近一个月')

    // 收起 ≠ 没有筛选：必须有**看得出能点**的入口（用户 2026-10-20：「折叠状态需要引导用户
    // 可以打开区域查询」）。判据 = 入口文案 + 按钮形态（描边）+ 悬停提示都在，
    // 只把「展开筛选」写成一行弱文字（无描边）也算没做到 —— 红证：去掉 `border` token ⇒ 红。
    const label = screen.getByTestId('search-panel-toggle-label')
    expect(label.textContent).toContain('展开筛选')
    expect(tokens(label)).toContain('border')
    expect(tokens(label)).toContain('rounded-lg')
    expect(toggle.getAttribute('title')).toContain('展开筛选区')
  })

  it('点「展开筛选」⇒ 字段与按钮逐个回来、aria-expanded 翻转；再点 ⇒ 又收起', () => {
    render(h(SearchPanel, collapsibleProps))
    const toggle = screen.getByTestId('search-panel-toggle')

    fireEvent.click(toggle)
    expect(toggle.getAttribute('aria-expanded')).toBe('true')
    for (const name of ['客户名称输入', '手机号输入', '下单时间输入']) {
      expect(screen.getByLabelText(name)).toBeTruthy()
    }
    expect(screen.getByRole('button', { name: '查询' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '重置' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '刷新' })).toBeTruthy()
    // 展开后字段本身就在说「在筛什么」⇒ 摘要不再渲染（§31 P2：不重复同屏已有信息）。
    expect(screen.queryByTestId('search-panel-summary')).toBeNull()
    const label = screen.getByTestId('search-panel-toggle-label')
    expect(label.textContent).toBe('收起')
    // 展开后入口降级成弱文字：不与「查询」抢视觉（一屏至多一个 primary，见 ui-button-standard §2）。
    expect(tokens(label)).not.toContain('border')

    fireEvent.click(toggle)
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    expect(screen.queryByLabelText('客户名称输入')).toBeNull()
  })

  it('defaultCollapsed={false} ⇒ 可折叠但初始展开（需要常驻的页面有出口）', () => {
    render(h(SearchPanel, { ...collapsibleProps, defaultCollapsed: false }))
    expect(screen.getByLabelText('客户名称输入')).toBeTruthy()
    expect(screen.getByTestId('search-panel-toggle').getAttribute('aria-expanded')).toBe('true')
  })
})
