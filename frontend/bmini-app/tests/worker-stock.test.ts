// case_ids: BM-056
/**
 * 工人端**库存修正**的纯逻辑（issue #8104）——
 * 页面只做接线，校验口径 / 提交体字段集 / 回执文案都在 `src/utils/workerStock.ts` 里，
 * 由本文件逐值钉住（页面测试只能证明「点了有没有发请求」）。
 *
 * | # | 判据 | 红证（怎么让它单独变红） |
 * |---|---|---|
 * | ① | **提交体是构造式白名单**：只有 5 个键，**没有** worker_id / worker_name / tenant_id | 把身份字段塞进 body ⇒ 键集断言红 |
 * | ② | **米数口径与库存链路同一把尺**：非负、最多 1 位小数、非数字/空 ⇒ 明确文案 | 放行 `-1` / `42.55` / `abc` ⇒ 红 |
 * | ③ | **三态分开说**：applied / unchanged / replayed 三句**互不相同**，未知状态如实显示 | 三态并成一句「提交成功」⇒ 红 |
 * | ④ | **缺值不冒充 0**：米数缺值 ⇒ `—`；差异 0 ⇒ 「无差异」（不印 `+0`） | 缺值回落 0 ⇒ 红 |
 * | ⑤ | **幂等键形态合法**：非空、≤48、只含字母数字连字符（服务端准入同口径） | 生成带空格的串 ⇒ 红 |
 */
import {
  MAX_NOTE_LENGTH,
  buildCorrectionBody,
  describeCorrection,
  formatDelta,
  formatMeters,
  newCorrectionRequestId,
  parseActualMeters,
  rowSubtitle,
  type StockBatchRow,
} from '../src/utils/workerStock'

const ROW: StockBatchRow = {
  batch_id: 7,
  batch_no: 'PC-20261020-0007',
  product_id: 'prod-1',
  product_name: '雪尼尔窗帘布',
  sku_code: '2659-04-28',
  dye_lot: 'A12',
  inbound_no: 'RK-20261020-0001',
  received_date: '2026-10-20',
  remaining_meters: 45.5,
}

describe('parseActualMeters（与服务端 StockQuantity.requireOneDecimal 同口径）', () => {
  it('① 合法值：整数 / 1 位小数都接受，原样返回数值', () => {
    expect(parseActualMeters('42')).toEqual({ value: 42, error: '' })
    expect(parseActualMeters(' 42.5 ')).toEqual({ value: 42.5, error: '' })
    expect(parseActualMeters('0')).toEqual({ value: 0, error: '' })
  })

  it('② 空值 / 非数字 / 超 1 位小数 ⇒ value 必为 null + 可行动文案（不给半合法值）', () => {
    expect(parseActualMeters('').value).toBeNull()
    expect(parseActualMeters('').error).toContain('请填实盘米数')
    expect(parseActualMeters('abc').value).toBeNull()
    expect(parseActualMeters('-1').value).toBeNull()
    expect(parseActualMeters('-1').error).toContain('只能填数字')
    expect(parseActualMeters('42.55').value).toBeNull()
    expect(parseActualMeters('42.55').error).toContain('1 位小数')
  })
})

describe('buildCorrectionBody（构造式白名单）', () => {
  it('③ 只有 5 个键；身份 / 租户字段**结构上不存在**', () => {
    const body = buildCorrectionBody(ROW, 42.5, 'miscount', '  裁过一截  ', 'req-1')
    expect(Object.keys(body).sort()).toEqual(
      ['actual_meters', 'batch_id', 'client_request_id', 'note', 'reason'].sort(),
    )
    expect(body.batch_id).toBe(7)
    expect(body.actual_meters).toBe(42.5)
    expect(body.reason).toBe('miscount')
    // 备注去掉首尾空白（不把空格当内容发上去）
    expect(body.note).toBe('裁过一截')
    expect(body.client_request_id).toBe('req-1')
    expect(body).not.toHaveProperty('worker_id')
    expect(body).not.toHaveProperty('worker_name')
    expect(body).not.toHaveProperty('tenant_id')
  })

  it('④ 空备注 ⇒ 不带 note 键（不是空串、不是 null）', () => {
    const body = buildCorrectionBody(ROW, 42, 'other', '   ', 'req-2')
    expect(body).not.toHaveProperty('note')
  })

  it('⑤ 备注超长 ⇒ 截到上限（不把脏值发给服务端）', () => {
    const body = buildCorrectionBody(ROW, 42, 'other', '备'.repeat(MAX_NOTE_LENGTH + 20), 'req-3')
    expect(body.note).toHaveLength(MAX_NOTE_LENGTH)
  })
})

describe('回执文案（三态分开说）', () => {
  const base = {
    batch_id: 7,
    batch_no: 'PC-20261020-0007',
    before_meters: 45.5,
    actual_meters: 42,
    delta_meters: -3.5,
    after_meters: 42,
  }

  it('⑥ applied / unchanged / replayed 三句互不相同，且各说清了「有没有写入」', () => {
    const applied = describeCorrection({ ...base, status: 'applied' })
    const unchanged = describeCorrection({ ...base, status: 'unchanged', delta_meters: 0, before_meters: 42 })
    const replayed = describeCorrection({ ...base, status: 'replayed' })
    expect(applied).toContain('已修正')
    expect(applied).toContain('45.5')
    expect(applied).toContain('42')
    expect(unchanged).toContain('与系统一致')
    expect(unchanged).toContain('未写入')
    expect(replayed).toContain('此前已记过账')
    expect(new Set([applied, unchanged, replayed]).size).toBe(3)
  })

  it('⑦ 未知 / 缺状态 ⇒ 如实说，不猜成成功', () => {
    expect(describeCorrection({ ...base, status: 'weird' })).toContain('weird')
    expect(describeCorrection({ ...base, status: '' })).toContain('未返回状态')
    expect(describeCorrection(null)).toContain('未返回状态')
  })
})

describe('格式（缺值不冒充 0）', () => {
  it('⑧ 米数：缺值 ⇒ —；整数不带 .0；小数保留 1 位', () => {
    expect(formatMeters(null)).toBe('—')
    expect(formatMeters(undefined)).toBe('—')
    expect(formatMeters('')).toBe('—')
    expect(formatMeters(42)).toBe('42 米')
    expect(formatMeters('42.5')).toBe('42.5 米')
  })

  it('⑨ 差异：0 ⇒ 「无差异」（不印 +0）；正负都带符号', () => {
    expect(formatDelta(0)).toBe('无差异')
    expect(formatDelta(-3.5)).toBe('-3.5 米')
    expect(formatDelta(2)).toBe('+2 米')
    expect(formatDelta(null)).toBe('—')
  })

  it('⑩ 行副标题：品名 · 货号 · 缸号，缺的跳过；全缺 ⇒ —（不摆内部 id）', () => {
    expect(rowSubtitle(ROW)).toBe('雪尼尔窗帘布 · 2659-04-28 · A12')
    expect(rowSubtitle({ ...ROW, dye_lot: null, sku_code: null })).toBe('雪尼尔窗帘布')
    expect(rowSubtitle({ batch_id: 1, batch_no: 'PC-1' })).toBe('—')
  })
})

describe('幂等键', () => {
  it('⑪ 形态符合服务端准入（≤48、只含字母数字连字符）且两次不同', () => {
    const a = newCorrectionRequestId()
    const b = newCorrectionRequestId()
    expect(a).toMatch(/^[A-Za-z0-9-]+$/)
    expect(a.length).toBeLessThanOrEqual(48)
    expect(a).not.toBe(b)
  })
})
