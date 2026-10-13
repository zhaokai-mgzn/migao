// case_ids: UI-057, UI-058, UI-092, UI-093
//
// 类级元守卫：**内部词汇不得写进用户可见文案**。九个形态 + 页面副标题四条，同一条纪律。
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
// ⑨ **占位符字母 / 模式代号**（#6488 续，用户 2026-10-08 逐字「用户不理解这句话是啥"库存为什么从 X 变成 Y"」）：
//    把 X/Y 当变量、把设计文档里的「A 模式」写进散文 ⇒ 商家读不懂。
//
// **页面副标题四条**（S1~S4，用户 2026-10-08 定的标准）：副标题要说清「**这个功能是干什么的**」
// （正例：「管理客户信息、标签和互动记录」；「待派订单按料（商品 × 颜色 × 门幅）合并 ——
// 同料合并领料，减少接头损耗；**加急单不参与合并，立即单独派单**」也行），**关键规则加粗**。
// ⇒ 机械可判的四条：箭头链路（⇒/→）、表达式（`每行 = 一次…`）、本企业数值口径（`0.5 米级`/`0.1 米粒度`）、
//    占位符字母与模式代号。**「讲不讲用途」判不了**，只能靠规范与评审（见 docs/design/user-facing-copy-standard.md §3）。
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
//    例如黄金策会话卡 `src/components/chat/BatchStockCard.tsx` 直接渲染响应里的 `cohortLabel`，
//    那三个词会经它上屏而不被本守卫抓到（该面另单跟踪，本单**有意不做**）。
import { describe, it, expect } from 'vitest'
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

import {
  RULES,
  EXEMPT,
  SUBTITLE_RULES,
  SUBTITLE_EXEMPT,
  candidateStrings,
  toCandidate,
  findViolations,
  findSubtitleOffenses,
  pageSubtitles,
  scanProject,
  WORKER_H5_EXEMPT,
  WORKER_H5_ROOT,
  findWorkerH5Violations,
  REMOVED_PAGE_NAMES,
  DEAD_PAGE_NAME_EXEMPT,
  deadPageNames,
  livePageNames,
  removedPageNameHit,
} from '../../scripts/user-copy-scan.mjs'

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

  it('规则表不许被悄悄删空（九条一条都不许少；每条必须给得出可行动的出口）', () => {
    expect(RULES.map((r) => r.id)).toEqual([
      'R1', 'R2', 'R3', 'R4', 'R5', 'R6', 'R7', 'R8', 'R9', 'R10', 'R11', 'R12',
    ])
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
    const fires = (text: string) => RULES.filter((r) => r.test(text)).map((r) => r.id)    // 逐族取样：都是 2026-10-07 现场逐字摘录的**真实**坏文案
    expect(fires('请先输入商品关键词（端点没有关键词参数，商品必须先选中才能按它查流水）')).toContain('R1')
    expect(fires('本页宁可不查，也不做「一次拉全量」的假方便')).toContain('R1')
    expect(fires('「剩余米数」是派生值（= 入库米数 − 已派工消耗）')).toContain('R2')
    expect(fires('（issue #4886）；')).toContain('R3')
    expect(fires('净窗高 > 超高阈值（`oversize_height_threshold`）')).toContain('R4')
    expect(fires('**高方向**的卷边量（引擎 `HEM_MARGIN`）')).toContain('R5')
    expect(fires('（L2）每平方米成品用掉多少米布')).toContain('R6')
    expect(fires('池看板里的进池订单')).toContain('R7')
    expect(fires('来源未知（切换前历史包袱）')).toContain('R8')
    // R12（#6826 的 B2 面）：引号里的旧页名、以及**没有引号**的旧页名都必须判红
    expect(fires('补救：到「工艺配置」页新建这条路线。')).toContain('R12')
    expect(fires('去定价（工艺配置 · 工序单价）')).toContain('R12')
    expect(fires("linkLabel: '工艺配置 → 算料配置'")).toContain('R12')
    expect(fires('开通后请到「工艺配置 → 工序管理」手工维护工序与工艺路线。')).toContain('R12')
    // 反侧：新指针与「工序库」面板逐字**都不许**红（域 label 现在是真值源里的一员）
    expect(fires('到「企业基础设置 → 工艺路线」新建这条路线；先到「企业基础设置 → 工序与部位单价」新增工序。')).toEqual([])
    expect(fires('工序库 · 计件单价')).toEqual([])
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

  /**
   * 🔴 issue #6663 扩网的自证：**表达式兜底 + 内部标识**。
   *
   * 为什么必须自证：改前 R1~R9 只扫**字面量**，`{param.key}` / env 名这类形态
   * **永远不判红** —— 一个不判红的判据等于没有判据（`migao-acceptance`「空断言」同族）。
   * 这里逐族取样：坏形态各自判红，**好形态一条不红**（否则判据会逼人把好码改坏）。
   */
  it('判别力自证②：R10「内部键兜底」/ R11「直接渲染内部键与 env 名」各自判红，好形态不红', () => {
    const R = (id: string) => RULES.find((r) => r.id === id)!
    const fires = (kind: string, text: string) =>
      RULES.filter((r) => r.test({ kind, text })).map((r) => r.id)

    // ── 坏形态（都是本轮/邻近轮真实摘录）──
    // R10：映射表兜底把**键本身**端给商家（`customer_service` 这种内部值上屏）
    expect(R('R10').test({ kind: 'jsx-text', text: 'CustomerChannelLabels[channel] || channel' })).toBe(true)
    expect(R('R10').test({ kind: 'jsx-text', text: 'permissionLabelMap[c] || c' })).toBe(true)
    // R11 ①：`{param.key}` —— 引擎标量参数的键名直接渲染（本包病灶，CalcCaliberPanel）
    expect(fires('jsx-member', 'param.key')).toContain('R11')
    expect(fires('jsx-member', 'p.key')).toContain('R11')
    expect(fires('jsx-member', 'field.key')).toContain('R11')
    // ⚠️ 反面（**有意不判**）：`rec.itemKey` 是服务端下发的**数据值**（余料台账的料组键），
    //    不是代码标识符 —— 判它会逼人把正常的数据渲染改坏。
    expect(R('R11').test({ kind: 'jsx-member', text: 'rec.itemKey' })).toBe(false)
    // R11 ②：环境变量名上屏（本包病灶，设置页「手机端入口」）
    expect(fires('jsx-text', '部署时设置 NEXT_PUBLIC_BMINI_H5_URL 后重新构建即可')).toContain('R11')

    /**
     * 🔴 **入参形态自证**（本包实测踩过的坑）：规则表要同时吃得下**裸字符串**（判别力自证、
     * 以及任何 `RULES[i].test('一句文案')` 的老写法）与**候选对象** `{kind, text}`（真扫描面）。
     * 只吃一种 ⇒ 要么真扫描 `TypeError`，要么规则**静默不命中**（「加了规则却零命中」的假绿）。
     */
    for (const rule of RULES) {
      const asString = () => rule.test('这是一句没有内部词汇的普通商家文案')
      const asCandidate = () => rule.test({ kind: 'jsx-text', text: '这是一句没有内部词汇的普通商家文案' })
      expect(asString, `${rule.id} 吃不下裸字符串（旧写法会崩）`).not.toThrow()
      expect(asCandidate, `${rule.id} 吃不下候选对象（真扫描面会崩）`).not.toThrow()
    }

    // ── 好形态：一条规则都不许红（否则判据会逼人把好码改坏）──
    // `key={x.key}` / `data-testid={`x-${x.key}`}` 里的成员访问是**控件属性**，不是上屏文本
    // （实测：放宽到属性面会从 3 条涨到 51 条**全假红**）
    expect(R('R11').test({ kind: 'attr:key', text: 'param.key' })).toBe(false)
    // 数据字段（服务端内容）不是代码标识符
    expect(R('R11').test({ kind: 'jsx-member', text: 'zone.label' })).toBe(false)
    expect(R('R11').test({ kind: 'jsx-member', text: 'domain.advanced.length' })).toBe(false)
    // 整句里出现 env 名（不是**只**渲染它）也不判 —— 那是散文，不是「直接渲染标识」
    expect(R('R11').test({ kind: 'string', text: '地址取自单一配置（唯一读取点 = @/lib/bmini-h5-url）' })).toBe(false)
    // R10 的好形态：兜底换成人话（`?? 「其他」`）
    expect(R('R10').test({ kind: 'string', text: 'LABELS[k] ?? 「其他」' })).toBe(false)
    // R10 不误伤数组下标取值本身（没有 `|| 键` 兜底）
    expect(R('R10').test({ kind: 'string', text: 'CustomerChannelLabels[channel]' })).toBe(false)
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

  /**
   * issue #6663 扩网的**抽取面**自证：`{param.key}` 与 env 名必须被**抽出来**。
   *
   * 为什么单独一条：抽取（`candidateStrings`）与判定（`RULES`）是两跳 ——
   * 抽不出来，规则再准也是空跑（这正是改前「表达式形态永远不判红」的机制）。
   */
  it('扩网抽取自证：表达式成员访问与 env 名都进了候选面（抽不出来 ⇒ 规则空跑）', () => {
    const source = [
      'export const a = ({ param }: any) => <div><span>{param.key}</span></div>',
      'export const b = () => <p>设置 NEXT_PUBLIC_BMINI_H5_URL 后重新构建</p>',
      // 控件属性里的同一形态**不该**被当成文案（否则假红 51 条，见判别力自证②）
      'export const c = ({ param }: any) => <div key={param.key} data-testid={`x-${param.key}`} />',
    ].join('\n')
    const found = candidateStrings(source, 'probe.tsx')
    expect(
      found.filter((c) => c.kind === 'jsx-member').map((c) => c.text),
      '`{param.key}` 必须被抽成 jsx-member 候选',
    ).toContain('param.key')
    expect(
      found.some((c) => c.kind === 'jsx-text' && c.text.includes('NEXT_PUBLIC_BMINI_H5_URL')),
      'env 名必须被抽成 jsx-text 候选',
    ).toBe(true)
    // 属性里的 `param.key`（`key=` / `data-testid=`）一个都不抽
    expect(found.filter((c) => c.kind === 'jsx-member' && c.text === 'param.key')).toHaveLength(1)
  })

  it('扩网后的**真实扫描面**自身清白：R10 / R11 零命中（含本包刚修的两处）', () => {
    const { offenders } = findViolations(ROOT)
    const exprHits = offenders.filter((o) => o.rule === 'R10' || o.rule === 'R11')
    expect(
      exprHits.map((o) => `${o.where}  ${o.text.slice(0, 120)}`),
      '表达式面命中 —— 内部键 / 兜底键 / env 名不得上屏（改法见 R10/R11 的出口）',
    ).toEqual([])
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

/**
 * R12（issue #6826 的 B2 面，`#6580` 撤掉页面名之后的那一类缺陷）：**上屏字面量不得出现已移除的页面名**。
 *
 * 病灶：`#6580` 把「参数总览」一级项与「加工项管理」/「工艺配置」两个菜单项撤掉（功能体并入
 * `/settings` =「企业基础设置」页内的配置域），而**前端上屏文案**仍逐字写着旧页名 ——
 * 商家照着提示去点，**找不到那个页面**（这与服务端文案面是同一类，服务端那一半由
 * `tests/unit_ci_workflows/test_removed_page_copy_guard.py` 承担；两面合起来才覆盖这个类）。
 *
 * 判据形态（**会红**，不是空断言）：
 * ① 扫描面非空 + 六个已修文件都在扫描面内（判据看不见它们 ⇒ 红）；
 * ② 逐文件现扫 R12 = 0（任一文件里出现旧页名 ⇒ 红，具名到 `文件:行 + 原文`）；
 * ③ **注入式红证**：把修过的旧串塞回该文件的源码 ⇒ R12 当场命中「现在被修的那一处」；
 * ④ 正控：新指针（`企业基础设置 → <域 label>`）在六个文件里逐字出现（改错了也红）；
 * ⑤ 豁免台账只许缩短（条目不再命中 ⇒ 红；六个已修文件**一个都不许**进台账）。
 *
 * 边界（照实登记，§19.1）：判不了「文案是否真上屏」（要 §15.7 真机）；判不了「假出口」
 * （页名对了但按文案做仍做不到 —— 那由 `docs/design/user-facing-copy-standard.md` 的评审口径承担）；
 * 也判不了服务端下发的字符串（那是上面那半个判据的面）。
 */
describe('R12：上屏字面量不得出现已移除的页面名（#6826 · B2 面）', () => {
  /** 本包逐条修过的五个上屏字面量所在文件（注入式红证的靶子 + 正控 + 台账不许收它们） */
  const FIXED_FILES = [
    'src/app/register/page.tsx',
    'src/components/orders/OrderCraftFields.tsx',
    'src/components/production/UnpricedNotice.tsx',
    'src/lib/route-source.ts',
    'src/lib/meters-formula-legend.ts',
  ]

  it('判别力自证：R12 在册，且十一个既有规则的语义没被这次追加改掉', () => {
    const r12 = RULES.find((r) => r.id === 'R12')
    expect(r12, 'R12（已移除的页面名）必须在规则表里').toBeTruthy()
    expect(r12!.name).toBe('已移除的页面名')
    expect(r12!.出口.length, 'R12 的出口必须写到「按动作改指哪个域」').toBeGreaterThan(30)
    // 已移除集合 = 现取（不是硬编码在规则里）：本期四个名字都不在导航真值源里
    for (const name of REMOVED_PAGE_NAMES) expect(deadPageNames()).toContain(name)
    // 真值源是**活的**：域 label 与一级菜单名都在册（新指针指向的名字必须可判）
    for (const live of ['企业基础设置', '工艺路线', '算料口径', '工序与部位单价', '加工项与分类', '加工费组合']) {
      expect(livePageNames(), `导航真值源里应有 ${live}`).toContain(live)
    }
    // 解析没坏：菜单项（带 path 的真菜单）+ 域 label 都**非空**（读成空集 ⇒ 规则静默放行 ⇒ 红）
    expect(livePageNames().size, '真值源读成空集 = 规则静默放行').toBeGreaterThanOrEqual(25)
    expect(deadPageNames()).not.toContain('工艺路线')
  })

  it('扫描面非空 + 五个已修文件都在扫描面内（看不见 ⇒ 判据在扫空气）', () => {
    const { files } = findViolations(ROOT)
    expect(files.length, '三个扫描目录下应有一批源文件').toBeGreaterThanOrEqual(200)
    for (const rel of FIXED_FILES) {
      expect(files, `扫描面必须含 ${rel}`).toContain(rel)
    }
  })

  it('🔴 已修文件里 R12 逐文件零命中（出现旧页名 ⇒ 红，具名到 文件:行 + 原文）', () => {
    const lines = []
    for (const rel of FIXED_FILES) {
      const src = readFileSync(join(ROOT, rel), 'utf-8')
      for (const c of candidateStrings(src, rel)) {
        const hit = removedPageNameHit(c.text)
        if (hit) lines.push(`${rel}:${c.line} 出现已移除页面名「${hit}」：${c.text.slice(0, 120)}`)
      }
    }
    expect(lines, '上屏文案里出现了已移除的页面名（商家按它去点会找不到页面）：\n' + lines.join('\n')).toEqual([])
  })

  it('正控：新指针在已修文件里逐字出现（改错了也红）', () => {
    const NEW_POINTERS: Array<[string, string]> = [
      ['src/app/register/page.tsx', '企业基础设置 → 工序与部位单价'],
      ['src/components/orders/OrderCraftFields.tsx', '企业基础设置 → 算料口径'],
      ['src/components/production/UnpricedNotice.tsx', '企业基础设置 → 工序与部位单价'],
      ['src/lib/route-source.ts', '企业基础设置 → 工艺路线'],
      // ⚠️ 用料公式说明的**链接文案**在 #6825 之后**不再是多级导航链**（该域就在本页
      //    「企业基础设置」内，旧写法「工艺配置 → 算料配置」整条退场）⇒ 正控钉的是**域 label**
      ['src/lib/meters-formula-legend.ts', "linkLabel: '算料口径'"],
    ]
    for (const [rel, pointer] of NEW_POINTERS) {
      expect(readFileSync(join(ROOT, rel), 'utf-8'), `${rel} 应含新指针 ${pointer}`).toContain(pointer)
    }
  })

  it('🔴 注入式红证：把修前的旧指针塞回源码 ⇒ R12 当场命中（「不会红的断言 = 空断言」）', () => {
    // ⚠️ 注入必须**落在代码里的那一处**（不是注释）：这五个文件的「旧说法」在**注释**里也有
    //    （沿革注解），拿整份文件 `String.replace(old, bad)` 会先改到注释上 ⇒ 前半句仍是旧串时
    //    改出来的是**非法 TS**，解析器一崩 `candidateStrings` 就返回空 ⇒ 这条自证读成「注入不生效」
    //    （本包实测踩过）。所以靶子取**代码里唯一的那一处**，`bad` 写成同形但**仍是合法 TS** 的旧串。
    const INJECT: Array<[string, string, string]> = [
      ['src/app/register/page.tsx', '企业基础设置 → 工序与部位单价', '开通后请到「工艺配置 → 工序管理」手工维护工序与工艺路线'],
      ['src/components/orders/OrderCraftFields.tsx', '档位来自「企业基础设置 → 算料口径」', '档位来自「工艺配置 → 算料配置」'],
      ['src/components/production/UnpricedNotice.tsx', '去定价（企业基础设置 → 工序与部位单价）', '去定价（工艺配置 · 工序单价）'],
      ['src/lib/route-source.ts', '补救：到「企业基础设置 → 工艺路线」新建这条路线', '补救：到「工艺配置」页新建这条路线'],
      // ⚠️ #6825 之后该链接文案 = 域 label「算料口径」（不再是多级导航链）；注入的旧串是**更早那版**
      ['src/lib/meters-formula-legend.ts', "linkLabel: '算料口径'", "linkLabel: '工艺配置 → 算料配置'"],
    ]
    for (const [rel, old, bad] of INJECT) {
      const src = readFileSync(join(ROOT, rel), 'utf-8')
      expect(src.split(old).length - 1, `${rel} 的代码版旧指针应恰好出现一次（注入靶必须唯一）`).toBe(1)
      const corrupted = src.replace(old, bad)
      const hits = candidateStrings(corrupted, rel).filter((c) => removedPageNameHit(c.text) !== null)
      expect(hits.length, `${rel} 注入旧串后 R12 必须命中（命中 ${hits.length} 条）`).toBe(1)
      // 命中的候选里确实带着**已移除集合里的那个名**（`bad` 在 `linkLabel: '…'` 形态下抽出来的是**串内容**）
      const hitName = removedPageNameHit(hits[0].text)
      expect(deadPageNames(), `${rel} 命中的候选应含已移除页名，实得 ${hitName}`).toContain(hitName)
      // 反向对照：同一份源码**不注入**时 R12 命中 0（说明上面那条命中的确是注入带来的）
      expect(candidateStrings(src, rel).filter((c) => removedPageNameHit(c.text) !== null)).toEqual([])
    }
  })

  it('🔴 豁免台账只许缩短：三条具名豁免都必须**仍在命中**，且五个已修文件一个都不许进台账', () => {
    const { candidates } = findViolations(ROOT)
    const live = new Set(candidates.filter((c) => removedPageNameHit(c.text) !== null).map((c) => c.file))
    for (const entry of DEAD_PAGE_NAME_EXEMPT) {
      expect(existsSync(join(ROOT, entry)), `台账条目指向的文件不存在：${entry}`).toBe(true)
      expect(live.has(entry), `台账条目不再命中（只许缩短，请删掉）：${entry}`).toBe(true)
    }
    for (const rel of FIXED_FILES) {
      expect(DEAD_PAGE_NAME_EXEMPT, `${rel} 已修 ⇒ 不得进豁免台账`).not.toContain(rel)
    }
  })
})

describe('页面副标题要说清「这个功能是干什么的」（#6488 续，用户 2026-10-08 定的标准）', () => {
  const { subtitles, offenses } = findSubtitleOffenses(ROOT)
  const byRule = (id: string) => offenses.filter((o) => o.rule === id)

  it('普查面非空（抽不到页面头 ⇒ 判据在扫空气）', () => {
    expect(subtitles.length, '商家后台应有成批页面头').toBeGreaterThanOrEqual(15)
    expect(pageSubtitles(ROOT).length).toBe(subtitles.length)
  })

  it('副标题规则表不许被删空（四条一条都不许少；每条给得出可行动的出口）', () => {
    expect(SUBTITLE_RULES.map((r) => r.id)).toEqual(['S1', 'S2', 'S3', 'S4'])
    for (const rule of SUBTITLE_RULES) {
      expect(rule.name.length, `${rule.id} 缺名字`).toBeGreaterThan(1)
      expect(rule.出口.length, `${rule.id} 的出口必须写到「改成什么」`).toBeGreaterThan(10)
    }
  })

  for (const rule of SUBTITLE_RULES) {
    it(`[${rule.id}] ${rule.name} 没有出现在页面副标题里（未登记即红）`, () => {
      expect(
        byRule(rule.id).map((o) => `${o.where}【${o.title}】 ${o.text.slice(0, 120)}`),
        `${rule.name} —— 副标题要讲「这个功能干什么」，不是写实现（issue #6488）。\n出口：${rule.出口}\n`
          + '（确有必要请登记 scripts/user-copy-scan.mjs 的 SUBTITLE_EXEMPT —— 只许缩短。）',
      ).toEqual([])
    })
  }

  it('副标题豁免台账不空转（失效即红 ⇒ 逼着删干净）', () => {
    const live = new Set(subtitles.map((s) => `${s.file}:${s.line}`))
    const stale = SUBTITLE_EXEMPT.filter((e) => !live.has(e))
    expect(stale, 'SUBTITLE_EXEMPT 里有不再命中的条目：\n' + stale.join('\n')).toEqual([])
  })

  it('判别力自证：四条规则对坏形态判红、对好文案（用户点名的正例）不红', () => {
    const S = (id: string) => SUBTITLE_RULES.find((r) => r.id === id)!
    // 坏形态（都是本轮真实病灶的**逐字**形态）
    expect(S('S1').test('工序与计件单价 → 工艺路线 → 算料口径')).toBe(true)
    expect(S('S2').test('每一行 = 一次库存变动：变动前多少、变动后多少')).toBe(true)
    expect(S('S3').test('可按实物把在库批次（含 0.5 米级尾料）登记进来')).toBe(true)
    expect(S('S4').test('库存为什么从 X 变成 Y，逐行都能对上')).toBe(true)
    // 好文案：用户点名的正例 + 改写后的形态，一条都不许红（否则判据会逼人把好文案也改坏）
    for (const good of [
      '管理客户信息、标签和互动记录',
      '待派订单按料（商品 × 颜色 × 门幅）合并 —— 同料合并领料，减少接头损耗；加急单不参与合并，立即单独派单',
      '登记布料到货、过账后加库存 —— 过账前不改动库存，可以先核对再确认',
      '管理发货单：可按单号、订单号、客户检索，并补打纸质发货单',
    ]) {
      for (const rule of SUBTITLE_RULES) {
        expect(rule.test(good), `${rule.id} 把好文案判红了：${good}`).toBe(false)
      }
    }
  })
})

/**
 * 类级元守卫（#6588）：**只读的服务端状态不得做成「开关」徽标**摆给商家看。
 *
 * 病灶（实测 2026-10-09）：「智能派单」状态条把服务端缺省值 `poolingEnabled` 渲染成
 * 「合并派单开关 已开启/未开启」徽标 —— 它**不可点、没有出口、恒为「未开启」**，
 * 用户当场问「在哪开启？」。（研发模式 §31 P3「不摆内部标识」/ P4「只陈述事实与该做什么」同源。）
 *
 * 判据形态：**状态副词不得单独做成 `Badge` 的子节点** —— 状态要么挂在被控对象/动作上，
 * 要么由控件本体（toggle / 按钮）表达；一个孤立的「已开启 / 未开启」说不出「谁被开启了、
 * 我能做什么」。放行的形态：**动作结果徽标**（如「已派单」）与**真实 toggle**（`aria-label` 的开关）。
 *
 * 判据源 = 本文件（源码文本扫描；`Badge` 是本仓唯一的徽标组件）。
 * 红证：把 `frontend/admin-web/src/app/(dashboard)/production/pool/page.tsx` 里那对
 * `<Badge variant="default">未开启</Badge>` 放回去 ⇒ 本判据当场红。
 */
describe('只读状态不得做成「开关」徽标（#6588）', () => {
  const SCAN_DIRS = ['src/app', 'src/components']
  const STATE_WORD = '(已开启|未开启|已关闭|已启用|已停用)'
  /**
   * 两个命中形态（都是「状态词就是徽标的全部内容」）：
   * ① 字面量：`<Badge variant="default">未开启</Badge>`（#6588 的病灶形态）；
   * ② 条件表达式：`<Badge>{ok ? '已开启' : '已关闭'}</Badge>`。
   * 放行：徽标里还有**别的信息**（动作结果 / 单号 / 对象名）。
   */
  const STATE_ONLY_BADGE =
    new RegExp(`<Badge[^>]*>\\s*(?:${STATE_WORD}|\\{[^}]*['"]${STATE_WORD}['"])`)

  const files = ((): string[] => {
    const out: string[] = []
    const walk = (rel: string) => {
      for (const entry of readdirSync(join(ROOT, rel))) {
        const child = `${rel}/${entry}`
        if (statSync(join(ROOT, child)).isDirectory()) walk(child)
        else if (/\.tsx?$/.test(entry)) out.push(child)
      }
    }
    for (const dir of SCAN_DIRS) walk(dir)
    return out
  })()

  it('普查面非空（扫不到文件 ⇒ 本判据在扫空气，而不是"没问题"）', () => {
    expect(files.length).toBeGreaterThan(20)
  })

  it('源码里没有「孤立状态词」徽标（未登记即红）', () => {
    const hits = files.filter((f) => STATE_ONLY_BADGE.test(readFileSync(join(ROOT, f), 'utf-8')))
    expect(hits, `这些文件把只读状态做成了徽标（状态该由控件本体表达）:\n${hits.join('\n')}`).toEqual([])
  })

  it('判别力自证：坏形态判红、好形态（动作结果徽标 / 真实开关）不红', () => {
    expect(STATE_ONLY_BADGE.test('<Badge variant="default">未开启</Badge>')).toBe(true)
    expect(STATE_ONLY_BADGE.test("<Badge variant='success'>{ok ? '已开启' : '已关闭'}</Badge>")).toBe(true)
    expect(STATE_ONLY_BADGE.test('<Badge variant="warning">加急插队</Badge>')).toBe(false)
    expect(STATE_ONLY_BADGE.test('<Badge variant="success">已派单，加工单号 JG-1</Badge>')).toBe(false)
  })

  it('只改注释不红（对照读数）：散文里提到状态词不算上屏，徽标形态才有罪', () => {
    expect(STATE_ONLY_BADGE.test('// 旧形态「合并派单开关 未开启」已删')).toBe(false)
    expect(STATE_ONLY_BADGE.test("aria-label=\"启用智能每日经营简报开关\"")).toBe(false)
  })
})

// ══════════════════════════════════════════════════════════════════════════════
// 第二个用户可见面：**车间现场端 worker-h5**（issue #6738）
//
// 🔴 为什么挂到这一把尺子上、而不是新开一把：判据源（`RULES` / `candidateStrings` / `toCandidate`）
//    只有**这一份**；「内部/开发口径字样不得上屏」这条纪律对两端同口径（工人与商家都是用户）。
// 🔴 为什么这几条写在 admin-web 侧：worker-h5 是**零依赖**页面（`node --test` 直接跑 `.mjs`），
//    而本扫描器依赖 `typescript` 解析源码 ⇒ 只有这边跑得起来（worker-h5 侧只钉「接线已声明」+「台账为 0」，
//    见 frontend/worker-h5/tests/worker-h5-6738-login-tenant-code.test.mjs 的 ④）。
//
// 判红时怎么红：任一条命中 ⇒ 上面那条「零命中」把 `文件:行 + 原文` 逐条打出来；
// 台账加一条 ⇒ 「只许缩短」那一条红；扫描面被写坏（谓词短路 / 目录写错）⇒
// 「普查面非空」或「判别力自证」红（本包实测踩过这份假绿，见下）。
// ══════════════════════════════════════════════════════════════════════════════
describe('用户可见文案不得含内部词汇 · 车间现场端 worker-h5（#6738）', () => {
  const { files, candidates, offenders } = findWorkerH5Violations()

  it('普查面非空（扫不到文件 ⇒ 本判据在扫空气，而不是"没问题"）', () => {
    expect(files.length, 'worker-h5 的 src/** 应有成批 .mjs').toBeGreaterThanOrEqual(6)
    expect(candidates.length, '应抽出成批「会上屏」的候选文案').toBeGreaterThanOrEqual(80)
    for (const anchor of [
      'frontend/worker-h5/src/app.mjs',
      'frontend/worker-h5/src/machine.mjs',
      'frontend/worker-h5/src/api.mjs',
    ]) {
      expect(files, `扫描面必须含 ${anchor}`).toContain(anchor)
    }
  })

  it('🔴 零命中（命中即红，逐条点名 `文件:行 + 原文`）', () => {
    const lines = offenders.map((o) => `${o.file}:${o.line} [${o.rule}] ${o.text.slice(0, 110)}`)
    expect(lines, `车间现场端屏上出现了内部/开发口径字样:\n${lines.join('\n')}`).toEqual([])
  })

  it('🔴 豁免台账只许缩短：worker-h5 面当前必须**零豁免**（台账加一条 = 放宽一格）', () => {
    expect(WORKER_H5_EXEMPT, '基线实测 0 命中 ⇒ 台账必须是空数组').toEqual([])
  })

  it('判别力自证：这把尺子**真的会红**（谓词没被短路、面不是空的）', () => {
    // 🔴 本包实测踩过一次假绿：自写的探针把谓词写成 `rule.re`（规则表其实用 `rule.test`）
    //    ⇒ 每条规则被短路跳过 ⇒ 8 条真命中读成「0 命中」，看起来全绿。
    //    这条把「尺子活着」本身钉住（§18「空集比空集是恒等」的同族坑）。
    const r1 = RULES.find((r) => r.id === 'R1')
    expect(r1, 'R1（接口/协议细节）规则必须在').toBeTruthy()
    expect(r1!.test(toCandidate('服务端忙不过来，请过一会儿再按一次')), 'R1 必须判红「服务端」这类开发术语').toBe(true)
    expect(r1!.test(toCandidate('系统忙不过来，请过一会儿再按一次')), '换成用户视角的话必须不红').toBe(false)
    expect(WORKER_H5_ROOT.endsWith('worker-h5'), `扫描根必须指向车间现场端：${WORKER_H5_ROOT}`).toBe(true)
  })
})
