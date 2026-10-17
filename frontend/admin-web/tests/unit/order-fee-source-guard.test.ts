// case_ids: UI-020
// 类级元守卫（issue #7138）：**加工费只能从"权威落库值"读，不能从 processingInfo 快照里的客户端副本读**。
//
// 病灶（2026-10-17 用户报障，两张真机截图）：同一张单 `20261016434070014`
//   · 订单列表「采购明细」= `… + 加工费15元`
//   · 订单详情「费用构成」= `2699系列雪尼尔窗帘面料 未定价 · 锁边`，订单金额 = 商品合计
// 根因：同一行 `order_items.processing_info` 里两个键并存 ——
//   `processingFee`（**客户端副本**：下单页 / 探针脚本写进来，服务端既不校验也不覆盖）
//   `processingFeeDetail`（**权威值**：服务端取价落库，#4406）
// ⇒ 列表读副本、详情读权威 ⇒ 两个面自相矛盾。dev 实证：tenant 32 有 63 行带副本键，
//   63 行与权威值**全部不等**（副本恒 15 / 权威恒 0·unpriced）。
//
// 本判据做两件事：
//  ① **取值单一入口**：`lib/order-fee-display.ts::processingFeeOf` 的四种形态（权威命中 / 权威未定价 /
//     存量单无 detail 的兜底 / 非对象）逐条钉住 —— 既有"权威优先"，也不许把存量单一起打成 0；
//  ② **来源扫描**：`src/**` 里任何从**原始快照变量**（`pi` / `processingInfo` / `info` / `blob` / `snapshot`）
//     读 `.processingFee` 的地方，只允许 `lib/order-fee-display.ts` 一处。别处再拼一份 = 迟早与详情分叉。
//
// 边界（照实登记，别读成"全覆盖"）：
//   · 判据按**变量名启发式**认"原始快照"——静态判不了类型；`item.processingFee` 这类**已声明字段**
//     （详情 DTO / 试算响应行）本就该读，不受影响（下面有负控钉住这一点）；
//   · 它判的是"有没有第二处读快照副本"，判不了"读到的数在业务上对不对"（那是取价侧的事）；
//   · 服务端是否应覆盖/剥离快照里的副本键（涉钱口径）**不在本判据面内** —— 关联 issue #7138 的裁定项。
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'fs'
import { join, relative, sep } from 'path'
import { processingFeeOf } from '@/lib/order-fee-display'

const SRC_DIR = join(process.cwd(), 'src')

/** 唯一允许从**原始 processingInfo 快照**读加工费的实现点 */
const ALLOWED = ['src/lib/order-fee-display.ts']

/**
 * 原始快照的常见变量名（启发式）：`pi` / `processingInfo` / `info` / `blob` / `snapshot`。
 * ⚠️ 故意**不**把 `item` / `row` / `feeRow` 收进来：那些是**已声明字段**的载体（详情 DTO /
 * 试算响应行），读 `item.processingFee` 是契约内的读，收进来就是误红。
 */
const RAW_BLOB_READ = /(?:^|[^\w.$])(pi|processingInfo|info|blob|snapshot)\s*\??\.\s*processingFee\b/g

/** 命中一处即返回那一行（供台账 / 报错具名）；无命中 ⇒ `[]`（纯函数，内存可注入） */
export function findRawSnapshotFeeReads(source: string): string[] {
  const hits: string[] = []
  for (const line of source.split('\n')) {
    if (/^\s*(?:\/\/|\*|\/\*)/.test(line)) continue // 注释行不算读（文档要能引用这个键名）
    RAW_BLOB_READ.lastIndex = 0
    if (RAW_BLOB_READ.test(line)) hits.push(line.trim())
  }
  return hits
}

function walk(dir: string): string[] {
  const files: string[] = []
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) files.push(...walk(full))
    else if (/\.tsx?$/.test(name) && !name.endsWith('.d.ts')) files.push(full)
  }
  return files
}

const rel = (full: string) => relative(process.cwd(), full).split(sep).join('/')
const CORPUS = walk(SRC_DIR).map((full) => ({ path: rel(full), source: readFileSync(full, 'utf-8') }))

describe('加工费读面来源守卫（issue #7138）', () => {
  it('普查面非空且覆盖已知对象（扫描面漂了 ⇒ 先红，而不是静默空跑）', () => {
    expect(CORPUS.length, '扫不到 src 源码 ⇒ 判据在扫空气').toBeGreaterThanOrEqual(80)
    expect(
      CORPUS.some((f) => f.path === 'src/components/orders/OrderTable.tsx'),
      '订单列表组件不在扫描面内 ⇒ 坐标系已漂移',
    ).toBe(true)
    expect(
      CORPUS.some((f) => f.path === ALLOWED[0]),
      '唯一实现点不在扫描面内 ⇒ 判据在扫空气',
    ).toBe(true)
  })

  it('只有唯一实现点可以从原始快照读 processingFee（别处再读一份 ⇒ 红）', () => {
    const offenders = CORPUS.filter((f) => !ALLOWED.includes(f.path))
      .map((f) => ({ path: f.path, hits: findRawSnapshotFeeReads(f.source) }))
      .filter((x) => x.hits.length > 0)
    expect(
      offenders,
      '这些文件绕开 `processingFeeOf` 直接从 processingInfo 快照读加工费 —— 那是**客户端副本**，'
        + '与权威 `processingFeeDetail.amount` 可以是两个数（issue #7138 实证：列表 15 元 / 详情未定价）\n'
        + offenders.map((o) => `${o.path}: ${o.hits.join(' | ')}`).join('\n')
        + '\n\n出口：改用 `@/lib/order-fee-display` 的 `processingFeeOf(processingInfo)`；'
        + '若确属新的权威读面，先把它并进那一处，再在 ALLOWED 里登记（只许一处）。',
    ).toEqual([])
  })

  it('判别力自证：副本读被抓住、"已声明字段"读不误伤（内存注入，不落盘）', () => {
    // ① 从原始快照读 ⇒ 命中（这就是 #7138 的病根写法）
    expect(findRawSnapshotFeeReads('const fee = Number(pi.processingFee ?? 0)')).toHaveLength(1)
    expect(findRawSnapshotFeeReads('const fee = processingInfo.processingFee')).toHaveLength(1)
    expect(findRawSnapshotFeeReads('const fee = info?.processingFee')).toHaveLength(1)
    // ② 已声明字段（详情 DTO / 试算行）⇒ 不误伤
    expect(findRawSnapshotFeeReads('const fee = item.processingFee')).toEqual([])
    expect(findRawSnapshotFeeReads('const fee = feeRow.processingFee')).toEqual([])
    // ③ 唯一实现点里的兜底写法（`blob.processingFee`）本来就该被规则命中 —— 它靠 ALLOWED 放行，
    //    而不是靠"规则看不见"（否则实现点整个搬走也不会有东西变红）
    expect(findRawSnapshotFeeReads('const declared = nullableNumber(blob.processingFee)')).toHaveLength(1)
  })

  it('取值：权威 detail 优先，存量单（无 detail）才回落副本 / 明细求和', () => {
    // ① 权威未定价（amount 0）⇒ 0，即使副本写着 15（= 用户截图那一行）
    expect(
      processingFeeOf({
        processingFee: 15,
        processingItems: [{ id: 'pi-1', name: '锁边', quantity: 2 }],
        processingFeeDetail: { fee_source: 'unpriced', amount: 0, composition: '锁边' },
      }),
    ).toBe(0)
    // ② 权威命中 ⇒ 权威值，副本不采信
    expect(
      processingFeeOf({
        processingFee: 99,
        processingFeeDetail: { fee_source: 'matched', amount: 15, unit_price: 7.5, meters: 2 },
      }),
    ).toBe(15)
    // ③ 存量单（#4406 前生成、无 detail）⇒ #2916 兜底：顶层副本
    expect(processingFeeOf({ processingFee: 50 })).toBe(50)
    // ④ 存量单、副本缺席 ⇒ 加工项明细求和
    expect(processingFeeOf({ processingItems: [{ subtotal: 32 }] })).toBe(32)
    // ⑤ 非对象 / 缺席 ⇒ 0（不抛、不猜）
    expect(processingFeeOf(null)).toBe(0)
    expect(processingFeeOf(undefined)).toBe(0)
    expect(processingFeeOf('{"processingFee":15}')).toBe(0)
  })
})
