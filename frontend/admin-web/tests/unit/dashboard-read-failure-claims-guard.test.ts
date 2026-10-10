// case_ids: DA-005, DA-006, UI-003
/**
 * 类级元守卫（issue #6715）：**读面失败时的「事实性断言」不得与失败面同屏**。
 *
 * ## 病灶（独立盲复核在 main `2adad8660` 上的实测）
 *
 * **登录前**就注入 dashboard 全部读面接口 ⇒ 500（全程**无一次成功加载**）⇒ 等 6s 读屏：
 *
 * - **N1 仍印「共 0 单」**：订单状态分布那行 `共 {total} 单` 的 `total = data.reduce(…)`，
 *   而 `data` 只是 `useState([])` 的初值 ⇒ **读不到**被印成「共 0 单」（健康基线是「共 308 单」）；
 * - **N2 失败横幅承诺了做不到的事**：横幅写「下方显示的仍是上次成功取到的值（**不是 0，
 *   也不是「暂无数据」**）」，而同屏事实 = 四卡 `—` ＋ **5 处「暂无…」** ＋ N1 的「共 0 单」
 *   ⇒ 它否认的两种误读**同时都在屏上**。它是为「有过上次成功值」写的，冷启动时是**假话**。
 *
 * 病根是**一句没人守的承诺**：文案写在屏上，而没有判据守着它。
 *
 * ## 判据与单一源
 *
 * 判据（`claimSites`）、豁免台账（`LEDGER`）、**在场门台账**（`PINNED_GATE_LINES`）与正向核
 * （`POSITIVE_ANCHORS`）都在
 * **`frontend/admin-web/scripts/dashboard-read-failure-claims-scan.mjs`**
 * （命令行 `node scripts/dashboard-read-failure-claims-scan.mjs` 与本测试**共用**它，不写第二份规则）。
 *
 * | 判据 | 判什么 | 会怎么红 |
 * |---|---|---|
 * | 1 | **判据面不得缩水**：`SCOPE` 必须含 `dashboard/page.tsx` 与 `components/dashboard/**` | 文件被改名 / 移出 ⇒ 红（否则本判据在空气上「全绿」） |
 * | 2 | **未门即红**：`共 … 单` 计数断言 / `暂无…` 空态断言必须带**在场门**，或登记进 `LEDGER` / `PINNED_GATE_LINES` | 新写一行 `共 {n} 单` / 一句「暂无…」⇒ 具名报出 |
 * | 3 | **两个台账只许缩短**：不再命中的条目当场红（僵尸豁免 / 僵尸钉住） | 修好不删条目 ⇒ 红 |
 * | 4 | **钉住条目的三重理由必须成立**：`claim`（该点逐字）· `gate`（门外那句逐字）· `runtime`（运行时出口锚）三条都必须在文件里**逐字**找到 | 摘门 / 删出口 / 改文案 ⇒ 红（这是「承诺要有判据守着」的机械面） |
 * | 5 | **覆盖非空**：至少 1 条计数断言 + 多条空态断言 + 至少 1 条**行内已门** | 判据面退化成空集自绿 ⇒ 红 |
 * | 6 | **判别力自证**：坏形态在内存源码里各自判红；**#6701 的形态**（`?? 0`）**必须不报** | 守卫退化成绿 / 两把尺子互相判僵尸 ⇒ 红 |
 *
 * ## 与 #6701 `derived-zero-fallback-scan.mjs` 的边界（谁管哪些形态）
 *
 * | 面 | 扫描器 | 判什么 |
 * |---|---|---|
 * | #6701 | `frontend/admin-web/scripts/derived-zero-fallback-scan.mjs` | **金额 / 数量派生展示位的零值字面量回退**（AST 判据） |
 * | **本单 #6715** | `frontend/admin-web/scripts/dashboard-read-failure-claims-scan.mjs` | **读失败的「事实性断言」上屏**：「共 N 单」计数断言 与 「暂无…」空态断言（文本判据） |
 *
 * **互不判僵尸的机械理由**：本判据的候选必须含「共 … 单」或「暂无…」文案，零值回退字面量
 * 一个都不含 ⇒ 命中集**在形态上不相交**（判据 6 的 ④/⑤ 把这条钉成断言）。
 *
 * ## 局限（照实登记，§19.1）
 *
 * - **只扫工作台文件族**；别的文件族（`/stock-ledger` #6707、`/chat` `/employees` `/notifications`
 *   `/products` `/shipments` `/production/remnants` #6713/#6714）**不在本台账内**，不冒充已覆盖；
 * - **在场门是「行内 + 上一非空行」**：跨 4~5 行的 JSX 三元（本仓常态）判不出来 ⇒ 那些点必须进
 *   `PINNED_GATE_LINES`（判据 4 逐条核三重理由）；**放宽窗口会假绿**（证明不了「中间没有别的分支」）；
 * - 门是**词表**判定：判不了「这个布尔位真的由读成功算出」—— 那半边由**实例判据**承担
 *   （`tests/unit/pages/dashboard.test.tsx` 的 #6715 用例）；
 * - 经中间变量传递的文案（`const t = failed ? '—' : '暂无…'`）判不出来；
 * - **横幅那句承诺本身**不在扫描器射程（它是一句话、不是断言上屏）⇒ 由判据 4 的 `gate`/`runtime`
 *   锚与 `POSITIVE_ANCHORS`（逐字「没有取到数据」）＋ 实例判据守着。
 */
import { describe, it, expect } from 'vitest'
import {
  LEDGER,
  PINNED_GATE_LINES,
  POSITIVE_ANCHORS,
  SCOPE,
  claimSites,
  claimSitesFromSource,
  scopeFiles,
} from '../../scripts/dashboard-read-failure-claims-scan.mjs'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

const ROOT = process.cwd()

/** 判据点（`scripts/*.mjs` 是 JS ⇒ 这里给测试侧一个结构类型，免得 `object` 上取属性报 TS2339） */
interface ClaimSite { file: string; line: number; claim: string; gated: boolean; key: string }

/** 在内存里造一段源码跑判据（自证用）—— 不在测试里抄第二份正则。 */
const probe = (source: string) => {
  const r = claimSitesFromSource(source, { file: 'probe.tsx' }) as { counts: ClaimSite[]; empties: ClaimSite[] }
  return { counts: r.counts.map((s) => s.claim), empties: r.empties.map((s) => s.claim) }
}
/** 未门命中（= 会判红的那一类） */
const ungatedOf = (source: string) => {
  const r = claimSitesFromSource(source, { file: 'probe.tsx' }) as { counts: ClaimSite[]; empties: ClaimSite[] }
  return [...r.counts, ...r.empties].filter((s) => !s.gated).map((s) => s.key)
}
const read = (rel: string) => readFileSync(join(ROOT, rel), 'utf8')

describe('读失败不得与「0 / 暂无数据」式断言同屏（类级元守卫，issue #6715）', () => {
  const { files, counts, empties } = claimSites(ROOT) as { files: string[]; counts: ClaimSite[]; empties: ClaimSite[] }
  const all = [...counts, ...empties]
  const ungated = all.filter((s) => !s.gated)
  const pinnedKeys = new Set(PINNED_GATE_LINES.map((p) => p.key))

  it('判据面非空且**含工作台文件族**（判据面被改小 ⇒ 本判据在空气上全绿）', () => {
    expect(files.length, '工作台文件族应有一批文件').toBeGreaterThanOrEqual(5)
    for (const anchor of [
      'src/app/(dashboard)/dashboard/page.tsx',
      'src/components/dashboard/OrderStatusChart.tsx',
    ]) {
      expect(files, `${anchor} 必须在判据面内（SCOPE 被改动 / 文件被挪走都会在这里红）`).toContain(anchor)
    }
    expect(SCOPE.length).toBeGreaterThan(0)
    // scopeFiles 与 claimSites 必须同源（防「清单走一条路、扫描走另一条」）
    expect(scopeFiles(ROOT).length).toBe(files.length)
  })

  it('未门即红：计数断言 / 空态断言必须带在场门，或登记进任一台账（未登记即红）', () => {
    const offenders = ungated.filter((s) => !LEDGER.includes(s.key) && !pinnedKeys.has(s.key))
    expect(
      offenders,
      '「读不到」与「0 / 暂无数据」不得同屏：这一处断言必须有**在场门**'
        + '（`blockEnabled(…)` / `blockFailed(…)` / `<name> in blockErrors` / `!readFailed` / `\'—\'` / `EMPTY_VALUE`），'
        + '跨多行的 JSX 三元判不出行内门时，进 frontend/admin-web/scripts/dashboard-read-failure-claims-scan.mjs 的 PINNED_GATE_LINES'
        + '（并写清 gate / runtime 两条锚）。\n'
        + offenders.map((s) => `  · ${s.key}  (${s.file}:${s.line})`).join('\n'),
    ).toEqual([])
  })

  it('两个台账都只许缩短：不再命中的条目当场红（僵尸豁免 / 僵尸钉住）', () => {
    const live = new Set(all.map((s) => s.key))
    const stale = [
      ...LEDGER.filter((k) => !live.has(k)),
      ...PINNED_GATE_LINES.filter((p) => !live.has(p.key)).map((p) => p.key),
    ]
    expect(
      stale,
      '这些台账条目已经不再命中（多半是修好了）⇒ 必须同批删掉，不留僵尸：\n'
        + stale.map((k) => `  · ${k}`).join('\n'),
    ).toEqual([])
  })

  it('钉住条目的**三重理由**必须逐字成立（点 / 门 / 运行时出口任一被摘 ⇒ 红）', () => {
    expect(PINNED_GATE_LINES.length, '钉住条目本身不许被清空「消红」').toBeGreaterThanOrEqual(1)
    for (const p of PINNED_GATE_LINES) {
      const claimText = read(p.runtimeIn)
      expect(claimText, `${p.key}：声明的断言点逐字不存在（${p.claim}）`).toContain(p.claim)
      const gateText = read(p.gateIn || p.runtimeIn)
      expect(gateText, `${p.key}：声明的**门**逐字不存在（${p.gate}）—— 门被摘 / 被改写 ⇒ 这里红`).toContain(p.gate)
      // `runtime` 必须是**真的稳定锚**（`data-testid`），不是一句随手写的散文
      expect(claimText, `${p.key}：声明的运行时出口 ${JSON.stringify(p.runtime)} 不是该文件里的 \`data-testid\``)
        .toContain(`data-testid="${p.runtime}"`)
      expect(p.gateWhy.length, `${p.key}：必须写清「这算什么门」的理由`).toBeGreaterThan(5)
      expect(p.runtimeWhy.length, `${p.key}：必须写清「运行时谁来判」`).toBeGreaterThan(5)
    }
  })

  it('正向核：`POSITIVE_ANCHORS` 的逐字锚必须在它声称的文件里真的在（门被摘 ⇒ 红）', () => {
    for (const { file, must, why } of POSITIVE_ANCHORS) {
      const text = read(file)
      for (const m of must) {
        expect(text, `${file} 里必须有逐字锚 ${JSON.stringify(m)}（${why}）`).toContain(m)
      }
    }
  })

  it('覆盖非空：至少 1 条计数断言 + 多条空态断言 + 至少 1 条**行内已门**（不是空集自绿）', () => {
    expect(counts.length, '计数断言（共 N 单）应在判据面内').toBeGreaterThanOrEqual(1)
    expect(empties.length, '空态断言（暂无…）应在判据面内').toBeGreaterThanOrEqual(3)
    expect(all.filter((s) => s.gated).length, '必须有行内判得出来的门（否则判据只在钉住表上运转）').toBeGreaterThanOrEqual(1)
  })

  it('判别力自证：坏形态在内存源码里**各自判红**（计数断言 / 空态断言 / 跨行门 / 注释不算证据）', () => {
    // ① N1 的逐字形态：读派生的 `共 {total} 单` 无门 ⇒ 红
    expect(ungatedOf('<span className="text-xs text-neutral-400">共 {total} 单</span>')).toEqual([
      'probe.tsx::count::<span className="text-xs text-neutral-400">共 {total} 单</span>',
    ])
    // ② 空态断言无门 ⇒ 红（N2 的 5 处「暂无…」即此形态）
    expect(ungatedOf('<p className="text-sm font-medium text-neutral-500">暂无订单数据</p>')).toEqual([
      'probe.tsx::empty::暂无订单数据',
    ])
    // ③ `!readFailed &&`（本包 OrderStatusChart 形态）⇒ 门
    expect(ungatedOf('{!readFailed && <span data-testid="order-status-count">共 {total} 单</span>}')).toEqual([])
    // ④ 五块收口用的 `blockEnabled(...)` 门 ⇒ 不红
    expect(ungatedOf("{blockEnabled('orderStatus') && <span>共 {total} 单</span>}")).toEqual([])
    // ⑤ 仓内既有的 `blockErrors` 门 ⇒ 不红
    expect(ungatedOf("{!('orders' in blockErrors) && <div>暂无近期订单</div>}")).toEqual([])
    // ⑥ 门在**上一非空行**（JSX 跨行）⇒ 不红
    expect(ungatedOf("{!readFailed && (\n  <p>暂无订单数据</p>\n)}")).toEqual([])
    // ⑦ 注释里的同形态不算证据（本仓注释惯例会引用这些串）
    expect(ungatedOf('// 改前这里是「共 0 单」与「暂无订单数据」，见 issue #6715')).toEqual([])
    // ⑧ **隔了一行**的门只认「上一非空行」⇒ 不再往上找（这是**有意**的窄口径：
    //    「隔着 N 行」证明不了中间没有别的分支 ⇒ 那种点必须进 PINNED_GATE_LINES 并写清理由）
    expect(ungatedOf("{!readFailed && (\n  )\n  <p>暂无订单数据</p>")).toEqual(['probe.tsx::empty::暂无订单数据'])
    // ⑨ 注释行**不能**把门「接」到注释里的串上（注释整行被抹空 ⇒ 注释里的串不是证据）
    expect(ungatedOf("// 上文引用过 !readFailed && 的门\n// 这里再引用一次「暂无订单数据」")).toEqual([])
    // ⑨ 属性形态的空态文案同样要门（`emptyText="暂无近期订单"`）
    expect(ungatedOf('<RecentOrders orders={recentOrders} emptyText="暂无近期订单" />')).toEqual([
      'probe.tsx::empty::暂无近期订单',
    ])
    expect(ungatedOf("{!readFailed && (\n  <RecentOrders orders={recentOrders} emptyText=\"暂无近期订单\" />\n)}")).toEqual([])
  })

  it('判别力自证（反向对照）：**#6701 的形态**与无关文案都**不**报（两份台账不互判僵尸）', () => {
    // ①② #6701 的形态：派生展示位的零值回退 —— 本判据**必须不报**（那是另一把尺子）
    expect(probe('<BizStatCard value={metricText(s.todaySales ?? 0, fmtCurrency)} />')).toEqual({ counts: [], empties: [] })
    expect(probe("<X value={stats?.todayOrders?.toLocaleString() || '0'} />")).toEqual({ counts: [], empties: [] })
    expect(probe('const v = stats?.monthRevenue ?? 0')).toEqual({ counts: [], empties: [] })
    // ③ 无关文案：页头 / 区块标题 / 无断言的普通数字
    expect(probe('<h1 className="text-xl font-semibold text-neutral-900">经营看板</h1>')).toEqual({ counts: [], empties: [] })
    expect(probe('const todaySalesState = 0')).toEqual({ counts: [], empties: [] })
  })
})
