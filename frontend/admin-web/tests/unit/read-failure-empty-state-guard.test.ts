// case_ids: UI-057, UI-058
/**
 * 类级元守卫（issue #6663）：**读面失败不得伪装成空态**。
 *
 * ## 病灶（2026-10-10 三维审计，配置与权限面）
 *
 * 同一个病在三页各写了一遍：读接口失败时 catch **只把读数清空**——
 * `roles/page.tsx` 岗位清单读了失败 ⇒ 页面**像**「这个企业没有岗位」；
 * `employees/page.tsx` 岗位下拉读了失败 ⇒ 下拉空着、`Select` 又不能手输 ⇒ **建不出员工**，
 * 而页面没有任何一句话说「读不到」；`settings/page.tsx` 通知开关读了失败 ⇒
 * 开关**画成「关闭」**（`notificationEnabled` 保持 `false`）—— **谎报状态**：
 * 商家以为通知是关的，而真相是**读不到**。
 *
 * 这是本仓「状态必须真实（故障不得伪装成空态 / 成功态）」纪律的反面，
 * 也是 `dashboard/page.tsx`（issue #5792 ④）早就立好的范式：**失败态与空态可区分** ——
 * 空态说「暂无数据」，失败态说「加载失败 + 是哪几块 + 重试」。
 * 本判据把那个范式**类级化**：单个页面改一次不解决复发。
 *
 * ## 判据与单一源
 *
 * 判据（`swallowSites`）与台账（`LEDGER` / `FAILURE_ANCHORS`）都在
 * **`scripts/read-failure-empty-state-scan.mjs`**（命令行 `node scripts/read-failure-empty-state-scan.mjs`
 * 与本测试**共用**它，不写第二份规则）。三条：
 *
 * 1. **扫描判据**：凡「catch 清空读数且不表达失败」的形态 ⇒ 必须登记进 `LEDGER`，**未登记即红**；
 * 2. **正向核**（`FAILURE_ANCHORS`）：本包已改对的页面必须**逐字**含失败态锚点
 *    （`data-testid` + 可行动文案）⇒ 锚点被删（页面退回空态）当场红。
 *    ⚠️ 只有扫描判据会**假绿**：把 catch 改成 `setError('')` 也能「不再命中」——正向核堵住这条路。
 * 3. **台账只许缩短**：`LEDGER` 里不再命中的条目当场红（逼着删干净，不留僵尸豁免）。
 *
 * ## 边界（照实登记，§19.1）
 *
 * - 只扫**商家后台**（`src/app/(dashboard)`），只认**源码文本形态**；
 * - **有意不判**「空 catch + 注释『拦截器已提示』」的**写面** catch（过账 / 作废 / 提交）：
 *   `request.ts` 拦截器已 toast，且**读面读数不变** ⇒ 不产生假的空态；
 * - **有意不判**「清提示语 / 清过程量」的 setter（`setSearchHint('')` / `setLoading(false)` 一族，
 *   理由逐条写在扫描器的 `NOT_READING_STATE`）；
 * - 「服务端下发的 `message` 里带字段名」不在本条射程（那是展示字段分离，另单）。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import {
  LEDGER,
  FAILURE_ANCHORS,
  SCOPE,
  swallowSites,
  swallowSitesFromSource,
  findOffenders,
  staleLedger,
} from '../../scripts/read-failure-empty-state-scan.mjs'

const ROOT = process.cwd()

describe('读面失败不得伪装成空态（类级元守卫，issue #6663）', () => {
  const { files, sites } = swallowSites(ROOT)

  it('普查面非空（扫不到文件 ⇒ 本判据在扫空气，而不是"没问题"）', () => {
    expect(files.length, `${SCOPE} 下应有一批页面`).toBeGreaterThanOrEqual(30)
    // 三个病灶页必须在扫描面里（否则改了目录名就会「静默全绿」）
    for (const anchor of [
      'src/app/(dashboard)/roles/page.tsx',
      'src/app/(dashboard)/employees/page.tsx',
      'src/app/(dashboard)/settings/page.tsx',
    ]) {
      expect(files, `扫描面必须含 ${anchor}`).toContain(anchor)
    }
  })

  it('本包三页**不再命中**「清空读数且不表达失败」的 catch（实例判据的类级面）', () => {
    for (const page of [
      'src/app/(dashboard)/roles/page.tsx',
      'src/app/(dashboard)/employees/page.tsx',
      'src/app/(dashboard)/settings/page.tsx',
    ]) {
      const hit = sites.filter((s) => s.file === page)
      expect(
        hit.map((s) => `${s.key} (L${s.line} 清空 ${s.cleared.join('/')})`),
        `${page} 仍有「读失败只清空读数、不表达失败」的 catch —— 故障会伪装成空态。\n`
          + '出口：照抄 `src/app/(dashboard)/dashboard/page.tsx` 的失败/空态分离（issue #5792 ④）'
          + '—— 加一个失败态行（`data-testid` + 可行动文案 + 重试出口），别只清列表。',
      ).toEqual([])
    }
  })

  it('未登记即红：命中点必须逐条登记进 LEDGER（含本包文件族之外的存量债）', () => {
    const { offenders } = findOffenders(ROOT)
    expect(
      offenders.map((o) => o.key + `  (L${o.line} 清空 ${o.cleared.join('/')})`),
      '这些 catch 读失败只清空读数、且没有失败态 —— 要么修（首选，见 dashboard/page.tsx 范式），'
        + '要么在 scripts/read-failure-empty-state-scan.mjs 的 LEDGER 里**具名登记**（只许缩短）：\n'
        + offenders.map((o) => `  ${o.key}`).join('\n'),
    ).toEqual([])
  })

  it('正向核：已改对的页面必须**逐字**含失败态锚点（删了锚点 ⇒ 当场红）', () => {
    expect(FAILURE_ANCHORS.length, '正向核台账不许被删空').toBeGreaterThanOrEqual(5)
    for (const entry of FAILURE_ANCHORS) {
      const source = readFileSync(join(ROOT, entry.file), 'utf-8')
      for (const anchor of entry.anchors) {
        expect(
          source.includes(anchor),
          `${entry.file} 缺失败态锚点「${anchor}」（${entry.name}）—— `
            + '页面退回「读失败 = 空态 / 关闭态」了。失败态必须自己渲染出来：'
            + '`data-testid` + 可行动文案（照抄 dashboard/page.tsx）。',
        ).toBe(true)
      }
    }
  })

  it('台账只许缩短：不再命中的条目当场红（逼着删干净）', () => {
    const stale = staleLedger(ROOT)
    expect(
      stale,
      'LEDGER 里这些条目**不再命中**（对应 catch 已改对/已删）—— 台账只许缩短，请删掉这几条：\n'
        + stale.join('\n'),
    ).toEqual([])
  })

  it('判别力自证：坏形态判红、好形态不红（守卫退化成绿 ⇒ 这里先红）', () => {
    const BAD = [
      // ① 病灶原形（roles/page.tsx 改前）：读失败只清空列表
      `const load = async () => {
         try { const res = await roleApi.getRoles(); setRoles(res.data.data) }
         catch (e) { setRoles([]) }
       }`,
      // ② 通知开关形态（settings/page.tsx 改前）：读失败保持「关闭」= false
      `const load = async () => {
         try { const res = await settingsApi.getSettings(); setNotificationEnabled(!!res.data.data.enabled) }
         catch { setNotificationEnabled(false) }
       }`,
      // ③ 下拉选项清空（employees/page.tsx 改前）
      `const load = async () => { try { await p() } catch { setPositionOptions([]) } }`,
      // ④ prompt 里撒个谎：既有失败文案变量，但 catch 也没用它 ⇒ 仍判红
      `const load = async () => { try { await p() } catch { setRows([]); setHint('') } }`,
      // ⑤ 只有「提示语」、没有**读数类**失败态 ⇒ 仍判红（提示语会被下一条成功读数冲掉）
      `const search = async () => { try { await p() } catch { setOptions([]); setSearchHint('商品搜索失败') } }`,
    ]
    for (const source of BAD) {
      expect(hits(source), `坏形态应判红：\n${source}`).toBeGreaterThan(0)
    }
    const GOOD = [
      // ① 正确范式（dashboard/page.tsx）：失败**记进失败集**，读数**不清零**
      `const load = async () => {
         try { setStats(await p()) }
         catch { setBlockErrors((prev) => ({ ...prev, stats: true })) }
       }`,
      // ② 读失败 ⇒ 显式错误话术（stock-ledger 范式）
      `const load = async () => { try { await p() } catch { setError('读取失败 —— 请稍后重试') } }`,
      // ③ 写面 catch + 拦截器已 toast（读面读数不变）⇒ 不判
      `const doPost = async () => { try { await p() } catch { /* 拦截器已提示 */ } finally { setActing(false) } }`,
      // ④ 过程量清空（不是读数）⇒ 不判
      `const search = async () => { try { await p() } catch { /* 拦截器已提示 */ } finally { setSearching(false) } }`,
      // ⑤ 读失败 ⇒ 置「读不到」的显式标记（读数**不**清成空）
      `const load = async () => { try { setRows(await p()) } catch { setLoadFailed(true) } }`,
    ]
    for (const source of GOOD) {
      expect(hits(source), `好形态不该判红：\n${source}`).toBe(0)
    }
  })

  it('只改注释不红（对照读数：守卫不得被自己的说明文案喂红）', () => {
    const commented = `// 读失败只清空读数（setRoles([])）会让故障伪装成空态 —— 这段文字本身不该判红
      /* catch { setRows([]) } 也是 —— 块注释里的示例不是真形态 */
      const x = 1`
    expect(hits(commented)).toBe(0)
  })
})

/** 内存变异：把一段源码当**真语料**喂给**生产判据**（不落盘、不改仓内文件、不抄第二份正则） */
function hits(source: string): number {
  return swallowSitesFromSource(source, { file: 'probe.tsx' }).length
}
