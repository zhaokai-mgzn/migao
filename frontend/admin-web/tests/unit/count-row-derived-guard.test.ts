// case_ids: UI-057, UI-058
/**
 * 类级元守卫（issue #6703）：**计数行不得从一个可能失败的读派生数字**。
 *
 * ## 病灶
 *
 * 后端整体不可用（注入 `/api/admin/**` → 500）时，失败**只由瞬时 toast 宣告**（≈4s 消失），
 * 而持久面上仍留着事实性断言：「**共 0 条**」/ Pagination 的「**共 0 条记录**」。
 * `total` 的初值是 0，读失败时**没人**标记它不可信 ⇒ 商家读成「今天没有订单」。
 * 与 #6691「读面故障不得画成空态」同族；本判据把 #6691 那条标准**类级化到计数行**。
 *
 * ## 判据与单一源
 *
 * 判据（`countRowSites`）与台账（`LEDGER` / `FAILURE_ANCHORS`）都在
 * **`frontend/admin-web/scripts/count-row-derived-scan.mjs`**（命令行
 * `node scripts/count-row-derived-scan.mjs` 与本测试**共用**它，不写第二份规则）。四条：
 *
 * 1. **扫描判据**：凡「文件里印了 `共 … 条`（或用了共享 `Pagination`）**且**这个数来自
 *    `setXxxTotal`（= 一个可能失败的读）」⇒ 必须满足：本文件带**列表读面失败锚**
 *    （`*-load-error` / `*-load-failed` / `*-load-retry` 的 testid，或 `totalReliable`），
 *    或**登记进 `LEDGER`** ⇒ **未登记即红**；
 * 2. **正向核**（`FAILURE_ANCHORS`）：本包已改对的页面必须**逐字**含失败态锚点
 *    ⇒ 锚点被删（页面退回「读失败 = 印 0」）当场红；
 * 3. **台账只许缩短**：`LEDGER` 里不再命中的条目当场红（逼着删干净，不留僵尸豁免）；
 * 4. **判别力自证**：六种坏形态在内存里各自判红、好形态不红、只改注释不红
 *    ⇒ 守卫自己退化成绿时先在这里红。
 *
 * ## 边界（照实登记，§19.1）
 *
 * - 只扫**源码文本形态**，判不了「失败面渲染得够不够显眼」（那是 §15.7 读图的面）；
 * - 「调用方有没有把 `totalReliable={...}` 传下去」**判不了**（要类型 / 运行时才知道）——
 *   漏判那一半由**实例判据** `frontend/admin-web/tests/unit/pages/list-count-failure-instances.test.tsx`
 *   兜底（注入读失败 ⇒ 屏上零「共 0 条」）；
 * - **有意不判**「屏上印的是服务端返回的**行数**（`rows.length`）」——那是读数本身，不是
 *   另一个读派生出来的断言（列表现状由 #6691 覆盖）；
 * - **与在飞包的扫描面边界**：#6701 = 工作台**金额面**（`scripts/derived-zero-fallback-scan.mjs`）；
 *   #6702 = 余料页（`/production/remnants`）的读失败文案 / 计数（另建）；**本判据** = 列表页
 *   计数行 + 共享 `Pagination`。三面各扫各的、不互判；
 * - 集成侧的同族普查（A 涉钱展示位 4 / B 图怰 3 / C 分页计数 8 / D 正例 1）记在 **#6701** 的评论里 ——
 *   本文件**不重复**那份清单，也**不**据它判红。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import {
  LEDGER,
  FAILURE_ANCHORS,
  SCOPES,
  countRowSites,
  countRowSitesFromSource,
  offendersOf,
  staleLedger,
} from '../../scripts/count-row-derived-scan.mjs'

const ROOT = process.cwd()

/** 内存变异：把一段源码当**真语料**喂给**生产判据**（不落盘、不抄第二份正则） */
const hits = (source: string) => countRowSitesFromSource(source, { file: 'probe.tsx' })
const n = (source: string) => hits(source).filter((s) => !s.guarded).length

describe('计数行不得从一个可能失败的读派生数字（类级元守卫，issue #6703）', () => {
  const { files, sites } = countRowSites(ROOT)

  it('普查面非空（扫不到文件 ⇒ 本判据在扫空气，而不是"没问题"）', () => {
    expect(files.length, `${SCOPES.join(' + ')} 下应有一批页面 / 组件`).toBeGreaterThanOrEqual(100)
    // 病灶页必须在扫描面里（否则改了目录名就会「静默全绿」）
    for (const anchor of [
      'src/app/(dashboard)/orders/page.tsx',
      'src/app/(dashboard)/finance/page.tsx',
      'src/app/(dashboard)/customers/page.tsx',
      'src/app/(dashboard)/after-sales/page.tsx',
      'src/app/(dashboard)/knowledge/page.tsx',
      'src/app/(dashboard)/stock-ledger/page.tsx',
      'src/components/ui/Pagination.tsx',
    ]) {
      expect(files, `扫描面必须含 ${anchor}`).toContain(anchor)
    }
  })

  it('本包六页**都**带着列表读面失败锚（实例判据的类级面）', () => {
    for (const page of [
      'src/app/(dashboard)/orders/page.tsx',
      'src/app/(dashboard)/finance/page.tsx',
      'src/app/(dashboard)/customers/page.tsx',
      'src/app/(dashboard)/after-sales/page.tsx',
      'src/app/(dashboard)/knowledge/page.tsx',
      'src/app/(dashboard)/stock-ledger/page.tsx',
    ]) {
      const hit = sites.filter((s) => s.file === page)
      expect(hit, `${page} 不在计数行扫描面内 ⇒ 本判据判不到它`).not.toEqual([])
      expect(
        hit.map((s) => `${s.key} [${s.prints.join('/')}] guarded=${s.guarded}`),
        `${page} 的计数行由可能失败的读派生，却没有列表读面失败锚 `
          + '（`*-load-error` 的 testid，或共享 Pagination 的 `totalReliable`）—— '
          + '读失败时它会把「读不到」印成「共 0 条」。\n'
          + '出口：照抄 `src/app/(dashboard)/orders/page.tsx` 的形态 —— catch 里 `setLoadError(true)`；'
          + '计数行改由失败标记门控（印 `—`）；渲染共享 `components/common/ListLoadError`（带真重发出口）。',
      ).toEqual(hit.filter((s) => s.guarded).map((s) => `${s.key} [${s.prints.join('/')}] guarded=true`))
    }
  })

  it('未登记即红：命中点必须「有失败锚」或逐条登记进 LEDGER（存量债）', () => {
    const { offenders } = offendersOf(ROOT)
    expect(
      offenders.map((o) => `${o.key} [${o.prints.join('/')}] total=${o.totals.join(',')}`),
      '这些文件的计数行由可能失败的读派生、且没有列表读面失败锚 —— '
        + '要么修（首选，照 `src/app/(dashboard)/orders/page.tsx`），'
        + '要么在 `frontend/admin-web/scripts/count-row-derived-scan.mjs` 的 LEDGER 里'
        + '**具名登记**（存量债，只许缩短）：\n'
        + offenders.map((o) => `  ${o.key}`).join('\n'),
    ).toEqual([])
  })

  it('正向核：已改对的页面必须**逐字**含失败态锚点（删了锚点 ⇒ 当场红）', () => {
    expect(FAILURE_ANCHORS.length, '正向核台账不许被删空').toBeGreaterThanOrEqual(8)
    for (const entry of FAILURE_ANCHORS) {
      const source = readFileSync(join(ROOT, entry.file), 'utf-8')
      for (const anchor of entry.anchors) {
        expect(
          source.includes(anchor),
          `${entry.file} 缺失败态锚点「${anchor}」（${entry.name}）—— `
            + '页面退回「读失败 = 计数行印 0」了。失败态必须自己渲染出来：'
            + '`data-testid` + 可行动文案 + 重试出口（照抄 `src/app/(dashboard)/orders/page.tsx`）。',
        ).toBe(true)
      }
    }
  })

  it('台账只许缩短：不再命中 / 已改对的条目当场红（逼着删干净）', () => {
    const stale = staleLedger(ROOT)
    expect(
      stale,
      'LEDGER 里这些条目**已不再需要**（对应页面已带失败锚或已删）—— 台账只许缩短，请删掉这几条：\n'
        + stale.join('\n'),
    ).toEqual([])
  })

  it('台账非空且**逐条兑现**（不许被删空消红；当前读数 = 3 条同族存量债）', () => {
    // 🔴 防「有人把台账清空来消红」：这条钉住当前**取数**（LEDGER 的条目必须真的还在命中）。
    // 条目归零的正确路径 = 把那三页也修掉（同批删条目），**不是**删台账。
    expect(LEDGER.length, 'LEDGER 被清空 = 用删台账代替修码；正确路径见扫描脚本注释').toBeGreaterThanOrEqual(3)
    const live = new Set(sites.filter((s) => !s.guarded).map((s) => s.key))
    for (const key of LEDGER) {
      expect(live.has(key), `LEDGER 条目「${key}」在扫描面里已不命中 ⇒ 必须同批删掉`).toBe(true)
    }
  })

  it('判别力自证：坏形态判红、好形态不红（守卫退化成绿 ⇒ 这里先红）', () => {
    const BAD = [
      // ① 病灶原形（/orders 改前）：`total` 初值 0 + 读失败只 toast + 尾行照旧印 total
      `export default function P() {
         const [total, setTotal] = useState(0)
         const [rows, setRows] = useState([])
         const load = async () => { try { const r = await api(); setTotal(r.total) } catch { toast.error('加载失败') } }
         return <><Table dataSource={rows} /><span>共 {total} 条</span></>
       }`,
      // ② 共享 Pagination 形态（/customers 改前）：分了页、total 照旧来自读
      `export default function P() {
         const [total, setTotal] = useState(0)
         const load = async () => { try { setTotal((await api()).total) } catch { toast.error('失败') } }
         return <Pagination current={1} pageSize={20} total={total} onChange={() => {}} />
       }`,
      // ③ `setXxxTotal` 形态（/finance 改前）：前缀不影响判定
      `export default function P() {
         const [txnTotal, setTxnTotal] = useState(0)
         const load = async () => { try { setTxnTotal((await api()).total) } catch { toast.error('失败') } }
         return <Pagination current={1} pageSize={20} total={txnTotal} onChange={() => {}} />
       }`,
      // ④ 「有失败**文案**、但锚点不是列表读面的那个」⇒ 仍判红（employees 的真实形态：
      //    岗位下拉有自己的 error，员工列表的计数行依旧没人管）
      `export default function P() {
         const [total, setTotal] = useState(0)
         const [positionError, setPositionError] = useState('')
         const load = async () => { try { setTotal((await api()).total) } catch { toast.error('失败') } }
         return <><span data-testid="employees-positions-error">{positionError}</span>
           <Pagination current={1} pageSize={20} total={total} onChange={() => {}} /></>
       }`,
    ]
    for (const source of BAD) {
      expect(n(source), `坏形态应判红：\n${source}`).toBeGreaterThan(0)
    }

    const GOOD = [
      // ① 正确范式（/orders 改后）：失败标记 + 计数行印 `—`
      `export default function P() {
         const [total, setTotal] = useState(0)
         const [loadError, setLoadError] = useState(false)
         const load = async () => { try { setTotal((await api()).total); setLoadError(false) } catch { setLoadError(true) } }
         return <div><div data-testid="orders-load-error" role="alert" /><span>共 {loadError ? '—' : total} 条</span></div>
       }`,
      // ② 共享 Pagination + `totalReliable`
      `export default function P() {
         const [total, setTotal] = useState(0)
         const [loadError, setLoadError] = useState(false)
         return <Pagination current={1} pageSize={20} total={total} totalReliable={!loadError} onChange={() => {}} />
       }`,
      // ③ 计数行印的是**行数**（读数本身，不是另一个读派生）⇒ 不判
      `export default function P() {
         const [rows, setRows] = useState([])
         return <span>共 {rows.length} 条</span>
       }`,
      // ④ 本地数组长度（`共 N 行` / `共 N 套`）⇒ 不判（没有读面 total）
      `export default function P() {
         const [lines, setLines] = useState([])
         return <span>共 {lines.length} 行（一行 = 一个批次）</span>
       }`,
      // ⑤ 与「共 N 条」无关的页面 ⇒ 不判
      `export default function P() { return <div>设置</div> }`,
    ]
    for (const source of GOOD) {
      expect(n(source), `好形态不该判红：\n${source}`).toBe(0)
    }
  })

  it('只改注释不红（对照读数：守卫不得被自己的说明文案喂红）', () => {
    // 🔴 实测教训：`finance/page.tsx` 的说明注释里就写着「共 0 条记录」这个串 ——
    // 不做注释剔除，这条注释会把它判成「计数行」并假红。
    const commented = `// 读失败时若照旧印「共 0 条记录」，商家会读成「今天没进账」（这段说明本身不该判红）
      /* 另一处示例：共 0 条也是 —— 块注释里的示例不是真形态 */
      const x = 1`
    expect(n(commented)).toBe(0)
  })
})
