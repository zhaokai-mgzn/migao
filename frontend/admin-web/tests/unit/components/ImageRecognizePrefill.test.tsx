// case_ids: PR-008, OR-008
/**
 * 图片识别预填映射（issue #5321 包 1）——**纯函数**面：不渲染 4965 行的建单页，
 * 直接在 `lib/image-recognize.ts` 上断言「识别结果 → 表单值 / 徽标清单」的确切产物。
 *
 * 三条口径（与内核冻结契约一致）：
 * ① `value: null` 的字段**绝不写进表单**（内核有意留空，不确定的宁可不填）；
 * ② 商品侧只映射能从既有代码论证的键（售价**有意不映射**）；
 * ③ 订单侧**只填当前为空的字段**（错收货信息 = 货发错人），明细/数量进备注；
 * ④ **尺寸（帘宽 / 帘高）进的是行状态**（issue #5349：推导链的原始输入）——
 *    只收能直接进数字框的数，落点由 `sizeTargetLineIndex` 定（**空行**才填）。
 * ⑤ **商品描述文案**（issue #6362）—— 预填到既有富文本区 `description`（**不新增落库字段**）；
 *    它是**推理产物**（`source` = `[米宝解读]`）⇒ 空值 / 缺失时**键不出现**（绝不写成空串：
 *    那会覆盖商家自己写的描述）。不覆盖的机制 = 「有值才写键」+ 表单合并式预填
 *    （`setForm(prev => ({...prev, ...initialData}))`，见本文件「不覆盖」用例）。
 */
import { act, render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import {
  buildOrderPrefill,
  buildProductPrefill,
  filledFields,
  RECOGNIZE_SOURCE_TAG,
  sizeTargetLineIndex,
} from '@/lib/image-recognize'
import type { RecognizedField } from '@/lib/api'
import { PAGE_FILL_SOURCE_INTERPRETED } from '@/lib/agent-page-fill'
import ProductForm from '@/components/products/ProductForm'

vi.mock('next/image', () => ({
  default: (props: Record<string, unknown>) => {
    const React = require('react')
    return React.createElement('img', { ...props, src: props.src || '' })
  },
}))

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return {
    ...actual,
    categoryApi: { getCategories: vi.fn().mockResolvedValue({ data: { data: [] } }) },
    fileApi: { uploadFile: vi.fn() },
  }
})

const TAG = RECOGNIZE_SOURCE_TAG

const PRODUCT_FIELDS: RecognizedField[] = [
  { key: 'name', label: '商品名称', value: '雪尼尔遮光窗帘', source: TAG, reason: null },
  { key: 'color', label: '颜色', value: '米白', source: TAG, reason: null },
  { key: 'material', label: '材质', value: '聚酯纤维', source: TAG, reason: null },
  { key: 'craft', label: '工艺', value: '韩式褶', source: TAG, reason: null },
  { key: 'door_width', label: '门幅', value: '门幅2.8米', source: TAG, reason: null },
  { key: 'price', label: '售价', value: '199', source: TAG, reason: null },
]

/** 内核有意留空的形态：`value: null` + `reason`，且**不得**进表单 */
const PRODUCT_FIELDS_BLANKED: RecognizedField[] = [
  { key: 'material', label: '材质', value: null, source: null, reason: '图片未标注材质' },
  { key: 'craft', label: '工艺', value: null, source: null, reason: '图片未标注工艺' },
]

const ORDER_FIELDS: RecognizedField[] = [
  { key: 'customer_name', label: '客户名', value: '张伟', source: TAG, reason: null },
  { key: 'customer_phone', label: '电话', value: '13800138000', source: TAG, reason: null },
  {
    key: 'customer_address',
    label: '地址',
    value: '浙江省杭州市余杭区仓前街道 1 号',
    source: TAG,
    reason: null,
  },
  { key: 'items', label: '商品明细', value: '遮光窗帘', source: TAG, reason: null },
  { key: 'quantity', label: '数量', value: '2', source: TAG, reason: null },
  { key: 'curtain_width', label: '帘宽', value: '2.8', source: TAG, reason: null },
  { key: 'curtain_height', label: '帘高', value: '2.4', source: TAG, reason: null },
]

const ORDER_REMARK_LINE = '[图片识别] 商品明细：遮光窗帘；数量：2'

const EMPTY_ORDER = { customerName: '', customerPhone: '', customerAddress: '', remark: '' }

describe('图片识别 · 商品侧预填 (#5321)', () => {
  it('只有有值的字段才是预填候选（value:null 一律排除）', () => {
    expect(filledFields(PRODUCT_FIELDS).map((f) => f.key)).toEqual([
      'name',
      'color',
      'material',
      'craft',
      'door_width',
      'price',
    ])
    expect(filledFields(PRODUCT_FIELDS_BLANKED)).toEqual([])
  })

  it('映射到商品表单：标题 / 规格属性（表单内部英文 key）/ 颜色 / 门幅（归一后）', () => {
    const { initialData, recognizedFields } = buildProductPrefill(PRODUCT_FIELDS)

    expect(initialData.name).toBe('雪尼尔遮光窗帘')
    // 表单内部规格 key 是英文（ProductAttributes 读 specifications.material / .craft），
    // 提交时由 ProductForm 的 toChineseSpecKeys 转「材质 / 工艺」落库
    expect(initialData.specifications).toEqual({ material: '聚酯纤维', craft: '韩式褶' })
    expect((initialData.colors || []).map((c) => c.colorName)).toEqual(['米白'])
    expect(initialData.doorWidths).toEqual(['2.8'])
    expect(recognizedFields).toEqual(['name', 'material', 'craft', 'color', 'door_width'])
  })

  it('颜色 × 门幅经既有 rebuildSkus 落成 SKU 矩阵行（价格/库存留 0 由商家填）', () => {
    const { initialData } = buildProductPrefill(PRODUCT_FIELDS)

    expect((initialData.skus || []).map((s) => ({
      colorName: s.colorName,
      doorWidth: s.doorWidth,
      price: s.price,
      stock: s.stock,
    }))).toEqual([{ colorName: '米白', doorWidth: '2.8', price: 0, stock: 0 }])
    // SKU 行必须挂在刚建的颜色上（否则矩阵里是两套颜色）
    expect(initialData.skus?.[0].colorId).toBe(initialData.colors?.[0].id)
  })

  it('售价**有意不映射**：顶层 price 在商品页上没有任何控件显示，预填了商家看不见也改不了', () => {
    const { initialData, recognizedFields } = buildProductPrefill(PRODUCT_FIELDS)

    expect('price' in initialData).toBe(false)
    expect(recognizedFields.includes('price')).toBe(false)
  })

  it('留空字段与非法门幅都不写表单（门幅只收数字）', () => {
    const blanked = buildProductPrefill(PRODUCT_FIELDS_BLANKED)
    expect(blanked.initialData).toEqual({})
    expect(blanked.recognizedFields).toEqual([])

    const garbage = buildProductPrefill([
      { key: 'door_width', label: '门幅', value: '深灰色', source: TAG, reason: null },
    ])
    expect(garbage.initialData.doorWidths).toBeUndefined()
    expect(garbage.recognizedFields).toEqual([])
  })
})

describe('图片识别 · 商品描述文案预填 (#6362)', () => {
  /** 米宝解读产出的描述（HTML 片段，来源恒为 `[米宝解读]`）—— 落点是既有的富文本区 */
  const INTERPRETED_TAG = '[米宝解读]'
  const DESCRIPTION_HTML =
    '<p>雪尼尔遮光窗帘，面料厚实、垂感好，适合客厅与卧室；可选配韩式褶工艺，支持机洗。</p>'
  const DESCRIPTION_FIELD: RecognizedField = {
    key: 'description',
    label: '商品描述',
    value: DESCRIPTION_HTML,
    source: INTERPRETED_TAG,
    reason: null,
  }

  it('描述文案**逐字**写进富文本区初值，并计入 recognizedFields（页面据此分派 [米宝解读] 徽标）', () => {
    const { initialData, recognizedFields } = buildProductPrefill([DESCRIPTION_FIELD])

    // 逐字相等（不是"包含"）：HTML 片段被改写 / 截断 / trim 掉首尾都算红
    expect(initialData.description).toBe(DESCRIPTION_HTML)
    expect(recognizedFields).toContain('description')
    // 描述之外没有凭空多出来的键
    expect(recognizedFields).toEqual(['description'])
  })

  it('描述为空 / 缺失 ⇒ 键**不出现**（绝不写成空串 —— 那会覆盖商家自己写的描述）', () => {
    // 先钉住"有值时确实落键"（否则下面那组 `in` 断言在未接线时会**空跑通过** —— 绿得毫无意义）
    expect('description' in buildProductPrefill([DESCRIPTION_FIELD]).initialData).toBe(true)

    const cases: RecognizedField[][] = [
      // 内核有意留空：`value: null` + `reason`（与 PRODUCT_FIELDS_BLANKED 同形态）
      [
        {
          key: 'description',
          label: '商品描述',
          value: null,
          source: null,
          reason: '图片信息不足，无法生成描述文案',
        },
      ],
      // 空白串（`filledFields` 口径里同样算"没值"）
      [{ key: 'description', label: '商品描述', value: '   ', source: null, reason: null }],
      // 完全没有这条字段
      [],
    ]
    for (const fields of cases) {
      const { initialData, recognizedFields } = buildProductPrefill(fields)
      expect('description' in initialData).toBe(false)
      expect(initialData.description).toBeUndefined()
      expect(recognizedFields).not.toContain('description')
    }
  })

  it('判别力自证：若预填改成"空值也写键"，合并式落值立刻覆盖商家描述（注入式红证）', () => {
    // 本仓最忌「判据绿而判据从没跑过」⇒ 同一份合并式落值（`{...prev, ...initialData}`）下对照两态：
    // 被禁形态 = 空值也写键（`description: ''`）⇒ 商家原文被空串顶掉；本包形态 = 键不出现 ⇒ 一个字不动。
    const mergeOver = (initialData: Partial<Record<'description', string>>) => ({
      description: '<p>商家自己写的描述</p>',
      ...initialData,
    })
    // 本包的真实产物：空字段 ⇒ 空对象（没有 description 键）
    expect(buildProductPrefill([]).initialData).toEqual({})
    expect(mergeOver(buildProductPrefill([]).initialData).description).toBe('<p>商家自己写的描述</p>')
    // 注入被禁形态：立刻把商家原文顶成空串（这就是本判据要拦住的那件事）
    expect(mergeOver({ description: '' }).description).toBe('')
  })

  it('不覆盖：空预填产物是空对象 ⇒ 合并式落值（`{...prev, ...initialData}`）不动商家已写的描述', () => {
    // 这就是"不覆盖"的机制：`ProductForm` 的落值是 `setForm(prev => ({...prev, ...initialData}))`
    // ⇒ 只要 `buildProductPrefill` 在没值时**不写这个键**，商家已有的描述就一个字都不会变。
    expect(buildProductPrefill([]).initialData).toEqual({})
    expect(
      'description' in buildProductPrefill(PRODUCT_FIELDS_BLANKED).initialData,
    ).toBe(false)
  })

  it('富文本区渲染商家自己的描述（编辑态 initialData 非空；空预填不参与合并）', async () => {
    render(
      <ProductForm
        initialData={{ name: '雪尼尔遮光窗帘', description: '<p>商家自己写的描述</p>' }}
        onSubmit={vi.fn()}
      />,
    )
    await act(async () => {})

    expect(screen.getByText('商家自己写的描述')).toBeTruthy()
  })

  it('米宝解读来源的描述在富文本区挂 `[米宝解读]` 徽标（另一枚徽标，不可与 [图片识别] 混同）', async () => {
    render(
      <ProductForm
        initialData={{ name: '雪尼尔遮光窗帘', description: DESCRIPTION_HTML }}
        onSubmit={vi.fn()}
        interpretedFields={['description']}
      />,
    )
    await act(async () => {})

    // 徽标文案 = `[米宝解读]`（与 `[图片识别]` 是两枚不同的徽标：可信度不同，不可混同）
    expect(screen.getByTestId('interpreted-marker-description').textContent).toBe(INTERPRETED_TAG)
    expect(screen.getByTestId('interpreted-marker-description').textContent).not.toBe(TAG)
  })
})

describe('图片识别 · 订单侧预填 (#5321)', () => {
  it('空表单：三个收货字段照填，明细/数量进备注，尺寸进**行状态**（推导链的原始输入）', () => {
    const prefill = buildOrderPrefill(ORDER_FIELDS, EMPTY_ORDER)

    expect(prefill.customerName).toBe('张伟')
    expect(prefill.customerPhone).toBe('13800138000')
    expect(prefill.customerAddress).toBe('浙江省杭州市余杭区仓前街道 1 号')
    expect(prefill.remark).toBe(ORDER_REMARK_LINE)
    // issue #5349：帘宽 / 帘高是**数**（直接进数字框 ⇒ 推导链自然生效）
    expect(prefill.curtainWidth).toBe(2.8)
    expect(prefill.curtainHeight).toBe(2.4)
    expect(prefill.recognizedFields).toEqual([
      'customerName',
      'customerPhone',
      'customerAddress',
      'curtain_width',
      'curtain_height',
      'remark',
    ])
    // 尺寸的落点由纯函数定（页面侧只填空行）⇒ 映射结果里**没有** lineItems（页面侧一行项都不动）
    expect('lineItems' in prefill).toBe(false)
  })

  it('尺寸只收**能直接进数字框**的值（非数 / 非正 ⇒ 不填，交给商家手填）', () => {
    for (const raw of ['2.8米', '门幅2.8', '看不清', '0']) {
      const prefill = buildOrderPrefill(
        [{ key: 'curtain_width', label: '帘宽', value: raw, source: TAG, reason: null }],
        EMPTY_ORDER,
      )
      expect(prefill.curtainWidth).toBeUndefined()
      expect(prefill.recognizedFields).toEqual([])
    }
    // 内核归一后的规范十进制串照收（与 `recognizer._normalise_size` 同口径）
    const ok = buildOrderPrefill(
      [{ key: 'curtain_width', label: '帘宽', value: '2.8', source: TAG, reason: null }],
      EMPTY_ORDER,
    )
    expect(ok.curtainWidth).toBe(2.8)
  })

  it('已有内容的字段**一律不覆盖**、也不打徽标（错收货信息 = 货发错人）', () => {
    const prefill = buildOrderPrefill(ORDER_FIELDS, {
      customerName: '李四',
      customerPhone: '',
      customerAddress: '',
      remark: '',
    })

    expect(prefill.customerName).toBeUndefined()
    expect(prefill.customerPhone).toBe('13800138000')
    expect(prefill.customerAddress).toBe('浙江省杭州市余杭区仓前街道 1 号')
    expect(prefill.recognizedFields).toEqual([
      'customerPhone',
      'customerAddress',
      'curtain_width',
      'curtain_height',
      'remark',
    ])
  })

  it('备注追加在原文之后（换行），重复识别同一张图不重复追加', () => {
    const first = buildOrderPrefill(ORDER_FIELDS, { ...EMPTY_ORDER, remark: '客户要求 3 天内发货' })
    expect(first.remark).toBe(`客户要求 3 天内发货\n${ORDER_REMARK_LINE}`)

    const replay = buildOrderPrefill(ORDER_FIELDS, {
      customerName: first.customerName || '',
      customerPhone: first.customerPhone || '',
      customerAddress: first.customerAddress || '',
      remark: first.remark || '',
    })
    expect(replay.remark).toBeUndefined()
    // 尺寸**不参与"当前值"比较**（行状态在页面侧）：重放仍会回传尺寸，
    // 但页面侧的落点函数会返回 `-1` ⇒ 一行都不动（幂等由落点判据保证，见等价性测试）
    expect(replay.curtainWidth).toBe(2.8)
    expect(replay.recognizedFields).toEqual(['curtain_width', 'curtain_height'])
    expect(sizeTargetLineIndex([{ width: 2.8, height: 2.4 }])).toBe(-1)
  })

  it('留空字段（value:null）既不填表也不进备注', () => {
    const prefill = buildOrderPrefill(
      [
        { key: 'customer_name', label: '客户名', value: null, source: null, reason: '图片未标注客户名' },
        { key: 'items', label: '商品明细', value: null, source: null, reason: '图片未标注商品' },
      ],
      EMPTY_ORDER,
    )

    expect(prefill.customerName).toBeUndefined()
    expect(prefill.remark).toBeUndefined()
    expect(prefill.recognizedFields).toEqual([])
  })
})

describe('ProductForm 的 [图片识别] 徽标 (#5321)', () => {
  it('只标在 recognizedFields 命中的字段上，文案逐字为 [图片识别]', async () => {
    render(
      <ProductForm
        initialData={{ name: '雪尼尔遮光窗帘' }}
        onSubmit={vi.fn()}
        recognizedFields={['name', 'material']}
      />,
    )
    // ProductForm 挂载后异步拉分类（已 mock 成空列表）——等它落定再断言
    await act(async () => {})

    expect(screen.getByTestId('recognized-marker-name').textContent).toBe('[图片识别]')
    expect(screen.getByTestId('recognized-marker-material').textContent).toBe('[图片识别]')
    expect(screen.queryByTestId('recognized-marker-craft')).toBeNull()
    expect(screen.queryByTestId('recognized-marker-color')).toBeNull()
  })

  it('颜色 / 门幅（列表字段）的徽标挂在 SkuMatrix 两处区块标题上 —— 预填了就一定有标注', async () => {
    render(
      <ProductForm
        initialData={{ name: '雪尼尔遮光窗帘' }}
        onSubmit={vi.fn()}
        recognizedFields={['name', 'color', 'door_width']}
      />,
    )
    await act(async () => {})

    // 逐字段标注的**清单必须与 `buildProductPrefill` 实际预填的键一致**：
    // 预填了颜色/门幅却不在表单上标注 ⇒ 商家会把识别值当成自己填的（本用例就是这条判据）。
    expect(screen.getByTestId('recognized-marker-color').textContent).toBe('[图片识别]')
    expect(screen.getByTestId('recognized-marker-door_width').textContent).toBe('[图片识别]')
    expect(screen.getByTestId('recognized-marker-name').textContent).toBe('[图片识别]')
    // 没有预填的键不得凭空长出徽标（标错了比不标更糟：商家会去核对一个不是识别来的格子）
    expect(screen.queryByTestId('recognized-marker-price')).toBeNull()
    expect(screen.queryByTestId('recognized-marker-craft')).toBeNull()
  })

  it('预填键清单与 `[图片识别]` 徽标渲染键**逐一对应**（预填了却没标注 = 红）', async () => {
    const { initialData, recognizedFields } = buildProductPrefill(PRODUCT_FIELDS)
    render(<ProductForm initialData={initialData} onSubmit={vi.fn()} recognizedFields={recognizedFields} />)
    await act(async () => {})

    const badgeKeys = recognizedFields.filter(
      (k) => screen.queryByTestId(`recognized-marker-${k}`) !== null,
    )
    expect(badgeKeys).toEqual(['name', 'material', 'craft', 'color', 'door_width'])
  })

  it('描述格在解读清单里 ⇒ 挂的是 `[米宝解读]` 徽标（两枚徽标各认各的键，不互相静默漏掉）', async () => {
    // 这条把「预填了描述却一枚徽标都不渲染」这条**静默漏标**钉死：`description` 只可能来自
    // `[米宝解读]`（内核不产这一格）⇒ 它进的是解读清单，渲染的必须是 `interpreted-marker-*`。
    render(
      <ProductForm
        initialData={{ description: '<p>米宝生成的描述</p>' }}
        onSubmit={vi.fn()}
        interpretedFields={['description']}
      />,
    )
    await act(async () => {})

    expect(screen.getByTestId('interpreted-marker-description')).toBeTruthy()
    // `description` 不在识别清单里 ⇒ 不得出现 `[图片识别]` 徽标（两枚徽标各认各的键）
    expect(screen.queryByTestId('recognized-marker-description')).toBeNull()
    // 徽标文案逐字 = 页面解读来源标记（与 `[图片识别]` 不同）
    expect(screen.getByTestId('interpreted-marker-description').textContent).toBe(
      PAGE_FILL_SOURCE_INTERPRETED,
    )
  })
})