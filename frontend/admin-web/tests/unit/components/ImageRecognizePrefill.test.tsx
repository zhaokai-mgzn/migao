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
})