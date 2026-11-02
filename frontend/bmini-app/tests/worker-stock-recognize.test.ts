// case_ids: BM-056
/**
 * 工人库存修正 · **拍照识别批次号**的纯逻辑（issue #8210；用户 2026-10-31 逐字
 * 「通过拍照来识别批次号」）。
 *
 * ## 这一层为什么是纯函数
 *
 * 入口顺序（**扫标签二维码优先 = 0 次 LLM**，解不出才让服务端走 vision）是**成本守卫**
 * —— 把它写在页面的 `onClick` 里，下一个人加一条「重试」分支就可能把 vision 排到前面，
 * 而没有任何东西会变红（同 `inbound/recognizeFlow.ts` 的既有理由）。
 * 这里用一个**假服务端**计数：命中标签码时 `recognize` 一次都不许被调用。
 *
 * ## 判据（每条都能单独变红）
 *
 * | # | 判据 | 红证（怎么让它单独变红） |
 * |---|---|---|
 * | ① | 标签二维码命中 ⇒ 按短码读详情拿批次号，**upload / vision 零调用** | 把 vision 排到最前 ⇒ 计数断言红 |
 * | ② | 标签**还没有批次号**（未过账 / 草稿）⇒ 如实说，**不**退回 OCR 去猜 | 退化成 vision ⇒ 计数断言红 |
 * | ③ | 洗水唛 / 陌生码 / 非法码**不算命中** ⇒ 走兜底（不是「读到了」） | 不判码空间 ⇒ 用例红 |
 * | ④ | 解不出码 ⇒ 上传 1~3 张后问 vision，只认 `batch_no` 一格 | 取别的键当批次号 ⇒ 用例红 |
 * | ⑤ | 没认出来（degraded / 空值）⇒ 给**手输出路**，不静默 | 返回空 notice ⇒ 用例红 |
 * | ⑥ | vision 401 ⇒ `statusCode` 透出（页面据此引导登录，不渲染成「没认出来」） | 吞掉 401 ⇒ 用例红 |
 * | ⑦ | 精确定位：批次号相等才选中；0 行 ⇒ `not-found`；多行 ⇒ `ambiguous`（**不自动选**） | 用 `includes` 模糊匹配 ⇒ 用例红 |
 */
import {
  STOCK_LABEL_LOOKUP_FAILED_HINT,
  STOCK_LABEL_NO_BATCH_HINT,
  STOCK_RECOGNIZE_MAX_PHOTOS,
  STOCK_RECOGNIZE_MANUAL_HINT,
  locateByBatchNo,
  normalizeBatchNo,
  pickRecognizedBatchNo,
  runStockRecognize,
} from '../src/utils/workerStockRecognize'
import type { StockBatchRow } from '../src/utils/workerStock'

const PHOTO = { tempFilePath: '/tmp/label.jpg' }
const PHOTO2 = { tempFilePath: '/tmp/label2.jpg' }

function row(overrides: Partial<StockBatchRow> = {}): StockBatchRow {
  return {
    batch_id: 7,
    batch_no: 'PC-20261031-0001',
    product_name: '雪尼尔窗帘布',
    sku_code: '2659-04-28',
    dye_lot: 'A12',
    remaining_meters: 45.5,
    ...overrides,
  }
}

/** 假服务端：每个依赖都计数，用来钉住「本机解码命中 ⇒ 一次 LLM 都不烧」。 */
function deps(overrides: Record<string, any> = {}) {
  const calls = {
    decode: 0,
    lookup: 0,
    upload: 0,
    recognize: 0,
  }
  const run = {
    photos: [PHOTO],
    decode: async () => {
      calls.decode += 1
      return { text: null, source: null, hint: '' }
    },
    lookupLabelBatchNo: async () => {
      calls.lookup += 1
      return { batchNo: null }
    },
    upload: async () => {
      calls.upload += 1
      return 'https://cdn.example.com/label.jpg'
    },
    recognize: async () => {
      calls.recognize += 1
      return { success: true, data: { fields: [], degraded: true } }
    },
    ...overrides,
  }
  return { deps: run as any, calls }
}

// ═══════════════════════════════════════════════════ ① 归一 / 精确定位

describe('批次号归一与精确定位', () => {
  it('归一 = 去空白 + 大写（只做无损动作，不改数字）', () => {
    expect(normalizeBatchNo(' pc-2026 1031-0001 ')).toBe('PC-20261031-0001')
    expect(normalizeBatchNo(null)).toBe('')
    expect(normalizeBatchNo('批次A12')).toBe('批次A12')
  })

  it('从识别字段表里只认 batch_no（值非空才算；别的键不当批次号）', () => {
    expect(pickRecognizedBatchNo([{ key: 'batch_no', value: 'pc-20261031-0001' }])).toBe(
      'PC-20261031-0001',
    )
    expect(pickRecognizedBatchNo([{ key: 'batch_no', value: null }])).toBeNull()
    expect(pickRecognizedBatchNo([{ key: 'sku_code', value: '2659-04-28' }])).toBeNull()
    expect(pickRecognizedBatchNo(null)).toBeNull()
  })

  it('定位只看批次号**相等**：命中 1 行才自动选中', () => {
    expect(locateByBatchNo([row(), row({ batch_id: 8, batch_no: 'PC-20261031-0002' })],
      'pc-20261031-0001')).toEqual({ kind: 'selected', row: row() })
  })

  it('0 行 ⇒ not-found（不是「没有批次」的空态）', () => {
    expect(locateByBatchNo([row()], 'PC-20261031-9999')).toEqual({
      kind: 'not-found',
      batchNo: 'PC-20261031-9999',
    })
  })

  it('多行同号 ⇒ ambiguous，交给工人点选（不自动选 —— 认错批次就是改错那一卷的账）', () => {
    const rows = [row(), row({ batch_id: 99 })]
    expect(locateByBatchNo(rows, 'PC-20261031-0001')).toEqual({ kind: 'ambiguous', rows })
  })

  it('模糊命中不算命中：`PC-20261031-0001` 不得被 `PC-20261031-00011` 冒充', () => {
    expect(locateByBatchNo([row({ batch_no: 'PC-20261031-00011' })], 'PC-20261031-0001')).toEqual({
      kind: 'not-found',
      batchNo: 'PC-20261031-0001',
    })
  })
})

// ═══════════════════════════════════════════════════ ②③ 扫标签二维码优先（0 次 LLM）

describe('扫标签二维码优先（0 次 LLM）', () => {
  it('标签码命中 ⇒ 读详情拿批次号；upload / vision 一次都不调用', async () => {
    const { deps: d, calls } = deps({
      decode: async () => ({
        text: 'https://app.migaozn.com/i/7K3M9QP2',
        source: 'h5-dom-canvas',
        hint: '',
      }),
      lookupLabelBatchNo: async () => {
        calls.lookup += 1
        return { batchNo: 'PC-20261031-0001' }
      },
    })

    const outcome = await runStockRecognize(d)

    expect(outcome.route).toBe('label-qr')
    expect(outcome.batchNo).toBe('PC-20261031-0001')
    expect(outcome.expectedLlmCalls).toBe(0)
    expect(outcome.notice).toBe('')
    expect(calls.lookup).toBe(1)
    expect(calls.upload).toBe(0)
    expect(calls.recognize).toBe(0)
  })

  it('标签还没有批次号（未过账）⇒ 如实说，不退回 OCR 去猜', async () => {
    const { deps: d, calls } = deps({
      decode: async () => ({
        text: 'https://app.migaozn.com/i/7K3M9QP2',
        source: 'h5-dom-canvas',
        hint: '',
      }),
      lookupLabelBatchNo: async () => ({ batchNo: null }),
    })

    const outcome = await runStockRecognize(d)

    expect(outcome.route).toBe('label-qr')
    expect(outcome.batchNo).toBeNull()
    expect(outcome.notice).toBe(STOCK_LABEL_NO_BATCH_HINT)
    expect(calls.recognize).toBe(0)
  })

  it('标签读取失败 ⇒ 可行动文案（**不**把读不到当成「没批次」）', async () => {
    const { deps: d } = deps({
      decode: async () => ({
        text: 'https://app.migaozn.com/i/7K3M9QP2',
        source: 'h5-dom-canvas',
        hint: '',
      }),
      lookupLabelBatchNo: async () => ({ batchNo: null, failed: true }),
    })

    const outcome = await runStockRecognize(d)

    expect(outcome.batchNo).toBeNull()
    expect(outcome.notice).toBe(STOCK_LABEL_LOOKUP_FAILED_HINT)
  })

  it('洗水唛 / 陌生码不算命中 ⇒ 走兜底（它不是入库标签）', async () => {
    const { deps: d, calls } = deps({
      decode: async () => ({
        text: 'https://app.migaozn.com/s/7K3M9QP2',
        source: 'h5-dom-canvas',
        hint: '',
      }),
    })

    const outcome = await runStockRecognize(d)

    expect(outcome.route).toBe('vision')
    expect(calls.lookup).toBe(0)
    expect(calls.recognize).toBe(1)
  })
})

// ═══════════════════════════════════════════════════ ④⑤⑥ 拍照 OCR 兜底

describe('拍照 OCR 兜底', () => {
  it('解不出码 ⇒ 上传 1 张后问 vision，只认 batch_no 一格', async () => {
    const { deps: d, calls } = deps({
      recognize: async () => {
        calls.recognize += 1
        return {
          success: true,
          data: {
            targetType: 'batch',
            fields: [{ key: 'batch_no', value: 'PC-20261031-0001', source: '[图片识别]' }],
            degraded: false,
          },
        }
      },
    })

    const outcome = await runStockRecognize(d)

    expect(outcome.route).toBe('vision')
    expect(outcome.batchNo).toBe('PC-20261031-0001')
    expect(outcome.expectedLlmCalls).toBe(1)
    expect(calls.upload).toBe(1)
    expect(calls.recognize).toBe(1)
  })

  it.each([
    ['degraded', { success: true, data: { fields: [], degraded: true } }],
    ['空值', { success: true, data: { fields: [{ key: 'batch_no', value: null }], degraded: false } }],
  ])('vision %s ⇒ 给手输出路（不静默）', async (_label, response) => {
    const { deps: d } = deps({ recognize: async () => response })

    const outcome = await runStockRecognize(d)

    expect(outcome.batchNo).toBeNull()
    expect(outcome.notice).toBe(STOCK_RECOGNIZE_MANUAL_HINT)
  })

  it('vision 401 ⇒ statusCode 透出（页面引导登录，不渲染成「没认出来」）', async () => {
    const { deps: d } = deps({
      recognize: async () => ({ success: false, statusCode: 401, message: '工人身份已失效' }),
    })

    const outcome = await runStockRecognize(d)

    expect(outcome.statusCode).toBe(401)
    expect(outcome.notice).toBe('')
  })

  it('一次最多传 3 张（多拍不会更准，只会多等一轮）', async () => {
    const photos = [PHOTO, PHOTO2, PHOTO, PHOTO]
    const uploaded: string[] = []
    const { deps: d } = deps({
      photos,
      upload: async () => {
        uploaded.push('https://cdn.example.com/x.jpg')
        return 'https://cdn.example.com/x.jpg'
      },
    })

    await runStockRecognize(d)

    expect(STOCK_RECOGNIZE_MAX_PHOTOS).toBe(3)
    expect(uploaded).toHaveLength(3)
  })
})
