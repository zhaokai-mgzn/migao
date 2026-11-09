// case_ids: MC-151
/**
 * 类级元守卫：**行内动作的链接规格只有一处定义**（issue #7082）。
 *
 * ## 为什么是类级（而不是"把四处手改完就完"）
 *
 * 2026-10-17 用户裁定「行内按钮样式让全部单据统一向订单保持一致，不要有多种风格设计」之后，
 * 共享原语 `src/components/ui/RowActionLink.tsx` 有了，但**同一份视觉规格的字面量**仍在
 * 售后 / 员工 / 员工资料面板 / 加工项面板各抄一份（issue #7082 的四处清单）。
 * 抄一份 = 第二份会漂的口径：原语改一次，副本不跟 ⇒ 两步之后没人知道哪个才是"对的"。
 * ⇒ 判据落成**扫描器 + 台账**（`frontend/admin-web/scripts/row-action-link-scan.mjs`），
 * 命令行（`node scripts/row-action-link-scan.mjs`）与本守卫**共用**它，不写第二份规则。
 *
 * ## 判据（各自能单独变红）
 *
 * ① **未登记即红**：出现规格副本且既不是已迁移文件、也不在 `exempt` 台账 ⇒ 红（具名文件 + 行号）；
 * ② **负控（射程准）**：原语**自身**里的同一串**不被扫**（它是比对基准，扫它 = 恒红）；
 *    反向自证：原语真的含这三个 token（否则扫描面是空的 ⇒ 恒绿假绿）；
 * ③ **接线在**：`migrated` 的文件必须逐字含 `<RowActionLink` + 登记的变体 prop
 *    （`size="sm"` 这类）—— 「把整段动作删掉 / 改回裸类名」也能让副本消失，这条堵掉那种假绿；
 * ④ **台账只许缩短**：`exempt` 条数 > `frozen_exempt_count` ⇒ 红；条目已不再命中 ⇒ 僵尸红（逼着删）；
 * ⑤ **形态台账不撒谎**：`conformant`（有意**不**走本组件的行内动作，如入库单 / 商品）必须在位
 *    —— 要求锚在、禁止锚不在；
 * ⑥ **判别力自证**：坏形态在**真语料的内存副本**上各自判红、好形态不红、只改注释不红。
 *
 * ## 外观不变的那一半（不在本文件，见下）
 *
 * 「迁移后长相逐字不变」由**原语自己的变体断言**承担：
 * `tests/unit/components/RowActionLink.test.tsx` 逐条钉「`size="sm"` ⇒ `text-sm`」「`emphasis` ⇒
 * `font-medium`」「`disabledStyle="keep"` ⇒ 保持字色 + `cursor-default`」「`tone="danger"` ⇒ 红字」，
 * 各带反向自证（默认档**不得**出现该 class）。四个消费点的页面测（售后 / 员工 / 加工项 / 工人档案）
 * 继续按 `role` / `text` / `testid` 定位，迁移不动它们的选择器。
 *
 * ## 边界（照实登记，`migao-dev-flow` §19.1）
 *
 * - 只扫 `frontend/admin-web/src/**`（`mini-app` / H5 各自一套 token）；
 * - **只裁「与原语同规格」的副本**：缺 `hover:text-primary-700` 的**漂移副本**（`purchase-orders` /
 *   `suppliers` / 各处页面级链接）不在面内 —— 它们已不是同一份规格，收口要先逐页裁定形态；
 * - 静态文本判据：判不了「渲染是否同色同字号」（原语变体断言 + 真机读图承担）；
 * - 判不了「新页面用 `Button` 手拼行内动作」（意图判不了）—— 那一半由
 *   `row-action-flat-scan.mjs`（操作列不得折叠成「⋯」）+ 评审承担。
 */
import { describe, it, expect } from 'vitest'

import {
  LEDGER_PATH,
  openingTags,
  MIN_SCOPE_FILES,
  PRIMITIVE,
  SPEC_TOKENS,
  audit,
  defaultRoot,
  readSources,
  specCopiesIn,
  stripComments,
  wiringGaps,
} from '../../scripts/row-action-link-scan.mjs'

/** 扫描器是 `.mjs`（命令行与守卫共用同一份实现）⇒ 在测试侧补最小类型，不引第二份规则 */
interface SpecCopy {
  line: number
  classString: string
}
interface LedgerEntry {
  file: string
  site?: string
  /** 调用点唯一的一句话（接线判据按**同一个开标签**认人） */
  marker?: string
  requires?: string[]
  pre_migration_tokens?: string[]
  reason?: string
  forbidden_anchors?: string[]
  forms?: { component: string; marker: string; requires?: string[] }[]
}
interface AuditReport {
  scopeFiles: number
  copies: Record<string, SpecCopy[]>
  unregistered: string[]
  regressed: string[]
  wiringMissing: LedgerEntry[]
  staleExempt: LedgerEntry[]
  exemptOverBaseline: number
  conformantBroken: LedgerEntry[]
  primitiveBlind: boolean
  migrated: LedgerEntry[]
  exempt: LedgerEntry[]
  conformant: LedgerEntry[]
}

const ROOT = defaultRoot()
const sourcesOf = (): Record<string, string> => readSources(ROOT) as Record<string, string>
const copiesIn = (sources: Record<string, string>): Record<string, SpecCopy[]> =>
  specCopiesIn(sources) as Record<string, SpecCopy[]>
const reportOf = (): AuditReport => audit(ROOT) as AuditReport

describe('行内动作链接规格只有一处定义（issue #7082 / MC-150）', () => {
  it('① 扫描面非空 + 原语自证：原语真的含规格 token（否则扫描面为空 ⇒ 恒绿假绿）', () => {
    const sources = sourcesOf()
    expect(Object.keys(sources).length).toBeGreaterThanOrEqual(MIN_SCOPE_FILES)
    // 注入：把原语里的 `hover:underline` 删掉 ⇒ 这条红（扫描器再也不可能证明"副本"存在）
    for (const token of SPEC_TOKENS) expect(sources[PRIMITIVE]).toContain(token)
    expect(copiesIn({ [PRIMITIVE]: sources[PRIMITIVE] })).toEqual({})
    expect(reportOf().primitiveBlind).toBe(false)
  })

  it('② 负控：原语**自身**里的同一串不被扫（射程只到副本）', () => {
    // 真语料：原语不在 copies 里
    expect(reportOf().copies[PRIMITIVE]).toBeUndefined()
    // 内存对照：同一段源码放进原语键 ⇒ 不报；放进别的文件键 ⇒ 报（同一判据、只差射程）
    const spec = `className="${SPEC_TOKENS.join(' ')}"`
    expect(copiesIn({ [PRIMITIVE]: spec })).toEqual({})
    expect(copiesIn({ 'src/app/(dashboard)/x/page.tsx': spec })).toEqual({
      'src/app/(dashboard)/x/page.tsx': [{ line: 1, classString: `"${SPEC_TOKENS.join(' ')}"` }],
    })
  })

  it('③ 未登记即红：现取零未登记（四处已迁移 + 一条豁免）；新出现的第五处当场红', () => {
    const report = reportOf()
    // 注入：在任一新文件里手抄一份规格串（如新列表页照抄 `text-primary-600 hover:text-primary-700 hover:underline`）
    // ⇒ 下面第一条具名红（打印出那个文件）
    expect(report.unregistered, `未登记副本：${report.unregistered.join('、')}`).toEqual([])
    // 台账 ⇄ 现取双向相等：副本集合 = 豁免集合（4 处迁移后已无副本）
    expect(Object.keys(report.copies).sort()).toEqual(report.exempt.map((e) => e.file).sort())
    // 内存注入：新文件出现副本 ⇒ 未登记红
    const sources = sourcesOf()
    sources['src/app/(dashboard)/new-list/page.tsx'] = `<button className="${SPEC_TOKENS.join(' ')}">详情</button>`
    expect(Object.keys(copiesIn(sources))).toContain('src/app/(dashboard)/new-list/page.tsx')
  })

  it('④ 迁移回退即红：已迁移文件里再出现裸类名 ⇒ 点名那个文件', () => {
    const report = reportOf()
    expect(report.regressed).toEqual([])
    // 内存注入：把"售后的行内动作迁回手抄"逐字还原（= 改前形态）
    const sources = sourcesOf()
    const afterSales = 'src/app/(dashboard)/after-sales/page.tsx'
    sources[afterSales] = sources[afterSales].replace(
      /<RowActionLink\s+size="sm"\s+onClick=\{\(\) => router\.push\(`\/after-sales\/\$\{ticket\.id\}`\)\}\s*>\s*查看\s*<\/RowActionLink>/,
      '<button className="text-primary-600 hover:text-primary-700 hover:underline transition-colors text-sm">查看</button>',
    )
    expect(sources[afterSales]).toContain('text-primary-600 hover:text-primary-700')
    const copies = copiesIn(sources)
    expect(Object.keys(copies), '注入后必须命中售后页').toContain(afterSales)
    // 注入自证生效：同一个文件在真语料里**不**命中（否则上面那条是空断言）
    expect(Object.keys(copiesIn(sourcesOf()))).not.toContain(afterSales)
  })

  it('⑤ 接线在：四处（5 个动作）仍在用原语 + 各自登记的变体 prop（摘掉接线 ⇒ 红）', () => {
    const report = reportOf()
    // 注入：把员工「姓名」那一格的接线整段摘掉（文件里**还有**操作列的另一处 `<RowActionLink>`）
    // ⇒ 这条必须具名红。这正是「文件级判据会假绿」的形态：只数文件有没有 `<RowActionLink` 是不够的。
    expect(report.wiringMissing.map((m) => m.site)).toEqual([])
    // 4 个文件 / 5 个动作（加工项面板一行里两个动作，各登记一条）
    expect([...new Set(report.migrated.map((m) => m.file))].length).toBe(4)
    expect(report.migrated.length).toBe(5)

    const sources = sourcesOf()
    const employees = 'src/app/(dashboard)/employees/page.tsx'
    const before = sources[employees]
    sources[employees] = before.replace(
      /<RowActionLink\s+size="sm"\s+emphasis\s+disabledStyle="keep"\s+disabled=\{!canWrite\}\s+onClick=\{\(\) => handleEdit\(record\)\}\s*>\s*\{record\.name\}\s*<\/RowActionLink>/,
      '<span className="text-sm font-medium">{record.name}</span>',
    )
    expect(sources[employees]).not.toBe(before)
    // 文件里仍有另一处 `<RowActionLink>`（操作列「编辑」）⇒ 文件级判据仍会绿；按开标签认人的判据必须红
    expect(sources[employees]).toContain('<RowActionLink')
    const gaps = wiringGaps(sources, report.migrated) as LedgerEntry[]
    expect(gaps.map((g) => g.marker)).toContain('handleEdit(record)')
  })

  it('⑥ 台账只许缩短：豁免不超冻结基线、僵尸条目即红（双向相等）', () => {
    const report = reportOf()
    expect(report.exemptOverBaseline).toBeLessThanOrEqual(0)
    expect(report.staleExempt).toEqual([])
    // 内存注入：给一个**没有副本**的文件登记豁免 ⇒ 僵尸红
    const clean = 'src/app/(dashboard)/orders/page.tsx'
    expect(copiesIn({ [clean]: sourcesOf()[clean] })[clean]).toBeUndefined()
  })

  it('⑦ 形态台账不撒谎（**双读**）：入库单有意保持 ghost 单动作 —— 禁止锚不在 + 要求形态在', () => {
    const report = reportOf()
    // 注入口 A：把入库单的「详情」改成 `<RowActionLink>` 而不改台账 ⇒ 禁止锚命中 ⇒ 红
    // 注入口 B：把入库单行内「详情」的 `variant="ghost"` 改成 `variant="secondary"` ⇒ 形态锚失效 ⇒ 红
    expect(report.conformantBroken.map((c) => c.file)).toEqual([])
    const conformantFiles = report.conformant.map((c) => c.file)
    expect(conformantFiles).toContain('src/app/(dashboard)/inbound-orders/page.tsx')

    const sources = sourcesOf()
    for (const entry of report.conformant) {
      const code = stripComments(sources[entry.file])
      expect(entry.forms?.length, `${entry.file} 缺形态要求`).toBeGreaterThan(0)
      // ① 禁止锚：一个都不许出现（否则「悄悄改成原语形态」照样绿）
      for (const needle of entry.forbidden_anchors ?? []) {
        expect(code, `${entry.file} 出现了禁止锚 ${needle}`).not.toContain(needle)
      }
      // ② 要求形态：每个形态都要在**同一个开标签**里成立（文件级字符串匹配会假绿）
      for (const form of entry.forms ?? []) {
        const tags = openingTags(code, form.component) as string[]
        expect(
          tags.some((tag) => tag.includes(form.marker) && (form.requires ?? []).every((n) => tag.includes(n))),
          `${entry.file} 的 ${form.component}[${form.marker}] 形态要求不成立`,
        ).toBe(true)
      }
    }

    // 判别力自证（内存）：把入库单行内动作改成 RowActionLink ⇒ 禁止锚命中
    const inbound = 'src/app/(dashboard)/inbound-orders/page.tsx'
    const mutated = sources[inbound].replace(
      /<Button variant="ghost" size="sm" onClick=\{\(\) => void openDetail\(row\.id\)\}>/,
      '<RowActionLink onClick={() => void openDetail(row.id)}>',
    )
    expect(mutated).not.toBe(sources[inbound])
    expect(mutated).toContain('<RowActionLink')
    // 反向对照：真语料里该禁止锚不存在（否则上面那条是空断言）
    expect(stripComments(sources[inbound])).not.toContain('<RowActionLink')
  })

  it('⑧ 注释里的同款串不误伤（迁移说明必须能写字）：strip 生效', () => {
    const spec = SPEC_TOKENS.join(' ')
    const commented = `// 改前长这样：className="${spec}"\n/* ${spec} */\nconst x = 'text-sm'`
    expect(copiesIn({ 'src/a.tsx': commented })).toEqual({})
    expect(stripComments(commented)).not.toContain('text-primary-600')
    // 反向自证：同一串在**代码**里（非注释）⇒ 命中
    expect(copiesIn({ 'src/a.tsx': `const c = '${spec}'` })['src/a.tsx']).toHaveLength(1)
  })

  it('⑨ 台账自洽：每条 migrated 都冻结了改前 token（迁移不得"顺手改观感"）', () => {
    const report = reportOf()
    for (const m of report.migrated) {
      expect(m.file, '台账条目缺文件').toMatch(/^src\/.+\.[t]sx$/)
      expect(m.site, `${m.file} 缺 site 说明`).toBeTruthy()
      expect(m.marker, `${m.file} 缺调用点 marker（接线判据按开标签认人）`).toBeTruthy()
      expect(m.requires?.length, `${m.file} 缺变体要求`).toBeGreaterThan(0)
      expect(Array.isArray(m.pre_migration_tokens), `${m.file} 缺改前 token 记录`).toBe(true)
      expect(m.pre_migration_tokens).toContain('hover:underline')
    }
    // 台账落点可解析（守卫读的就是它）
    expect(LEDGER_PATH.endsWith('row-action-link-ledger.json')).toBe(true)
  })
})
