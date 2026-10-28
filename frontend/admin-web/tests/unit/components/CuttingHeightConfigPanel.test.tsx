// @vitest-environment jsdom
// case_ids: PG-045
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'

/**
 * 裁高配置面板（母单 #5161；v2 = issue #7997）—— 每条判据都能红：
 *   ① 打开即读 `GET …/cutting-height-config`，把 `source` 画出来，且**分两个区块**
 *      （工序专用 / 公共兜底）：`default` ⇒ 「当前使用系统默认值」（不把默认值伪装成商家配置）；
 *   ② 保存走 **PUT 全量替换**，报文是 **v2 形态**（`scope` / `position` / `conditions`）——
 *      红证：把 `scope` 或 `conditions` 丢掉 ⇒ 后端收到只有 half 份配置 ⇒ 命中口径静默变化；
 *   ③ 预演走 `POST …/preview`（命中口径**由服务端判**，前端不自己比名字），并把「命中但未配置取值」
 *      的项**显式**画出来（壁达的「画线」形态）；
 *   ④ 保存失败**不冒充成功**（不弹成功 toast、来源徽标不变）；
 *   ⑤ **线上形态**同样留空（后端 `spring.jackson.default-property-inclusion: non_null` 把 `value=null`
 *      的键**整个丢掉** ⇒ 前端拿到的是 `undefined` 而不是 `null`）—— 取值框不得显示 `undefined`；
 *   ⑥ **取值域是闭词表**：安装工艺 = 单选 `CRAFT_OPTIONS`、特殊选项 / 条件取值 = 多选闭词表（默认折叠）；
 *   ⑦ **版式（修 #7153 残留）**：表格已退场（无 `<table>` / `<colgroup>`），控件满列、条件 chips 可折行
 *      —— 「部位」下拉不再被 11% 宽的列压到只显示「布」（红证：把 `<select>` 的 `w-full` 去掉 /
 *      把 chips 容器换成不折行的 `flex` ⇒ 红）；
 *   ⑧ **存量 v1 报文不白屏**：旧后端（`hit` 形态）在滚动发布窗口里也要能渲染（按工序专用组显示）。
 */
import { CRAFT_OPTIONS, SPECIAL_OPTIONS } from '@/lib/order-craft-fields'

const mockGet = vi.fn()
const mockUpdate = vi.fn()
const mockPreview = vi.fn()

vi.mock('@/lib/api', () => ({
  cuttingHeightApi: {
    get: (...a: unknown[]) => mockGet(...a),
    update: (...a: unknown[]) => mockUpdate(...a),
    preview: (...a: unknown[]) => mockPreview(...a),
  },
  productionApi: {
    getRouteRuleOptions: () =>
      Promise.resolve({
        data: { data: { crafts: [...CRAFT_OPTIONS], processing_items: ['定型', '拼接'], positions: [] } },
      }),
  },
}))

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import { CuttingHeightConfigPanel } from '@/components/production/CuttingHeightConfigPanel'
import { toast } from 'sonner'

const ITEMS = [
  {
    key: 'bangdai_hanzhe',
    name: '布绑带-韩褶',
    value: 0.14,
    direction: 'add',
    height_join: false,
    scope: 'specific',
    position: '布帘',
    conditions: [
      { kind: 'option', values: ['布绑带'] },
      { kind: 'craft', values: ['韩褶'] },
    ],
    enabled: true,
    order: 10,
  },
  {
    key: 'huaxian',
    name: '画线',
    value: null,
    direction: 'add',
    height_join: false,
    scope: 'specific',
    position: null,
    conditions: [{ kind: 'option', values: ['接高', '双眼皮接高'] }],
    enabled: true,
    order: 20,
  },
  {
    key: 'butie',
    name: '布贴',
    value: 0.015,
    direction: 'add',
    height_join: false,
    scope: 'fallback',
    position: '布帘',
    conditions: [{ kind: 'option', values: ['布贴'] }],
    enabled: true,
    order: 30,
  },
]

const configResponse = (source: string) => ({
  data: {
    data: {
      source,
      config: {
        items: ITEMS,
        rounding: { mode: 'half_up', digits: 3 },
      },
    },
  },
})

/**
 * 线上形态：`non_null` 会把 `null` 值的键**整个丢掉**（同族先例 = 后端
 * `backend/admin-api/src/test/java/com/migao/admin/controller/CustomerProfileWireKeyParityTest.java`）
 * ⇒ 前端收到的是 `undefined`。本函数把 fixture 变成「线上报文」（剥掉所有 null 键）。
 */
function wireForm<T>(value: T): T {
  if (Array.isArray(value)) return value.map(wireForm) as unknown as T
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value)
        .filter(([, v]) => v !== null)
        .map(([k, v]) => [k, wireForm(v)]),
    ) as T
  }
  return value
}

describe('CuttingHeightConfigPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGet.mockResolvedValue(configResponse('default'))
  })

  it('① 打开即读配置，分「工序专用 / 公共兜底」两个区块，默认值不伪装成商家配置', async () => {
    render(<CuttingHeightConfigPanel />)

    await waitFor(() => expect(screen.getByTestId('cutting-height-source')).toBeTruthy())
    expect(mockGet).toHaveBeenCalledTimes(1)
    expect(screen.getByTestId('cutting-height-source').textContent).toBe('当前使用系统默认值')
    expect((screen.getByLabelText('名称-0') as HTMLInputElement).value).toBe('布绑带-韩褶')
    // 有项无值：取值输入框留空（不是 0）
    expect((screen.getByLabelText('取值-1') as HTMLInputElement).value).toBe('')

    // 分组：专用组 2 项、兜底组 1 项（不是把 3 项平铺成一张表）
    const specific = screen.getByTestId('cutting-height-group-specific')
    const fallback = screen.getByTestId('cutting-height-group-fallback')
    expect(within(specific).getByLabelText('名称-0')).toBeTruthy()
    expect(within(specific).getByLabelText('名称-1')).toBeTruthy()
    expect(within(fallback).getByLabelText('名称-2')).toBeTruthy()
    // 兜底语义写在脸上（用户 2026-10-28 裁定 A：替换，不是叠加）
    expect(fallback.textContent).toContain('没有任何工序专用参数命中时才用')
    expect(specific.textContent).toContain('只要有一条命中')

    // 条件 chips：布绑带（特殊选项）∧ 韩褶（安装工艺）
    expect(screen.getByLabelText('条件类型-0-0').tagName).toBe('SELECT')
    expect(screen.getByLabelText('条件取值-0-0').textContent).toBe('布绑带')
    expect(screen.getByLabelText('条件取值-0-1').textContent).toBe('韩褶')
    // 一项里两个取值 = 「或」
    expect(screen.getByLabelText('条件取值-1-0').textContent).toBe('接高、双眼皮接高')
  })

  it('② 保存 = PUT 全量替换，报文是 v2（scope / position / conditions）', async () => {
    mockUpdate.mockResolvedValue(configResponse('stored'))
    render(<CuttingHeightConfigPanel />)
    await waitFor(() => expect(screen.getByTestId('cutting-height-save')).toBeTruthy())

    fireEvent.click(screen.getByTestId('cutting-height-save'))

    await waitFor(() => expect(mockUpdate).toHaveBeenCalledTimes(1))
    const body = mockUpdate.mock.calls[0][0] as {
      items: Array<Record<string, unknown>>
      rounding: unknown
    }
    expect(body.items).toHaveLength(3)
    expect(body.rounding).toEqual({ mode: 'half_up', digits: 3 })
    expect(body.items[0]).toMatchObject({
      key: 'bangdai_hanzhe',
      scope: 'specific',
      position: '布帘',
      conditions: [
        { kind: 'option', values: ['布绑带'] },
        { kind: 'craft', values: ['韩褶'] },
      ],
    })
    expect(body.items[2]).toMatchObject({ key: 'butie', scope: 'fallback' })
    // 旧键绝不回流（一份配置只留一种写法）
    expect(body.items[0]).not.toHaveProperty('hit')
    expect(body.items[0]).not.toHaveProperty('hit_expr')
    expect(toast.success).toHaveBeenCalled()
  })

  it('③ 预演：命中口径由服务端判；「命中但未配置取值」显式画出；加工项随报文发出', async () => {
    mockPreview.mockResolvedValue({
      data: {
        data: {
          source: 'default',
          base: 2.92,
          cutting_height: 2.935,
          rounding: { mode: 'half_up', digits: 3 },
          hits: [{ key: 'butie', name: '布贴', value: 0.015, direction: 'add', height_join: false }],
          misses: [{ key: 'huaxian', name: '画线', reason: 'unresolved' }],
        },
      },
    })
    render(<CuttingHeightConfigPanel />)
    await waitFor(() => expect(screen.getByTestId('cutting-height-preview')).toBeTruthy())

    fireEvent.change(screen.getByLabelText('预演成品高'), { target: { value: '2.92' } })
    fireEvent.change(screen.getByLabelText('预演工艺'), { target: { value: '打孔' } })
    fireEvent.click(screen.getByLabelText('预演特殊选项'))
    fireEvent.click(screen.getByLabelText('特殊选项-布绑带'))
    fireEvent.click(screen.getByLabelText('预演加工项'))
    fireEvent.click(screen.getByLabelText('加工项-定型'))
    fireEvent.click(screen.getByTestId('cutting-height-preview'))

    await waitFor(() => expect(screen.getByTestId('cutting-height-preview-result')).toBeTruthy())
    expect(mockPreview.mock.calls[0][0]).toMatchObject({
      position: '布帘',
      finished_height: '2.92',
      craft: '打孔',
      special_options: ['布绑带'],
      processing_items: ['定型'],
    })
    const result = screen.getByTestId('cutting-height-preview-result')
    expect(result.textContent).toContain('2.935')
    expect(result.textContent).toContain('未配置取值')
  })

  it('④ 保存失败不冒充成功：不弹成功 toast，来源徽标不变', async () => {
    mockUpdate.mockRejectedValue(new Error('boom'))
    render(<CuttingHeightConfigPanel />)
    await waitFor(() => expect(screen.getByTestId('cutting-height-save')).toBeTruthy())

    fireEvent.click(screen.getByTestId('cutting-height-save'))

    await waitFor(() => expect(toast.error).toHaveBeenCalled())
    expect(toast.success).not.toHaveBeenCalled()
    expect(screen.getByTestId('cutting-height-source').textContent).toBe('当前使用系统默认值')
  })

  it('⑤ 线上形态（non_null 丢键 ⇒ value / position 缺席）取值框留空，不得显示 undefined', async () => {
    const res = configResponse('default')
    mockGet.mockResolvedValue({ data: { data: wireForm(res.data.data) } })
    render(<CuttingHeightConfigPanel />)

    await waitFor(() => expect(screen.getByTestId('cutting-height-items')).toBeTruthy())

    const huaxian = screen.getByLabelText('取值-1') as HTMLInputElement
    expect(huaxian.value).toBe('')
    // 反向断言：整块配置里任何一个输入框都不许出现 undefined 字面量
    for (const input of screen.getByTestId('cutting-height-items').querySelectorAll('input')) {
      expect((input as HTMLInputElement).value).not.toBe('undefined')
    }
    expect((screen.getByLabelText('部位-1') as HTMLSelectElement).value).toBe('')
  })

  it('⑥ 取值域是闭词表：工艺单选、特殊选项/条件取值多选（默认折叠）', async () => {
    render(<CuttingHeightConfigPanel />)
    await waitFor(() => expect(screen.getByTestId('cutting-height-preview')).toBeTruthy())

    const craft = screen.getByLabelText('预演工艺') as HTMLSelectElement
    expect(craft.tagName).toBe('SELECT')
    expect(Array.from(craft.options).map((o) => o.textContent)).toEqual(['不指定', ...CRAFT_OPTIONS])

    const options = screen.getByLabelText('预演特殊选项')
    expect(options.tagName).toBe('BUTTON')
    expect(options.getAttribute('aria-expanded')).toBe('false')
    fireEvent.click(options)
    expect(options.getAttribute('aria-expanded')).toBe('true')
    for (const name of SPECIAL_OPTIONS) {
      expect(screen.getByLabelText(`特殊选项-${name}`)).toBeTruthy()
    }
    fireEvent.mouseDown(document.body)
    expect(screen.queryByLabelText('特殊选项-拼2次')).toBeNull()

    // 条件取值同样走闭词表（选项名是 join key，不给自由文本）
    fireEvent.click(screen.getByLabelText('条件取值-0-0'))
    for (const name of SPECIAL_OPTIONS) {
      expect(screen.getByLabelText(`条件取值-0-0-${name}`)).toBeTruthy()
    }
  })

  it('⑦ 版式：#7153 的成因（窄列 + 大内边距裁字）结构上不存在', async () => {
    render(<CuttingHeightConfigPanel />)
    const container = await screen.findByTestId('cutting-height-items')

    // 表格已退场：没有 <table>/<colgroup> ⇒ 不存在「col 分到 11% ⇒ 布帘被裁成布」这条路径
    expect(container.querySelector('table')).toBeNull()
    expect(container.querySelector('colgroup')).toBeNull()
    // 字段级下拉（部位）满列：定宽 + 内边距 = 又回到裁字
    for (const index of [0, 1, 2]) {
      const position = screen.getByLabelText(`部位-${index}`) as HTMLElement
      expect(position.className).toContain('w-full')
    }
    // 任何下拉都不许用像素定宽（`w-[Npx]`，按 class 逐段判 —— `max-w-[7rem]` 是「上限」不是定宽）
    for (const select of Array.from(container.querySelectorAll('select'))) {
      const widthClasses = (select as HTMLElement).className.split(/\s+/).filter((c) => /^w-\[/.test(c))
      expect(widthClasses, `下拉不得像素定宽：${(select as HTMLElement).className}`).toEqual([])
    }
    // 条件 chips 行可折行（不折行 = 条件一多就往右溢出）
    const addCondition = screen.getByTestId('cutting-height-add-condition-0')
    expect(addCondition.parentElement?.className).toContain('flex-wrap')
    // 「启用 / 删除」不竖排
    expect((screen.getByTestId('cutting-height-remove-0') as HTMLElement).className).toContain(
      'whitespace-nowrap',
    )
  })

  it('⑧ 存量 v1 报文（hit 形态）不白屏：按工序专用组渲染', async () => {
    const legacy = {
      data: {
        data: {
          source: 'stored',
          config: {
            items: [
              {
                key: 'butie',
                name: '布贴',
                value: 0.015,
                direction: 'add',
                height_join: false,
                hit: { trigger_kind: 'option', trigger_value: '布贴', position: '布帘' },
                hit_expr: null,
                enabled: true,
                order: 10,
              },
            ],
            rounding: { mode: 'half_up', digits: 3 },
          },
        },
      },
    }
    mockGet.mockResolvedValue(legacy)
    render(<CuttingHeightConfigPanel />)

    await waitFor(() => expect(screen.getByTestId('cutting-height-items')).toBeTruthy())
    const specific = screen.getByTestId('cutting-height-group-specific')
    expect(within(specific).getByLabelText('名称-0')).toBeTruthy()
    expect((screen.getByLabelText('部位-0') as HTMLSelectElement).value).toBe('')
    // 旧形态没有 conditions ⇒ 显示「无附加条件」，不渲染空 chip
    expect(screen.queryByLabelText('条件取值-0-0')).toBeNull()
  })
})
