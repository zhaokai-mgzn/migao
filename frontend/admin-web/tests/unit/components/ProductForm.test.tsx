/**
 * ProductForm 组件测试
 * 覆盖：#646 移除 in_warehouse — 按钮数量、labelMap 无仓库中
 * #4371：加工项与商品解耦 —— 表单不再有「是否支持加工」与加工项配置编辑区
 * case_ids: PR-008, PR-017, PR-042, PR-043, PR-044, OR-046
 */
import { render, screen, within, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import ProductForm from '@/components/products/ProductForm'

// Mock 子组件以减少依赖
vi.mock('@/components/products/ImageUploader', () => ({
  default: (props: any) => {
    const React = require('react')
    return React.createElement('div', { 'data-testid': 'image-uploader' }, 'ImageUploader')
  },
}))
vi.mock('@/components/products/SkuMatrix', () => ({
  default: (props: any) => {
    const React = require('react')
    return React.createElement('div', { 'data-testid': 'sku-matrix' }, 'SkuMatrix')
  },
}))
vi.mock('@/components/products/ProductAttributes', () => ({
  default: (props: any) => {
    const React = require('react')
    return React.createElement('div', { 'data-testid': 'product-attributes' }, 'ProductAttributes')
  },
}))
vi.mock('@/components/products/RichTextEditor', () => ({
  default: (props: any) => {
    const React = require('react')
    return React.createElement('div', { 'data-testid': 'rich-text-editor' }, 'RichTextEditor')
  },
}))

// Mock API 调用
vi.mock('@/lib/api', () => ({
  categoryApi: {
    getCategories: vi.fn().mockResolvedValue({ data: { data: [] } }),
  },
  processingItemApi: {
    getProcessingItems: vi.fn().mockResolvedValue({ data: { data: { items: [] } } }),
  },
}))

describe('ProductForm (#1284 — 表单行对齐)', () => {
  const mockOnSubmit = vi.fn().mockResolvedValue(undefined)

  it('「总库存」「拍下减库存」两行 label 均含 * 必填标记', () => {
    render(<ProductForm onSubmit={mockOnSubmit} />)

    const stockLabels = screen.getAllByText(/总库存/)
    const deductionLabels = screen.getAllByText(/拍下减库存/)

    expect(stockLabels.length).toBeGreaterThanOrEqual(1)
    expect(deductionLabels.length).toBeGreaterThanOrEqual(1)
  })

  it('「拍下减库存」渲染 RadioGroup（是/付款减库存）', () => {
    render(<ProductForm onSubmit={mockOnSubmit} />)

    // "否（付款减库存）" 选项存在
    expect(screen.getByText(/付款减库存/)).toBeTruthy()
  })

  it('RadioGroup 有 pt-2 补偿，使文字 baseline 与 h-9 input 对齐', () => {
    render(<ProductForm onSubmit={mockOnSubmit} />)

    const deductionRadio = screen.getByText(/付款减库存/)
    const deductionRadioGroup = deductionRadio.parentElement!.parentElement!
    expect(deductionRadioGroup.className).toContain('pt-2')
  })

  it('「退货回补库存」开关渲染（允许/不允许，issue #2991）', () => {
    render(<ProductForm onSubmit={mockOnSubmit} />)

    expect(screen.getByText(/退货回补库存/)).toBeTruthy()
    expect(screen.getAllByText('允许').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('不允许').length).toBeGreaterThanOrEqual(1)
    // 行业提示文案：定制退货不可再售
    expect(screen.getByText(/退货后无法再次出售/)).toBeTruthy()
  })

  it('编辑场景回填 allowReturnRestock 开关（开启状态）', () => {
    render(
      <ProductForm
        onSubmit={mockOnSubmit}
        initialData={{ name: '标准杆', allowReturnRestock: true } as any}
      />
    )
    // 回填后「允许」仍可渲染（默认值随 initialData 合并）
    expect(screen.getAllByText('允许').length).toBeGreaterThanOrEqual(1)
  })

  it('提交时规格属性英文 key 转中文 key 落库（issue #3044）', async () => {
    // 表单内部用英文 key（weight/material/...），提交 payload 必须统一为中文 key
    // （克重/材质/...）与 ai-agent 建品风格一致，详情页天然中文展示。
    const submit = vi.fn().mockResolvedValue(undefined)
    render(
      <ProductForm
        onSubmit={submit}
        initialData={{
          name: '常青藤系列窗帘',
          specifications: {
            weight: '200-300g',
            material: '涤纶',
            function: '遮光',
            craft: '色织',
            style: '现代简约',
            pattern: '纯色',
          },
        } as any}
      />
    )

    // draft 状态仅校验名称；initialData 已提供名称
    const { fireEvent } = await import('@testing-library/react')
    fireEvent.click(screen.getByText('存草稿'))

    await new Promise((r) => setTimeout(r, 0))
    const payload = submit.mock.calls[0]?.[0]
    expect(payload.specifications).toEqual({
      克重: '200-300g',
      材质: '涤纶',
      功能: '遮光',
      工艺: '色织',
      风格: '现代简约',
      图案: '纯色',
    })
  })
})

describe('ProductForm (#646 — 移除 in_warehouse)', () => {
  const mockOnSubmit = vi.fn().mockResolvedValue(undefined)

  it('底部操作栏只有 2 个按钮：存草稿 + 提交并上架', () => {
    render(<ProductForm onSubmit={mockOnSubmit} />)

    // 应该有「存草稿」按钮
    expect(screen.getByText('存草稿')).toBeTruthy()

    // 应该有「提交并上架」按钮
    expect(screen.getByText('提交并上架')).toBeTruthy()

    // 不应有「提交并放入仓库」按钮
    expect(screen.queryByText('提交并放入仓库')).toBeNull()
    expect(screen.queryByText('仓库中')).toBeNull()
  })

  it('编辑场景仍显示 2 按钮（不出现仓库按钮）', () => {
    render(
      <ProductForm
        initialData={{ name: '测试商品', status: 'draft' } as any}
        onSubmit={mockOnSubmit}
      />
    )

    expect(screen.getByText('存草稿')).toBeTruthy()
    expect(screen.getByText('提交并上架')).toBeTruthy()
    expect(screen.queryByText('提交并放入仓库')).toBeNull()
  })

  it('自定义 submitText 生效', () => {
    render(<ProductForm onSubmit={mockOnSubmit} submitText="保存并上架" />)

    expect(screen.getByText('保存并上架')).toBeTruthy()
  })

  it('页面标题显示"新增商品"（非编辑模式）', () => {
    render(<ProductForm onSubmit={mockOnSubmit} />)

    expect(screen.getByText('新增商品')).toBeTruthy()
  })

  it('编辑模式页面标题显示"编辑商品"', () => {
    render(
      <ProductForm
        initialData={{ name: '测试' } as any}
        onSubmit={mockOnSubmit}
      />
    )

    expect(screen.getByText('编辑商品')).toBeTruthy()
  })
})

describe('ProductForm (#1403 — 管理分类入口)', () => {
  const mockOnSubmit = vi.fn().mockResolvedValue(undefined)

  it('「商品分类」选择框旁应存在「管理分类」按钮', () => {
    render(<ProductForm onSubmit={mockOnSubmit} />)

    // 分类选择器的 label 存在
    const categoryLabels = screen.getAllByText('商品分类')
    expect(categoryLabels.length).toBeGreaterThanOrEqual(1)

    // 「管理分类」按钮应存在于选择框旁
    expect(screen.getByText('管理分类')).toBeTruthy()
  })

  it('点击「管理分类」按钮应打开分类管理弹窗', async () => {
    const { default: userEvent } = await import('@testing-library/user-event')
    const ue = userEvent.setup()
    render(<ProductForm onSubmit={mockOnSubmit} />)

    const btn = screen.getByText('管理分类')
    await ue.click(btn)

    // 弹窗标题「分类管理」应出现
    expect(screen.getByText('添加分类')).toBeTruthy()
  })
})

// ========== #2908: 校验失败提示可见性 ==========

describe('ProductForm (#2908 — 校验失败提示可见性)', () => {
  const mockOnSubmit = vi.fn().mockResolvedValue(undefined)

  it('提交校验失败时顶部出现错误汇总横幅（必填数量 + 查看第一处问题）', async () => {
    const { default: userEvent } = await import('@testing-library/user-event')
    const ue = userEvent.setup()
    // jsdom 未实现 scrollIntoView，validate() 滚动到首错会触发
    Element.prototype.scrollIntoView = vi.fn()

    render(<ProductForm onSubmit={mockOnSubmit} />)

    await ue.click(screen.getByText('提交并上架'))

    const alert = screen.getByRole('alert')
    expect(alert.textContent).toContain('表单校验未通过')
    expect(alert.textContent).toMatch(/\d+ 处必填/)
    // 空表单必填项：标题/货号/计价单位/分类/主图/颜色/售卖方式/规格尺寸 = 8 处
    expect(alert.textContent).toContain('8 处必填')
    // 提供「查看第一处问题」按钮
    expect(screen.getByText('查看第一处问题')).toBeTruthy()
    // 校验失败不调提交
    expect(mockOnSubmit).not.toHaveBeenCalled()
  })

  it('修复一处错误后重新提交，汇总数量减少', async () => {
    const { default: userEvent } = await import('@testing-library/user-event')
    const ue = userEvent.setup()
    Element.prototype.scrollIntoView = vi.fn()

    render(<ProductForm onSubmit={mockOnSubmit} />)

    await ue.click(screen.getByText('提交并上架'))
    expect(screen.getByRole('alert').textContent).toContain('8 处必填')

    // 填写商品标题后重提交 → 7 处
    await ue.type(screen.getByPlaceholderText('最多可输入50汉字（100字符）'), '测试商品')
    await ue.click(screen.getByText('提交并上架'))
    expect(screen.getByRole('alert').textContent).toContain('7 处必填')
  })
})

// ========== 售卖方式 / 1 卷米数 = 商品基础属性（PR-042 / PR-043）==========
//
// 用户裁定：「商品的售卖方式整卷/散件**不能作为 SKU 的组合项**，只能作为基础属性」；
// 「商品需要增加 1 卷=多少米，作为**商品货号的基础参数**」。
// ⇒ 两个控件都在**基础属性**区（`基础信息` section），提交时走请求体**顶层**。
describe('售卖方式与卷长：商品基础属性（PR-042 / PR-043）', () => {
  const mockOnSubmit = vi.fn().mockResolvedValue(undefined)

  /** 一个除「售卖方式 / 卷长」外全部合法的编辑态表单（提交校验可通过） */
  const validInitialData = {
    name: '遮光窗帘',
    skuCode: 'CUR-001',
    unit: '米',
    categoryId: 'cat-1',
    images: ['https://example.com/a.jpg'],
    colors: [{ id: '1', colorName: '红色', sortOrder: 0 }],
    sellingMethods: [] as ('bulk_cut' | 'full_roll')[],
    doorWidths: ['2.8'],
    skus: [
      {
        id: '1',
        colorId: '1',
        colorName: '红色',
        doorWidth: '2.8',
        price: 100,
        stock: 10,
        status: 'active' as const,
      },
    ],
    status: 'draft' as const,
  }

  it('PR-042: 售卖方式 / 卷长控件在「基础信息」区（不在 SKU 矩阵里）', () => {
    render(<ProductForm onSubmit={mockOnSubmit} />)

    const baseSection = screen.getByText('基础信息').closest('section') as HTMLElement
    expect(baseSection).toBeTruthy()
    // 两个控件都在基础属性区
    expect(within(baseSection).getByTestId('pf-selling-methods')).toBeTruthy()
    expect(within(baseSection).getByTestId('pf-roll-length')).toBeTruthy()
    expect(within(baseSection).getByText('售卖方式')).toBeTruthy()
    expect(within(baseSection).getByText('1 卷 = 多少米')).toBeTruthy()
    // 售卖方式是多选（散剪 / 整卷），沿用既有标签
    expect(within(baseSection).getByText('散剪')).toBeTruthy()
    expect(within(baseSection).getByText('整卷')).toBeTruthy()
    // SKU 矩阵（本测试里被 mock）**不**承载售卖方式
    expect(within(screen.getByTestId('sku-matrix')).queryByText('售卖方式')).toBeNull()
  })

  it('PR-043: 提交 ⇒ 顶层带 sellingMethods / rollLengthM，且 skus[] 不带 sellingMethod', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    Element.prototype.scrollIntoView = vi.fn()
    render(<ProductForm initialData={validInitialData} onSubmit={onSubmit} />)

    // 勾「整卷」（商品级基础属性，多选）
    fireEvent.click(screen.getByLabelText('整卷'))
    // 填「1 卷 = 多少米」
    // issue #5218 #4：卷长改用 NumberInput（`type="text"` + 字符串草稿）⇒ role 由 spinbutton 变 textbox
    const rollInput = within(screen.getByTestId('pf-roll-length')).getByRole(
      'textbox'
    ) as HTMLInputElement
    fireEvent.change(rollInput, { target: { value: '60' } })
    expect(rollInput.value).toBe('60')

    fireEvent.click(screen.getByText('提交并上架'))

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1))
    const [payload] = onSubmit.mock.calls[0]
    // ① 顶层字段（不是塞进 skus[]）
    expect(payload.sellingMethods).toEqual(['full_roll'])
    expect(payload.rollLengthM).toBe(60)
    // ② skus[] 里**没有** sellingMethod（SKU 组合只有 颜色 × 门幅）
    expect(payload.skus).toHaveLength(1)
    expect('sellingMethod' in payload.skus[0]).toBe(false)
  })

  it('PR-043: 卷长留空 ⇒ 顶层 rollLengthM 为 null（未配置是合法状态）', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    Element.prototype.scrollIntoView = vi.fn()
    render(<ProductForm initialData={validInitialData} onSubmit={onSubmit} />)

    fireEvent.click(screen.getByLabelText('散剪'))
    fireEvent.click(screen.getByText('提交并上架'))

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1))
    const [payload] = onSubmit.mock.calls[0]
    expect(payload.sellingMethods).toEqual(['bulk_cut'])
    expect(payload.rollLengthM).toBeNull()
  })

  it('PR-043: 卷长填 0 ⇒ 校验拦下（卷长必须大于 0 米），不提交', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    Element.prototype.scrollIntoView = vi.fn()
    render(<ProductForm initialData={validInitialData} onSubmit={onSubmit} />)

    fireEvent.click(screen.getByLabelText('整卷'))
    // issue #5218 #4：卷长改用 NumberInput（`type="text"` + 字符串草稿）⇒ role 由 spinbutton 变 textbox
    const rollInput = within(screen.getByTestId('pf-roll-length')).getByRole(
      'textbox'
    ) as HTMLInputElement
    fireEvent.change(rollInput, { target: { value: '0' } })
    fireEvent.click(screen.getByText('提交并上架'))

    expect(await screen.findByText('卷长必须大于 0 米')).toBeTruthy()
    expect(onSubmit).not.toHaveBeenCalled()
  })

  // issue #5218 #4：旧形态 `type="number"` + `Number(e.target.value)` 往返 ⇒ "0." 中间态被吃掉。
  it('卷长逐键 0 → . → 5 打出 "0.5"（issue #5218 #4 红证）', async () => {
    render(<ProductForm initialData={validInitialData} onSubmit={vi.fn()} />)
    fireEvent.click(screen.getByLabelText('整卷'))
    const rollInput = within(screen.getByTestId('pf-roll-length')).getByRole(
      'textbox'
    ) as HTMLInputElement

    fireEvent.change(rollInput, { target: { value: '0' } })
    expect(rollInput.value).toBe('0')
    fireEvent.change(rollInput, { target: { value: '0.' } })
    // 红证（单点变异）：把本格改回 `type="number"` + `Number(...)` ⇒ 本断言收到 ''（中间态被吞）
    expect(rollInput.value).toBe('0.')
    fireEvent.change(rollInput, { target: { value: '0.5' } })
    expect(rollInput.value).toBe('0.5')
    fireEvent.blur(rollInput)
    expect(rollInput.value).toBe('0.5')
  })

  it('PR-043: 售卖方式一项都没勾 ⇒ 校验拦下（沿用原规则，只是位置变了）', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    Element.prototype.scrollIntoView = vi.fn()
    render(<ProductForm initialData={validInitialData} onSubmit={onSubmit} />)

    fireEvent.click(screen.getByText('提交并上架'))

    expect(await screen.findByText('请至少添加 1 种售卖方式')).toBeTruthy()
    expect(onSubmit).not.toHaveBeenCalled()
  })
})
