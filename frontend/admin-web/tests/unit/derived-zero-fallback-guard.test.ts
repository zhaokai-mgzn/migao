// case_ids: DA-005, DA-006, UI-003
/**
 * 类级元守卫（issue #6701）：**读派生的展示位不得 `?? 0` / `|| 0`**（金额 / 数量 / 计数）。
 *
 * ## 病灶（商家电脑端 `/dashboard` 集成侧实测）
 *
 * 经营数据读面失败时，屏上**同时**有失败面（`dashboard-load-failed` + 重试）**和** `¥0`
 * —— 「今日暂无新订单，销售额 ¥0」＋「本月销售额 ¥0」，共 3 处 `¥0`。
 * 根因 = 展示位把**没读到**折成**真 0**（`stats?.todaySales ?? 0` 一族），
 * 于是「今天销售额 ¥0」被读成「今天没卖出去」⇒ **错误经营判断**（涉钱 + 商家第一屏），
 * 并**派生**假读数（客单价 = 0 ÷ 0）。
 * 与 #6691（读面故障不得画成空态）同族，但射程不同：那条管**列表 / 状态**，本条管**金额与计数**。
 *
 * ## 判据与单一源
 *
 * 判据（`derivedZeroSites`）与台账（`LEDGER`）都在
 * **`frontend/admin-web/scripts/derived-zero-fallback-scan.mjs`**（命令行
 * `node scripts/derived-zero-fallback-scan.mjs` 与本测试**共用**它，不写第二份规则）。四条：
 *
 * 1. **未登记即红**：命中「`?? 0` / `|| 0` 直接落在展示位」⇒ 必须登记进 `LEDGER`；
 * 2. **台账只许缩短**：`LEDGER` 里**不再命中**的条目当场红（修好必须同批删干净，不留僵尸豁免）；
 * 3. **判据面不得缩水**：判据面必须含 `dashboard/page.tsx` 与 `components/dashboard/**`
 *    —— 文件被改名 / 移出 `SCOPE` ⇒ 红（否则本判据会在空气上「全绿」）；
 * 4. **判别力自证**：坏形态（金额位 `?? 0` / `|| 0`）在内存源码里各自判红，好形态
 *    （读不到 ⇒ `null` ⇒ `--`）**不**报 —— 守卫自己退化成绿 ⇒ 红。
 *
 * ## 局限（照实登记，§19.1）
 *
 * - 只扫**工作台文件族**（`SCOPE`）；**全仓同类存量不在本台账内**：实测另有 4 处别的文件族命中
 *   （`src/app/(dashboard)/finance/page.tsx` 的 `fmtMoney(value ?? 0)` 等，属别的写面，本单边界不动）；
 * - 只认**直接落位**的形态：经中间变量、`{...props}` 展开、跨行传递的 `?? 0` **判不出来**
 *   —— 那半边由**实例判据**承担（`tests/unit/pages/dashboard.test.tsx` 的 #6701 用例，
 *   断言「不出现 `¥0`」+「出现 `--`」+「重试后变回真实值」）；
 * - 只判**静态文本/AST 形态**，不判运行时行为；服务端下发文案里的假 0 不在射程。
 */
import { describe, it, expect } from 'vitest'
import {
  LEDGER,
  SCOPE,
  derivedZeroSites,
  derivedZeroSitesFromSource,
  scopeFiles,
} from '../../scripts/derived-zero-fallback-scan.mjs'

const ROOT = process.cwd()

/** 在内存里造一段源码跑判据（自证用）—— 不在测试里抄第二份正则。 */
const probe = (source: string) => derivedZeroSitesFromSource(source, { file: 'probe.tsx' }).map((s) => s.slot)

describe('读派生展示位不得 ?? 0 / || 0（类级元守卫，issue #6701）', () => {
  const { files, sites } = derivedZeroSites(ROOT)

  it('判据面非空且**含工作台文件族**（判据面被改小 ⇒ 本判据在空气上全绿）', () => {
    expect(files.length, '工作台文件族应有一批文件').toBeGreaterThanOrEqual(5)
    for (const anchor of [
      'src/app/(dashboard)/dashboard/page.tsx',
      'src/components/dashboard/TodayOverviewBar.tsx',
    ]) {
      expect(files, `${anchor} 必须在判据面内（SCOPE 被改动 / 文件被挪走都会在这里红）`).toContain(anchor)
    }
    // 台账锚不许悬空：每条登记的键必须能在**现取**文件集里找到同一文件前缀
    for (const key of LEDGER) {
      const file = String(key).split('::')[0]
      expect(files, `台账条目指向判据面外的文件：${key}`).toContain(file)
    }
    expect(SCOPE.length).toBeGreaterThan(0)
    // scopeFiles 与 derivedZeroSites 必须同源（防「清单走一条路、扫描走另一条」）
    expect(scopeFiles(ROOT).length).toBe(files.length)
  })

  it('未登记即红：命中点必须登记（台账只许缩短）', () => {
    const unregistered = sites.filter((s) => !LEDGER.includes(s.key))
    expect(
      unregistered,
      '读派生的展示位不得把「读不到」折成 0：改成「读不到 ⇒ --，真 0 仍显示 0」'
        + '（口径见 frontend/admin-web/src/components/dashboard/TodayOverviewBar.tsx 的 DASHBOARD_EMPTY_VALUE 一族的等价写法），'
        + '确属必要再登记进 frontend/admin-web/scripts/derived-zero-fallback-scan.mjs 的 LEDGER。\n'
        + unregistered.map((s) => `  · ${s.key}  (${s.file}:${s.line} @ ${s.within})`).join('\n'),
    ).toEqual([])
  })

  it('台账只许缩短：`LEDGER` 里不再命中的条目当场红（修好必须同批删）', () => {
    const stale = LEDGER.filter((key) => !sites.some((s) => s.key === key))
    expect(
      stale,
      '这些台账条目已经不再命中（多半是修好了）⇒ 必须同批删掉，不留僵尸豁免：\n'
        + stale.map((k) => `  · ${k}`).join('\n'),
    ).toEqual([])
  })

  it('本包目标形态：工作台文件族命中数 = 0（含 dashboard/page.tsx 的金额/计数展示位）', () => {
    expect(sites.map((s) => `${s.file}:${s.line} ${s.key}`)).toEqual([])
  })

  it('判别力自证：坏形态在内存源码里**各自判红**（金额 / 计数 / 格式化 / `|| 0` / 字符串 `0`）', () => {
    // ① 金额展示位（本单病灶原形）
    expect(probe('<BizStatCard value={fmtCurrency(stats?.todaySales ?? 0)} />')).toEqual(['fmtCurrency'])
    // ② 计数展示位
    expect(probe('<PendingCard count={stats?.pendingOrders ?? 0} />')).toEqual(['count'])
    // ③ 逻辑或（`||`）同样命中 —— 它是同一个病的另一种写法
    expect(probe('<BizStatCard value={fmtCurrency(stats?.monthRevenue || 0)} />')).toEqual(['fmtCurrency'])
    // ④ JSX 属性直挂（**透明节点穿透**：`?? 0` 的直接父节点是 JsxExpression，不是 JsxAttribute）
    expect(probe('<X value={a ?? 0} />')).toEqual(['value'])
    // ⑤ 字符串 `'0'`：屏上长得与 `?? 0` 一模一样（实测 `dashboard/page.tsx` 的 toLocaleString 站点）
    expect(probe("<X value={stats?.todayOrders?.toLocaleString() || '0'} />")).toEqual(['value'])
    // ⑥ 格式化调用实参（非展示名）
    expect(probe('const v = fmtYuan(row.amount ?? 0)')).toEqual(['fmtYuan'])
    // ⑦ 括号包裹
    expect(probe('<X value={(a ?? 0)} />')).toEqual(['value'])
    // ⑧ 对象属性展示位（非 JSX 路径）
    expect(probe('const p = { value: x ?? 0 }')).toEqual(['value'])
  })

  it('判别力自证（反向对照）：**正确形态**与**判据面外**的写法都**不**报', () => {
    // ① 正确形态：读不到 ⇒ null ⇒ 渲染 `--`（本包实现）
    expect(probe('<BizStatCard value={s ? fmtCurrency(s.todaySales) : EMPTY_VALUE} />')).toEqual([])
    // ② 真 0 的合法写法：值本身来自已判定「读到了」的对象
    expect(probe('<BizStatCard value={fmtCurrency(stats.todaySales)} />')).toEqual([])
    // ③ 判据面外：状态聚合 / 进度条宽度 / 量宽度（都不是「把坏值印成读数」）
    expect(probe('setLowStockCount(s.lowStockItems ?? 0)')).toEqual([])
    expect(probe('style={{ width: `${(r.salesQty || 0) / max * 100}%` }}')).toEqual([])
    expect(probe('const w = el.getBoundingClientRect().width || 0')).toEqual([])
    expect(probe('const n = Number(d.price ?? 0)')).toEqual([])
    expect(probe('const a = arr.map((d) => d.orders || 0)')).toEqual([])
    // ④ 成员访问：属性名是**对象自己的**字段名，不是展示位名
    expect(probe('const v = state.count ?? 0')).toEqual([])
    // ⑤ 非展示名的 JSX 属性（`label` 不是金额/计数/占比）
    expect(probe('<X label={x ?? 0} />')).toEqual([])
  })
})
