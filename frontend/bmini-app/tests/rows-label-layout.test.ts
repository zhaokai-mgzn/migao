// case_ids: BM-060, BM-061
/**
 * **50×70 行式标签**（成品入库标签 / 发货联）的版面与渲染判据（issue #8287）。
 *
 * ## 判据（每条都能单独变红）
 *
 * | # | 判据 | 红证（怎么让它单独变红） |
 * |---|---|---|
 * | L1 | 纸型 / 像素口径 / 纸长范围**只来自介质矩阵**（`label-50x70`），画布宽 = 有效打宽 | 把布局里的宽度换成矩阵之外的数 ⇒ 红；改矩阵里 `effectiveWidthPx` ⇒ 版面跟着变 |
 * | L2 | 成品入库标签 = **固定 70mm**；行 / 短码全来自服务端块，缺值印 `—` | 把 `fixedLengthMm` 删掉 ⇒ 纸长按内容缩到 < 70mm ⇒ 红 |
 * | L3 | 发货联 = **按内容撑开**（70~150mm），行序与 `/w/` 相同；可选附注缺值整行不印 | 把 `remark` 改成必印行 ⇒ 行数变多 / 红 |
 * | L4 | 下单日期按 **Asia/Shanghai** 取日（`16:30Z` ⇒ 次日） | 改回 `toISOString().slice(0,10)` ⇒ 红 |
 * | L5 | 预览与打印**同一份计划**；取不到位图 ⇒ **抛错**（不静默打白图） | 去掉 `requirePixels` ⇒ 红 |
 * | L6 | 多行字段（地址 / 安装位置 / 备注）按显式换行 + 宽度折行 | 把换行当普通字符 ⇒ 两行粘成一行 ⇒ 红 |
 */
import { labelGeometry, labelLengthRange, labelPaperBox, SHIP_LABEL_MEDIA_ID } from '../src/utils/inbound/truth'
import {
  ROWS_LABEL_MISSING,
  layoutRowsLabel,
  renderRowsLabel,
  rowsLabelPaper,
  type RowsLabelSpec,
} from '../src/utils/labels/rowsLabel'
import {
  finishedInboundBinText,
  finishedInboundQualityText,
  finishedInboundRows,
  finishedInboundSpec,
  type FinishedInboundView,
} from '../src/utils/labels/finishedInbound'
import {
  buildShipLabelRows,
  setsText,
  shipLabelDateText,
  shipLabelSpec,
  type ReadyShipmentOrderLike,
} from '../src/utils/labels/shipLabel'

const GEOMETRY = labelGeometry(SHIP_LABEL_MEDIA_ID)
const RANGE = labelLengthRange(SHIP_LABEL_MEDIA_ID)
const PAPER = labelPaperBox(SHIP_LABEL_MEDIA_ID)

/** 计划里的文字（按绘制顺序）——版面判据只看「纸上会出现什么」。 */
function texts(spec: RowsLabelSpec): string[] {
  return layoutRowsLabel(spec)
    .ops.filter((op) => op.kind === 'text')
    .map((op) => (op as { text: string }).text)
}

const FINISHED: FinishedInboundView = {
  already: false,
  bin_code: 'A-01',
  inbound_no: 'RK-20261031-001',
  label: {
    rows: [
      { label: '品名', value: '遮光布' },
      { label: '色号', value: '米白' },
      { label: '入库日期', value: '2026-10-31' },
      { label: '数量', value: '3 米' },
    ],
    short_code: 'ABCD2345',
  },
  quality: { result: 'rework', reason: '跳线' },
}

const SHIP: ReadyShipmentOrderLike = {
  order_no: 'SO-20260901-001',
  created_at: '2026-09-01T16:30:00Z',
  customer_name: '张三',
  customer_phone: '13849944707',
  customer_address: '洛阳市涧西区珠江路 18 号 3 单元 502',
  logistics_type: 'logistics',
  logistics_type_label: '物流专线',
  logistics_company: '四季安',
  total_sets: 3,
  completed_sets: 3,
  curtain_types: '布帘/纱帘',
  install_community: '珠江路小区',
  install_rooms: '客厅\n主卧',
  remark: '样品货款 600 元',
}

describe('L1 纸型与像素口径：只从介质矩阵取', () => {
  it('纸型 = 50×70，画布宽 = 有效打宽，纸长范围 = 70~150mm', () => {
    expect(PAPER).toEqual({ widthMm: 50, heightMm: 70 })
    expect(rowsLabelPaper()).toEqual(PAPER)
    expect(GEOMETRY.canvasWidthPx).toBe(GEOMETRY.effectiveWidthPx)
    expect(GEOMETRY.canvasHeightPx).toBe(GEOMETRY.heightPx)
    expect(RANGE).toEqual({ minMm: 70, maxMm: 150 })
  })

  it('画布尺寸跟着矩阵走（不是布局里另写一份）', () => {
    const plan = layoutRowsLabel({ rows: [{ key: 'a', label: 'A', value: '1' }] })
    expect(plan.widthPx).toBe(GEOMETRY.effectiveWidthPx)
    expect(plan.heightPx).toBeGreaterThanOrEqual(Math.round(RANGE.minMm * GEOMETRY.dotsPerMm))
    expect(plan.heightPx).toBeLessThanOrEqual(Math.round(RANGE.maxMm * GEOMETRY.dotsPerMm))
  })
})

describe('L2 成品入库标签：固定 70mm + 服务端字段原样', () => {
  it('卡片文案：仓位缺值 = 未分配；质检无记录 = 正常，有记录 = 词 + 原因', () => {
    expect(finishedInboundBinText(FINISHED)).toBe('A-01')
    expect(finishedInboundBinText({})).toBe('未分配')
    expect(finishedInboundQualityText(FINISHED)).toBe('已记做工返工（原因：跳线）')
    expect(finishedInboundQualityText({ quality: { result: 'pass' } })).toBe('正常')
    expect(finishedInboundQualityText({})).toBe('正常')
  })

  it('行 / 短码 = 服务端 `label` 块原样（前端不补行、不改写）', () => {
    expect(finishedInboundRows(FINISHED).map((row) => [row.label, row.value])).toEqual([
      ['品名', '遮光布'],
      ['色号', '米白'],
      ['入库日期', '2026-10-31'],
      ['数量', '3 米'],
    ])

    const plan = layoutRowsLabel(finishedInboundSpec(FINISHED))
    expect(plan.heightPx).toBe(Math.round(PAPER.heightMm * GEOMETRY.dotsPerMm))
    expect(plan.qr).toBeNull()
    expect(plan.codeText).toBe('ABCD2345')
    const printed = texts(finishedInboundSpec(FINISHED))
    for (const expected of ['品名', '遮光布', '色号', '米白', '入库日期', '2026-10-31', '数量', '3 米', 'ABCD2345']) {
      expect(printed).toContain(expected)
    }
    expect(plan.warnings).toEqual([])
  })

  it('缺值印 —（不是 0、不是空串）', () => {
    const printed = texts({ rows: [{ key: 'remark', label: '备注', value: '' }] })
    expect(printed).toContain(ROWS_LABEL_MISSING)
  })
  it('固定 70mm：内容再多也不撑长（成品入库标签不是连续纸）；超长要登记 warnings', () => {
    expect(finishedInboundSpec(FINISHED).fixedLengthMm).toBe(PAPER.heightMm)
    const manyRows = Array.from({ length: 24 }, (_, index) => ({
      label: `行${index + 1}`,
      value: '内容',
    }))
    const plan = layoutRowsLabel(
      finishedInboundSpec({ ...FINISHED, label: { rows: manyRows, short_code: 'ABCD2345' } }),
    )
    expect(plan.heightPx).toBe(Math.round(PAPER.heightMm * GEOMETRY.dotsPerMm))
    expect(plan.warnings.length).toBeGreaterThan(0)
  })

})

describe('L3 发货联：行序 / 套数 / 可选附注 / 动态纸长', () => {
  it('行序与 /w/ 相同（含随货标识），物流类型**不**拼公司', () => {
    const rows = buildShipLabelRows(SHIP)
    expect(rows.map((row) => row.label)).toEqual([
      '订单号',
      '收货人',
      '电话',
      '地址',
      '帘种',
      '安装小区',
      '安装位置',
      '物流类型',
      '物流公司',
      '下单日期',
      '套数',
      '备注',
    ])
    expect(rows.find((row) => row.key === 'logistics_type')?.value).toBe('物流专线')
    expect(rows.find((row) => row.key === 'sets')?.value).toBe('3 套（全完工）')
  })

  it('可选附注缺值 ⇒ 整行不印；必印行缺值 ⇒ —', () => {
    const rows = buildShipLabelRows({ order_no: 'SO-2' })
    expect(rows.map((row) => row.label)).toEqual([
      '订单号',
      '收货人',
      '电话',
      '地址',
      '物流类型',
      '物流公司',
      '下单日期',
      '套数',
    ])
    expect(rows.find((row) => row.key === 'consignee')?.value).toBe(ROWS_LABEL_MISSING)
    expect(rows.find((row) => row.key === 'order_date')?.value).toBe(ROWS_LABEL_MISSING)
    expect(rows.some((row) => row.key === 'remark')).toBe(false)
  })

  it('套数只读服务端读数（全完工 / 半完工 / 缺 total）', () => {
    expect(setsText({ total_sets: 3, completed_sets: 3 })).toBe('3 套（全完工）')
    expect(setsText({ total_sets: 3, completed_sets: 1 })).toBe('1/3 套')
    expect(setsText({ total_sets: null, completed_sets: 1 })).toBe(ROWS_LABEL_MISSING)
  })

  it('纸长按内容撑开（70~150mm 内），标题「发货联」在纸上', () => {
    const plan = layoutRowsLabel(shipLabelSpec(SHIP))
    expect(plan.heightPx).toBeGreaterThanOrEqual(Math.round(RANGE.minMm * GEOMETRY.dotsPerMm))
    expect(plan.heightPx).toBeLessThanOrEqual(Math.round(RANGE.maxMm * GEOMETRY.dotsPerMm))
    expect(texts(shipLabelSpec(SHIP))).toContain('发货联')
    expect(plan.warnings).toEqual([])
  })
})

describe('L4 下单日期按业务时区取日', () => {
  it('16:30Z ⇒ 上海次日；带 +08:00 偏移 ⇒ 当日；坏值 ⇒ —', () => {
    expect(shipLabelDateText('2026-09-01T16:30:00Z')).toBe('2026-09-02')
    expect(shipLabelDateText('2026-09-01T00:00:00+08:00')).toBe('2026-09-01')
    expect(shipLabelDateText('2026-09-01T15:59:59Z')).toBe('2026-09-01')
    expect(shipLabelDateText('')).toBe(ROWS_LABEL_MISSING)
    expect(shipLabelDateText('not-a-date')).toBe(ROWS_LABEL_MISSING)
  })
})

describe('L5 渲染与预览同一份计划；取不到位图 ⇒ 抛错', () => {
  function fakeCanvas(withPixels: boolean): any {
    const ctx = {
      fillStyle: '',
      font: '',
      textBaseline: '',
      fillRect: () => undefined,
      fillText: () => undefined,
      ...(withPixels
        ? {
            getImageData: (x: number, y: number, width: number, height: number) => ({
              data: new Uint8ClampedArray(width * height * 4),
              width,
              height,
            }),
          }
        : {}),
    }
    return { width: 0, height: 0, getContext: () => ctx }
  }

  it('位图尺寸 = 计划尺寸（1:1，不缩放）', () => {
    const spec = finishedInboundSpec(FINISHED)
    const plan = layoutRowsLabel(spec)
    const rendered = renderRowsLabel(spec, (width, height) => fakeCanvas(true))
    expect(rendered.widthPx).toBe(plan.widthPx)
    expect(rendered.heightPx).toBe(plan.heightPx)
    expect(rendered.image.width).toBe(plan.widthPx)
    expect(rendered.image.height).toBe(plan.heightPx)
  })

  it('画布取不到位图 ⇒ 抛错（不静默打印白图）', () => {
    expect(() => renderRowsLabel(finishedInboundSpec(FINISHED), () => fakeCanvas(false))).toThrow(
      /取不到位图/,
    )
  })
})

describe('L6 多行字段：显式换行 + 宽度折行', () => {
  it('安装位置/备注里的换行各自成行（不是粘成一行）', () => {
    const plan = layoutRowsLabel(shipLabelSpec(SHIP))
    const all = plan.ops.filter((op) => op.kind === 'text').map((op) => (op as { text: string }).text)
    expect(all).toContain('客厅')
    expect(all).toContain('主卧')
    expect(all.some((text) => text.includes('客厅主卧'))).toBe(false)
  })
})
