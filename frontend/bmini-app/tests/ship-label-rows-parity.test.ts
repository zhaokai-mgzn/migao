// case_ids: BM-061
/**
 * 发货联行清单的**跨端等价**判据（issue #8287）。
 *
 * ## 为什么这条必须「现取两侧实现」而不是各自快照
 *
 * 这张纸的同一份行清单现在有两个消费方：`/w/`（`frontend/worker-h5/src/shipment.mjs`）与
 * bmini（`frontend/bmini-app/src/utils/labels/shipLabel.ts`）。两份**各自绿**没有意义 ——
 * 任一侧改了行序 / 缺值规则 / 日期口径，纸面就会在「手机打出来的」和「终端打出来的」之间分叉。
 * ⇒ 本判据把 `/w/` 的实现**真的跑起来**（`node --input-type=module` 导入同一文件），
 * 对同一组 fixture 逐行比对；任一侧漂移 ⇒ 逐字段点名红。
 *
 * ## 红证（每条都能单独变红）
 *
 * | # | 判据 | 红证 |
 * |---|---|---|
 * | P1 | 12 行齐全（含帘种 / 安装小区 / 安装位置），行序与 `/w/` 逐行相等 | 删任一行 / 调换两行 ⇒ 红 |
 * | P2 | 可选附注缺值 ⇒ **整行不印**（两侧一致） | 把 remark 改成必印 ⇒ 红 |
 * | P3 | 缺值 = `—`（两侧一致，不补 0 / 空串） | 改一侧为 '' ⇒ 红 |
 * | P4 | 下单日期按 Asia/Shanghai（`16:30Z` ⇒ 次日，两侧一致） | 任一侧改成本地时区 ⇒ 红 |
 * | P5 | fixture 真的进入了 `/w/` 的实现（不是空跑）—— 正向取到的行数 > 0 且含单号 | 换一个不存在的导出 ⇒ 抛错红 |
 */
import { execFileSync } from 'child_process'
import path from 'path'
import { pathToFileURL } from 'url'
import {
  buildShipLabelRows,
  type ReadyShipmentOrderLike,
} from '../src/utils/labels/shipLabel'

const SHIPMENT_MJS = path.resolve(__dirname, '../../../frontend/worker-h5/src/shipment.mjs')
const SHIPMENT_URL = pathToFileURL(SHIPMENT_MJS).href

/** 真的把 `/w/` 的实现跑起来（零依赖 `.mjs`，node 直接 import）。 */
function h5Rows(order: ReadyShipmentOrderLike): unknown[] {
  const script = [
    "import(process.env.SHIPMENT_URL)",
    '  .then((m) => {',
    '    if (typeof m.buildShipLabelRows !== "function") {',
    '      throw new Error("shipment.mjs 没有 buildShipLabelRows（导出面变了？）");',
    '    }',
    '    process.stdout.write(JSON.stringify(m.buildShipLabelRows(JSON.parse(process.env.SHIPMENT_FIXTURE))));',
    '  })',
    '  .catch((error) => { console.error(error); process.exit(1); });',
  ].join('\n')
  const out = execFileSync(process.execPath, ['--input-type=module', '-e', script], {
    env: {
      ...process.env,
      SHIPMENT_URL,
      SHIPMENT_FIXTURE: JSON.stringify(order),
    },
    encoding: 'utf8',
  })
  return JSON.parse(out)
}

/** 全字段（与生产列表行的形状一致）。 */
const FULL: ReadyShipmentOrderLike = {
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

const FIXTURES: Array<{ name: string; order: ReadyShipmentOrderLike }> = [
  { name: '全字段', order: FULL },
  { name: '最小行（只有单号）', order: { order_no: 'SO-2' } },
  {
    name: '可选附注全缺 / 全空白',
    order: {
      ...FULL,
      curtain_types: '',
      install_community: '   ',
      install_rooms: null,
      remark: '',
    },
  },
  {
    name: '日期时区边界（16:30Z）',
    order: { ...FULL, created_at: '2026-09-01T16:30:00Z' },
  },
  {
    name: '缺值（收货信息 / 物流公司）',
    order: {
      ...FULL,
      customer_name: '',
      customer_phone: null,
      customer_address: '   ',
      logistics_type_label: null,
      logistics_company: null,
    },
  },
]

describe('发货联行清单：bmini 与 /w/ 逐行等价（issue #8287）', () => {
  it('P5 正向：/w/ 的实现真的被跑起来（不是空跑）', () => {
    const rows = h5Rows(FULL) as Array<{ key: string; value: string }>
    expect(rows.length).toBeGreaterThanOrEqual(10)
    expect(rows.find((row) => row.key === 'order_no')?.value).toBe(FULL.order_no)
  })

  it('P1/P2/P3/P4 每一组 fixture 逐行相等（行序 / 缺值 / 可选行 / 时区）', () => {
    const mismatches: string[] = []
    for (const fixture of FIXTURES) {
      const ours = buildShipLabelRows(fixture.order)
      const theirs = h5Rows(fixture.order)
      if (JSON.stringify(ours) !== JSON.stringify(theirs)) {
        mismatches.push(
          `${fixture.name}:\n  bmini = ${JSON.stringify(ours)}\n  /w/   = ${JSON.stringify(theirs)}`,
        )
      }
      // 反向钉住：可选附注全空 ⇒ 那三行 + 备注**都不在**（不是印「—」白吃版心）
      if (fixture.name === '可选附注全缺 / 全空白') {
        const labels = ours.map((row) => row.label)
        for (const optional of ['帘种', '安装小区', '安装位置', '备注']) {
          expect(labels).not.toContain(optional)
        }
      }
    }
    expect(mismatches).toEqual([])
  })
})
