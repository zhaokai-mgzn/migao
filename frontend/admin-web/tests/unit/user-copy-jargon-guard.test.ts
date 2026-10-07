// case_ids: UI-057, UI-058, UI-092, UI-093
//
// 类级元守卫：**内部词汇不得写进用户可见文案**。八个形态，同一条纪律。
//
// ① 度量分层代号（#5565）：省料看板把 `L2` / `L3` 抄进了页头副标题与区块标题
//    ⇒ 用户逐字反馈「L2和L3是什么概念，用户不懂，我也不懂」。
// ② 机制隐喻（#5576）：「池」是 pooling 的实现隐喻（池看板/池化开关/进池/池内/成批区）
//    ⇒ 用户逐字反馈「池看板这个命名用户不太懂」，菜单改名**智能派单**并与页内文案一起去隐喻。
// ③ 服务端**分组标签**（#6459）：省料看板把 `切换后（采购入库）` / `存量导入（切换前历史包袱）` /
//    `来源未知`（= `SavingMetricViews.cohortLabel` 的三个取值）做成「来源组对照」三行表端给新用户
//    ⇒ 用户逐字「省料看板为什么一定要加上切换后（采购入库）这种概念，让新用户如何理解」。
// ④⑤⑥⑦⑧ **研发腔五族**（#6488，用户 2026-10-07 逐字「我们系统中暴露了大量的这种研发过程产生的
//    文字，适当的文档可以引导和教育用户如何使用我们的产品，但是这类文案明显不是一个好的引导文案」）：
//    接口与参数细节（「端点没有关键词参数」）、内部机制名（「读面」「派生值」「真值源」「组合键」）、
//    研发过程编号与判据语（`issue #4886` / 「判据」）、代码标识符上屏（`oversize_height_threshold`）、
//    行内代码片里塞标识符（`` `HEM_MARGIN` ``）。
//
// 形态相同：写码时**对着 issue / 设计文档写**，把内部编号、机制名、接口细节当名词带上了屏。
// 单个页面改一次不解决复发 ⇒ 本守卫是那条类级收口。
//
// ## 判据源只有一份
//
// 规则表与「什么算上屏」的口径都在 **`scripts/user-copy-scan.mjs`**（`RULES` / `candidateStrings`），
// 本测试与命令行**共用**它 —— 不在这里写第二份正则（判据漂移的起点）。
// 复算：`cd frontend/admin-web && node scripts/user-copy-scan.mjs`
// 规范：`docs/design/user-facing-copy-standard.md`
//
// ⚠️ 边界（照实登记，issue #6459）：本守卫扫**源码字面量**，判不了**服务端下发的字符串** ——
//    例如米宝会话卡 `src/components/chat/BatchStockCard.tsx` 直接渲染响应里的 `cohortLabel`，
//    那三个词会经它上屏而不被本守卫抓到（该面另单跟踪，本单**有意不做**）。
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

import { RULES, EXEMPT, candidateStrings, findViolations, scanProject } from '../../scripts/user-copy-scan.mjs'

const ROOT = process.cwd()

describe('用户可见文案不得含内部词汇 / 研发腔（#5565 · #5576 · #6459 · #6488）', () => {
  const { files, candidates, raw, offenders } = findViolations(ROOT)
  const byRule = (id: string) => offenders.filter((o) => o.rule === id)

  it('普查面非空（扫不到文件 ⇒ 本判据在扫空气，而不是"没问题"）', () => {
    expect(files.length, '三个扫描目录下应有一批源文件').toBeGreaterThanOrEqual(200)
    expect(candidates.length, '应抽出成批「会上屏」的候选文案').toBeGreaterThanOrEqual(3000)
    for (const anchor of ['src/lib/craft-calc-glossary.ts', 'src/app/(dashboard)/stock-ledger/page.tsx']) {
      expect(files, `扫描面必须含 ${anchor}`).toContain(anchor)
    }
  })

  it('规则表不许被悄悄删空（八条一条都不许少；每条必须给得出可行动的出口）', () => {
    expect(RULES.map((r) => r.id)).toEqual(['R1', 'R2', 'R3', 'R4', 'R5', 'R6', 'R7', 'R8'])
    for (const rule of RULES) {
      expect(rule.name.length, `${rule.id} 缺名字`).toBeGreaterThan(1)
      expect(rule.出口.length, `${rule.id} 的出口必须写到「改成什么」，否则判红时读的人无从下手`).toBeGreaterThan(15)
    }
  })

  // 每条规则一个用例（判红时**具名到规则**，出口逐条给）
  for (const rule of RULES) {    it(`[${rule.id}] ${rule.name} 没有出现在用户可见文案里（未登记即红）`, () => {
      expect(
        byRule(rule.id).map((o) => `${o.where}  ${o.text.slice(0, 120)}`),
        `${rule.name} —— 商家读不懂（issue #6488）。\n出口：${rule.出口}\n`
          + '（确有必要请登记 scripts/user-copy-scan.mjs 的 EXEMPT —— 只许缩短。）',
      ).toEqual([])
    })
  }

  it('豁免台账不空转：每条豁免必须**仍然**命中某条规则（失效的当场判红 ⇒ 逼着删干净）', () => {
    // ⚠️ 必须比 **raw**（豁免前）——比 offenders 的话，被豁免的那条永远不在里面 ⇒ 台账恒被判「空转」
    const seen = new Set(raw.flatMap((o) => [o.where, o.file]))
    const stale = EXEMPT.filter((entry) => !seen.has(entry))
    expect(
      stale,
      'EXEMPT 里有**不再命中**的条目 —— 台账只许缩短，请删掉这几条：\n' + stale.join('\n'),
    ).toEqual([])
  })

  it('判别力自证：坏形态各自判红、好文案一条不红（守卫退化成绿 ⇒ 这里先红）', () => {
    const fires = (text: string) => RULES.filter((r) => r.test(text)).map((r) => r.id)
    // 逐族取样：都是 2026-10-07 现场逐字摘录的**真实**坏文案
    expect(fires('请先输入商品关键词（端点没有关键词参数，商品必须先选中才能按它查流水）')).toContain('R1')
    expect(fires('本页宁可不查，也不做「一次拉全量」的假方便')).toContain('R1')
    expect(fires('「剩余米数」是派生值（= 入库米数 − 已派工消耗）')).toContain('R2')
    expect(fires('（issue #4886）；')).toContain('R3')
    expect(fires('净窗高 > 超高阈值（`oversize_height_threshold`）')).toContain('R4')
    expect(fires('**高方向**的卷边量（引擎 `HEM_MARGIN`）')).toContain('R5')
    expect(fires('（L2）每平方米成品用掉多少米布')).toContain('R6')
    expect(fires('池看板里的进池订单')).toContain('R7')
    expect(fires('来源未知（切换前历史包袱）')).toContain('R8')
    // **好**文案（同一条纪律的另一侧）：行业术语 + 商家动作 ⇒ 一条规则都不该命中
    expect(fires('净窗高超过你们设的阈值就走特殊工艺档，点「去处理」按你家口径核一遍。')).toEqual([])
    expect(fires('批次余量要按商品查：先在上方搜一个商品再点选。')).toEqual([])
    expect(fires('未定价 ≠ ¥0.00：报工按未定价处理，点「去处理」逐道补价。')).toEqual([])
  })

  it('只改注释不红（对照读数：守卫不得被自己的文案喂红）', () => {
    const source = [
      '// 端点 / 读面 / 派生值 / issue #1234 —— 这些词在注释里是合法的',
      '/* 组合键 / 真值源 / oversize_height_threshold 也一样（块注释） */',
      'const x = 1',
    ].join('\n')
    expect(candidateStrings(source, 'probe.tsx')).toEqual([])
  })

  it('真声明面自证：源码里的**坏文案**确实被抽出来（否则上面全绿 = 假绿）', () => {
    const source = [
      'export const a = () => <p>请先输入商品关键词（端点没有关键词参数）</p>',
      "export const b = '「剩余米数」是派生值（= 入库米数 − 已派工消耗）'",
    ].join('\n')
    const found = candidateStrings(source, 'probe.tsx').map((c) => c.text)
    expect(found.some((t) => t.includes('端点'))).toBe(true)
    expect(found.some((t) => t.includes('派生值'))).toBe(true)
  })

  it('扫描面只认三个目录下的 ts/tsx（口径自证）', () => {
    const { files: scanned } = scanProject(ROOT)
    expect(scanned.every((f) => /^src\/(app|components|lib)\//.test(f))).toBe(true)
    expect(scanned.every((f) => /\.(tsx|ts)$/.test(f))).toBe(true)
  })

  it('不上屏的位置不抽：`className` / `data-testid` / `style` 与 CSS 模板串', () => {
    const source = [
      "export const a = <div className='端点 读面' data-testid='派生值' style={{ color: 'red' }}>真文案</div>",
      'export const css = `@media print { /* 只有「本次目标」上纸：非目标单据留在 display:none */ }`',
    ].join('\n')
    const found = candidateStrings(source, 'probe.tsx').map((c) => c.text)
    expect(found).toContain('真文案')
    expect(found.some((t) => t.includes('端点'))).toBe(false)
    expect(found.some((t) => t.includes('本次目标'))).toBe(false)
  })

  it('扫描器是仓内单一源且只读（跑一遍不落文件、不复制第二份规则）', () => {
    const scanner = relative(ROOT, join(ROOT, 'scripts', 'user-copy-scan.mjs'))
    expect(scanner).toBe('scripts/user-copy-scan.mjs')
    expect(readFileSync(join(ROOT, scanner), 'utf-8')).toContain('export const RULES')
    const before = readdirSync(join(ROOT, 'scripts')).length
    findViolations(ROOT)
    expect(readdirSync(join(ROOT, 'scripts')).length).toBe(before)
    expect(statSync(join(ROOT, 'scripts', 'user-copy-scan.mjs')).isFile()).toBe(true)
  })
})
