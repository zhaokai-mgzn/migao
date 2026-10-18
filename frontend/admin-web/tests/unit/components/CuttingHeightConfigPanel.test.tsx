// @vitest-environment jsdom
// case_ids: PG-045
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

/**
 * 裁高配置面板（母单 #5161）——五条判据，每条都能红：
 *   ① 打开即读 `GET /api/admin/production/cutting-height-config`，并把 `source` 画出来
 *      （`default` ⇒ 「当前使用系统默认值」—— **不把默认值伪装成商家配置**）；
 *   ② 保存走 **PUT 全量替换**（items + rounding 一起发，不发明「部分更新」）；
 *   ③ 预演走 `POST …/preview`（命中口径**由服务端判**，前端不自己比名字），
 *      并把「命中但未配置取值」的项**显式**画出来（壁达的「画线」形态）；
 *   ④ 保存失败**不冒充成功**（不弹成功 toast、来源徽标不变）；
 *   ⑤ **线上形态**同样留空（后端 `spring.jackson.default-property-inclusion: non_null` 把 `value=null`
 *      的键**整个丢掉** ⇒ 前端拿到的是 `undefined` 而不是 `null`）—— 判据 = 取值框不得显示
 *      `undefined` 字面量。红证：把 `undefined` 也当空值的兜底摘掉 ⇒ ⑤ 红（旧实现只判 `=== null`）。
 *   ⑥ **预演的取值域是闭词表**（issue #7213）：安装工艺 = 单选 `CRAFT_OPTIONS`、特殊选项 = 多选
 *      `SPECIAL_OPTIONS`（默认折叠）。红证：把任一改回 `<input>` 自由文本 ⇒ ⑥ 红（`tagName` / 默认折叠）。
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
}))

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import { CuttingHeightConfigPanel } from '@/components/production/CuttingHeightConfigPanel'
import { toast } from 'sonner'

const configResponse = (source: string) => ({
  data: {
    data: {
      source,
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
          {
            key: 'huaxian',
            name: '画线',
            value: null,
            direction: 'add',
            height_join: false,
            hit: { trigger_kind: 'option', trigger_value: '画线', position: null },
            hit_expr: null,
            enabled: true,
            order: 20,
          },
        ],
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

  it('① 打开即读配置，并把「当前使用系统默认值」画出来（不伪装成商家配置）', async () => {
    render(<CuttingHeightConfigPanel />)

    await waitFor(() => expect(screen.getByTestId('cutting-height-source')).toBeTruthy())
    expect(mockGet).toHaveBeenCalledTimes(1)
    expect(screen.getByTestId('cutting-height-source').textContent).toBe('当前使用系统默认值')
    expect((screen.getByLabelText('名称-0') as HTMLInputElement).value).toBe('布贴')
    expect((screen.getByLabelText('触发值-0') as HTMLInputElement).value).toBe('布贴')
    // 有项无值：取值输入框留空（不是 0）
    expect((screen.getByLabelText('取值-1') as HTMLInputElement).value).toBe('')
  })

  it('② 保存 = PUT 全量替换（items 与 rounding 一起发）', async () => {
    mockUpdate.mockResolvedValue(configResponse('stored'))
    render(<CuttingHeightConfigPanel />)
    await waitFor(() => expect(screen.getByTestId('cutting-height-save')).toBeTruthy())

    fireEvent.click(screen.getByTestId('cutting-height-save'))

    await waitFor(() => expect(mockUpdate).toHaveBeenCalledTimes(1))
    const body = mockUpdate.mock.calls[0][0] as { items: unknown[]; rounding: unknown }
    expect(body.items).toHaveLength(2)
    expect(body.rounding).toEqual({ mode: 'half_up', digits: 3 })
    expect(toast.success).toHaveBeenCalled()
  })

  it('③ 预演：命中口径由服务端判；「命中但未配置取值」显式画出', async () => {
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
    fireEvent.click(screen.getByLabelText('特殊选项-拼2次'))
    fireEvent.click(screen.getByLabelText('特殊选项-接高'))
    fireEvent.click(screen.getByTestId('cutting-height-preview'))

    await waitFor(() => expect(screen.getByTestId('cutting-height-preview-result')).toBeTruthy())
    expect(mockPreview.mock.calls[0][0]).toMatchObject({
      position: '布帘',
      finished_height: '2.92',
      craft: '打孔',
      special_options: ['拼2次', '接高'],
    })
    const result = screen.getByTestId('cutting-height-preview-result')
    expect(result.textContent).toContain('2.935')
    expect(result.textContent).toContain('未配置取值')
  })

  it('⑥ 预演的「安装工艺 / 特殊选项」是闭词表选择器（不是自由文本）—— 默认折叠、清单与下单页同源', async () => {
    render(<CuttingHeightConfigPanel />)
    await waitFor(() => expect(screen.getByTestId('cutting-height-preview')).toBeTruthy())

    // 安装工艺：单选，取值逐字 = CRAFT_OPTIONS（外加「不指定」空值）
    const craft = screen.getByLabelText('预演工艺') as HTMLSelectElement
    expect(craft.tagName).toBe('SELECT')
    expect(Array.from(craft.options).map((o) => o.textContent)).toEqual(['不指定', ...CRAFT_OPTIONS])

    // 特殊选项：多选下拉 —— 默认只占一行，点开才渲染 19 项复选（§31 P1 常驻面克制）
    const options = screen.getByLabelText('预演特殊选项')
    expect(options.tagName).toBe('BUTTON')
    expect(options.getAttribute('aria-expanded')).toBe('false')
    expect(options.textContent).toContain('未选择')
    expect(screen.queryByLabelText('特殊选项-拼2次')).toBeNull()

    fireEvent.click(options)
    expect(options.getAttribute('aria-expanded')).toBe('true')
    for (const name of SPECIAL_OPTIONS) {
      expect(screen.getByLabelText(`特殊选项-${name}`)).toBeTruthy()
    }
    fireEvent.click(screen.getByLabelText('特殊选项-拼2次'))
    fireEvent.click(screen.getByLabelText('特殊选项-接高'))
    expect(options.textContent).toContain('已选 2 项')

    // 点外部 ⇒ 收起（不是「打开就关不掉」的常驻块）
    fireEvent.mouseDown(document.body)
    expect(screen.queryByLabelText('特殊选项-拼2次')).toBeNull()
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

  it('⑤ 线上形态（non_null 丢键 ⇒ value 缺席）取值框留空，不得显示 undefined', async () => {
    const res = configResponse('default')
    // 逐字复现线上报文：`value: null` / `hit.position: null` / `hit_expr: null` 三个键都不在线
    mockGet.mockResolvedValue({ data: { data: wireForm(res.data.data) } })
    render(<CuttingHeightConfigPanel />)

    await waitFor(() => expect(screen.getByTestId('cutting-height-items')).toBeTruthy())

    const huaxian = screen.getByLabelText('取值-1') as HTMLInputElement
    expect(huaxian.value).toBe('')
    // 反向断言：整张表里任何一个输入框都不许出现 undefined 字面量
    for (const input of screen.getByTestId('cutting-height-items').querySelectorAll('input')) {
      expect((input as HTMLInputElement).value).not.toBe('undefined')
    }
    expect((screen.getByLabelText('部位-1') as HTMLSelectElement).value).toBe('')
  })

  it('⑥ 列宽显式 + 表头不竖排（#7153：下拉与「启用 / 删除」不得被压到裁字）', async () => {
    mockGet.mockResolvedValue(configResponse('stored'))
    render(<CuttingHeightConfigPanel />)

    const table = await screen.findByTestId('cutting-height-items')
    // ① 固定布局 + 最小宽度：窄屏走横向滚动，不再把控件压到内容宽度以下
    //    （注入：把 `table-fixed` 或 `min-w-[…]` 删掉 ⇒ 下面两条红 —— 那正是「特殊选: / 布厂」的成因）
    expect(table.className).toContain('table-fixed')
    expect(table.className).toMatch(/min-w-/)
    // ② 列宽显式给：colgroup 的列数必须等于表头列数（漏一列 ⇒ 那一列又回到 auto 被压扁）
    const cols = table.querySelectorAll('colgroup > col')
    const heads = table.querySelectorAll('thead th')
    expect(heads.length).toBe(7)
    expect(cols.length).toBe(heads.length)
    // ③ 表头不竖排（「启用」曾折成两行）、操作按钮不竖排（「删除」曾折成两行）
    for (const th of Array.from(heads)) {
      expect((th as HTMLElement).className, `表头「${th.textContent}」缺 whitespace-nowrap`).toContain(
        'whitespace-nowrap',
      )
    }
    const removeButtons = table.querySelectorAll('tbody button')
    expect(removeButtons.length).toBeGreaterThan(0)
    for (const btn of Array.from(removeButtons)) {
      expect((btn as HTMLElement).className).toContain('whitespace-nowrap')
    }
  })
})
