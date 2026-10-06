// case_ids: UI-086
// 类级元守卫（issue #6398）：**页面/组件里的表格与手写药丸不得被压成竖排**。
//
// 病灶（与 UI-056「按钮标签竖排」**同一机制**，只是落在表格上）：`<table className="w-full">`
// 把宽度钉死在容器宽度上，而 `th` / `td` 没有 `whitespace-nowrap` ⇒ 列可以一直被压到
// **CJK min-content = 一个汉字**（`行数 / 总数量` 甚至在 `/` 处断行）⇒ 表头折行、状态药丸
// 「已过账」竖排成两行。用户实测（2026-10-06）：「状态样式展示不对，列的样式也有问题，要平铺开」。
//
// 为什么是元守卫而不是只钉入库单页：本仓 2026-09 已有同族先例（UI-041 开关缺 shrink-0 /
// UI-056 按钮缺 nowrap）。「可收缩容器里的中文文本缺几何保护」是一**类**，发现规则是**机械的**，
// 新表格/新药丸漏了即红，不靠人记得登记。
//
// 两条规则（判据本体 = 下面的 `scanTables` / `scanPills`，纯函数，可内存注入取证）：
//   ① 表格（**有表头**的表格，即 `<th>` 在面内）：每个 `<th>` 必须带 `whitespace-nowrap`，
//      且表格必须落在 `overflow-x-auto` / `overflow-auto` 横向逃逸口里（**两条缺一不可**：只有逃逸口
//      ⇒ 列照旧被压扁；只有 nowrap 而没有逃逸口 ⇒ 表格溢出被 `overflow-hidden` **裁切**，是更难发现的假绿）；
//      🔴 **边界（有意，且被下面的自证钉住）**：本规则**只裁 `<th>`，不裁 `<td>`** —— 「单元格能不能折行」
//      取决于**数据与列语义**（长文本列本就该折行，`src/components/ui/Table.tsx` 的原语也只给表头 nowrap）
//      ⇒ 静态判不了。单元格那一半由**效果层**守：`tests/e2e/specs/warehouse/inbound-orders-table-geometry.spec.ts`
//      逐单元格断言「单行」（真实浏览器 + 真实几何）。
//   ② 手写药丸（`inline-flex` ∧ `rounded-full` ∧ `border`，`src/components/ui/**` 除外 ——
//      共享原语面由 UI-056 守）：必须带 `whitespace-nowrap`，否则它在 flex/表格单元格里
//      可收缩，min-content = 一个汉字 ⇒ 「已过账」竖排。
//
// 存量台账（`FROZEN_TABLES` / `FROZEN_PILLS`）：**双向相等 + 只许缩短** —— 现取集合必须逐条登记
// （新缺陷进不来），登记的条目必须仍是缺陷（修好了必须从台账里删掉，死条目即红）。
// 台账条目 = `<仓库相对路径>::<锚>`（锚 = 表头文本 / 归一化后的源码行，**不写行号** —— 行号会漂）。
//
// 效果层几何由 `tests/e2e/specs/warehouse/inbound-orders-table-geometry.spec.ts`（Playwright，UI-086）
// 守；本判据守的是**每一次 PR**（admin-web 单测面）就能拦住的那一层。
//
// 已知不覆盖（照实登记，边界）：
//   · 打印/单据类表格用 `<td>` 当表头 ⇒ 不在规则 ① 面内（有意：那些表格是固定版式的分页单据）；
//   · 单元内**短文本**（如「合计」）不折行也不会红 —— 本规则判的是**有没有几何保护**，不是「此刻有没有折行」；
//   · 同一行源码里 `border` 属于另一个元素时，规则 ② 可能误报（无跨元素解析）⇒ 出口 = 登记台账。
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'fs'
import { join, relative, sep } from 'path'

const SRC_DIR = join(process.cwd(), 'src')
const UI_PRIMITIVE_DIR = join(SRC_DIR, 'components', 'ui')

/**
 * 存量台账·规则 ①（表格）：**只许缩短** —— 与现取缺陷集合**双向相等**（新缺陷进不来 /
 * 修好了必须删掉死条目），且基线是**冻结读数**（`FROZEN_TABLES.length === TABLE_BASELINE`：
 * 修好一处必须同时下调基线，不许留松弛量）。
 *
 * 冻结于 2026-10-06（issue #6398）：**改前** 26 条 → 本包修掉入库单列表那一处后 **25**
 * （这条 26 → 25 是**实测**出来的：修复落地而不改台账时，本判据在「台账不得腐坏」这一条上
 *  **具名**报红，报的就是被修好的那一张表）。
 */
const FROZEN_TABLES: string[] = [
  'src/app/(dashboard)/dashboard/page.tsx::表[#|商品|成交量|环比]',
  'src/app/(dashboard)/finance/page.tsx::表[支付方式|收入|退款|净额]',
  'src/app/(dashboard)/finance/page.tsx::表[日期|收入|退款|净额]',
  'src/app/(dashboard)/inbound-orders/new/page.tsx::表[货号 / 颜色 / 门幅|数量*|单价(元)|缸号|旧系统批次号|卷长(米)|批次号|~]',
  'src/app/(dashboard)/inbound-orders/page.tsx::表[行号|货号|剩余米数|缸号|旧系统批次号|校验结果]',
  'src/app/(dashboard)/inbound-orders/page.tsx::表[货号 / 颜色 / 门幅|数量|单价|金额|批次号|缸号|卷长(米)|旧系统批次号]',
  'src/app/(dashboard)/production/page.tsx::表[加工单号|订单号|客户|商品与数量|状态|工序进度|计件合计|操作]',
  'src/app/(dashboard)/production/piecework/page.tsx::表[~|计件数量|金额]',
  'src/app/(dashboard)/production/piecework/page.tsx::表[工人|计件数量|金额]',
  'src/app/(dashboard)/production/piecework/page.tsx::表[工序|计件数量|金额]',
  'src/app/(dashboard)/production/pool/page.tsx::表[单号|单号|物料（商品 × 颜色 × 门幅）|需求米数|等待时长|加急标记|到货日]',
  'src/app/(dashboard)/production/processing/page.tsx::表[选配组合|加工费单价|来源|操作]',
  'src/app/(dashboard)/production/routings/page.tsx::表[工序|单价|分组 · 单位 · 操作]',
  'src/app/(dashboard)/products/[id]/ProductDetail.tsx::表[颜色|门幅|货号|库存|价格]',
  'src/app/(dashboard)/products/page.tsx::表[行号|货号|原因]',
  'src/app/(dashboard)/shipments/page.tsx::表[发货单号|订单号|客户|来源|发货人|发货时间|实发|操作]',
  'src/components/dashboard/RecentOrders.tsx::表[订单号|客户|金额|状态|时间]',
  // ⚠️ 本条的锚里带 `~`（`{...}` 表达式被归一化成 `~`）：表头里嵌了受控复选框（跨行 JSX）⇒ 锚较长但仍是**稳定文本锚**。
  'src/components/orders/OrderTable.tsx::表[~} onChange=~ className="w-4 h-4 rounded border-neutral-300 text-primary-600 focus:ring-primary-500" />|订单ID|采购商品|采购明细 (名称:单价×数量+加工费)|累计金额(元)|实收款(元)|收货人信息|下单时间|制单人|状态|加急|到货日|备注|操作]',
  'src/components/production/CutPlanTable.tsx::表[套号|部位|组件 / 货号|用料（米）|裁多长（米） × 几片|备注]',
  'src/components/production/CuttingHeightConfigPanel.tsx::表[名称|取值（米）|触发|触发值|部位|启用|~]',
  'src/components/products/BatchStockPanel.tsx::表[批次号|货号|入库量|已消耗|余量|收货日期]',
  'src/components/products/BatchStockPanel.tsx::表[档位|批次数|占比]',
  'src/components/products/BatchStockPanel.tsx::表[货号|SKU 库存|批次余量|差额|已售扣减|已派工扣减|其它台账|台账外存量|恒等式]',
  'src/components/products/BatchStocktakeForm.tsx::表[批次号|货号|当前余量|实盘米数|差异]',
  'src/components/products/SkuMatrix.tsx::表[颜色分类|规格尺寸|*价格（元）|*库存（米）]',
]
const TABLE_BASELINE = 25

/**
 * 存量台账·规则 ②（手写药丸）：同上，冻结于 2026-10-06（issue #6398），**改前** 6 条 → **5**。
 */
const FROZEN_PILLS: string[] = [
  'src/app/(corporate)/page.tsx::<div className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/5 px-4 py-1.5 text-xs text-neutral-200 sm:text-sm">',
  'src/app/(corporate)/page.tsx::<span className="inline-flex items-center rounded-full border border-primary-200 bg-primary-50 px-3 py-1 align-middle text-sm font-bold text-primary-700">',
  'src/app/(dashboard)/after-sales/page.tsx::className="inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-800 transition-colors hover:bg-amber-100"',
  'src/components/chat/QuickActions.tsx::className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-white hover:bg-primary-50 border border-neutral-200 hover:border-primary-200 rounded-full text-xs text-neutral-600 hover:text-primary-600 transition-all shadow-sm disabled:opacity-40 disabled:cursor-not-allowed"',
  'src/components/orders/EditOrderContentModal.tsx::\'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs cursor-pointer\',',
]
const PILL_BASELINE = 5

const stripTags = (s: string): string =>
  s
    .replace(/<[^>]*>/g, '')
    .replace(/\{[^{}]*\}/g, '~')
    .replace(/\s+/g, ' ')
    .trim()

export interface TableFinding {
  /** 台账锚：`<相对路径>::表[表头1|表头2|…]`（表头文本，不含行号） */
  key: string
  /** 缺 `whitespace-nowrap` 的表头个数 */
  badHeaders: number
  /** 表格是否落在横向逃逸口里（`overflow-x-auto` / `overflow-auto`；看紧邻其前的 300 字符窗口） */
  hasScroll: boolean
}

/**
 * 规则 ①：扫描一份源码里的表格。纯函数（内存可注入），**不含**文件 IO。
 *
 * 只收**有 `<th>` 的表格**：打印/单据类表格用 `<td>` 当表头（实测 12 个），它们不在本规则面内。
 */
export function scanTables(relPath: string, source: string): TableFinding[] {
  const out: TableFinding[] = []
  const seen = new Map<string, number>()
  const tableOpen = /<table\b[^>]*>/g
  let m: RegExpExecArray | null
  while ((m = tableOpen.exec(source)) !== null) {
    const close = source.indexOf('</table>', m.index)
    const body = source.slice(m.index + m[0].length, close === -1 ? source.length : close)
    const thOpen = /<th\b[^>]*>/g
    const headers: RegExpExecArray[] = []
    let h: RegExpExecArray | null
    while ((h = thOpen.exec(body)) !== null) headers.push(h)
    if (headers.length === 0) continue
    const texts = headers.map((item) => {
      const after = body.slice(item.index + item[0].length)
      const thClose = after.indexOf('</th>')
      return stripTags(thClose === -1 ? '' : after.slice(0, thClose)) || '~'
    })
    const badHeaders = headers.filter((item) => !item[0].includes('whitespace-nowrap')).length
    const window = source.slice(Math.max(0, m.index - 300), m.index)
    const hasScroll = /(?:^|[\s"'])(?:overflow-x|overflow)-(?:auto|scroll)/.test(window)
    if (badHeaders === 0 && hasScroll) continue
    const base = `${relPath}::表[${texts.join('|')}]`
    const n = (seen.get(base) ?? 0) + 1
    seen.set(base, n)
    out.push({ key: n === 1 ? base : `${base}#${n}`, badHeaders, hasScroll })
  }
  return out
}

/** 规则 ②：扫描一份源码里的**手写药丸**（`inline-flex` ∧ `rounded-full` ∧ `border`，逐行判定）。 */
export function scanPills(relPath: string, source: string): string[] {
  const out: string[] = []
  for (const line of source.split('\n')) {
    if (!line.includes('inline-flex')) continue
    if (!line.includes('rounded-full')) continue
    if (!line.includes('border')) continue
    if (line.includes('whitespace-nowrap')) continue
    out.push(`${relPath}::${line.trim().replace(/\s+/g, ' ')}`)
  }
  return out
}

/** 语料面自证用：数一份源码里**有表头**的表格个数（与规则 ① 的判定口径同源，只用于「扫到了没有」）。 */
export function countHeaderTables(source: string): number {
  let n = 0
  const tableOpen = /<table\b[^>]*>/g
  let m: RegExpExecArray | null
  while ((m = tableOpen.exec(source)) !== null) {
    const close = source.indexOf('</table>', m.index)
    const body = source.slice(m.index + m[0].length, close === -1 ? source.length : close)
    if (/<th\b/.test(body)) n += 1
  }
  return n
}

function walkTsx(dir: string): string[] {
  const files: string[] = []
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) {
      if (full === UI_PRIMITIVE_DIR) continue
      files.push(...walkTsx(full))
    } else if (name.endsWith('.tsx')) {
      files.push(full)
    }
  }
  return files
}

const rel = (full: string) => relative(process.cwd(), full).split(sep).join('/')
const CORPUS = walkTsx(SRC_DIR).map((full) => ({ path: rel(full), source: readFileSync(full, 'utf-8') }))
const TABLE_COUNT = CORPUS.reduce((n, f) => n + (f.source.match(/<table\b/g)?.length ?? 0), 0)
const OFFENDERS = CORPUS.flatMap((f) => scanTables(f.path, f.source).map((t) => t.key)).sort()
const PILL_OFFENDERS = CORPUS.flatMap((f) => scanPills(f.path, f.source)).sort()

describe('列表页表格 / 药丸换行守卫（issue #6398）', () => {
  it('普查面非空且覆盖已知对象（改名/搬走 ⇒ 本判据先红，而不是静默空跑）', () => {
    expect(CORPUS.length, '扫不到页面源码 ⇒ 判据在扫空气').toBeGreaterThanOrEqual(40)
    expect(TABLE_COUNT, '扫不到表格 ⇒ 判据在扫空气').toBeGreaterThanOrEqual(30)
    // 已知对象必须在场：入库单列表（本次缺陷现场）
    const inbound = CORPUS.find((f) => f.path.endsWith('(dashboard)/inbound-orders/page.tsx'))
    expect(inbound?.path, '入库单列表页面找不到 ⇒ 本判据的坐标系已漂移').toBe(
      'src/app/(dashboard)/inbound-orders/page.tsx',
    )
    // 语料面自证：该页的表格必须**真被扫到**（扫描面漂了 / 计数口径坏了 ⇒ 这里先红，
    // 而不是「规则 ① 空跑通过」）。用**原始计数**而非缺陷计数 —— 避免「把这页修好 ⇒ 计数变 0 ⇒ 自红」的自毁形态。
    expect(
      countHeaderTables(inbound!.source),
      '入库单列表页面里数不到「有表头的表格」⇒ 本判据的扫描面已漂移（改前该页 3 张）',
    ).toBeGreaterThanOrEqual(1)
  })

  it('① 每个有表头的表格：th 全带 whitespace-nowrap 且表格在 overflow-x-auto 逃逸口里', () => {
    const unexpected = OFFENDERS.filter((k) => !FROZEN_TABLES.includes(k))
    expect(
      unexpected,
      '这些表格的 th 缺 whitespace-nowrap，或表格不在 overflow-x-auto 逃逸口里'
        + '（列会被压到 CJK min-content = 一个汉字 ⇒ 表头折行 / 药丸竖排；'
        + '单元格那一半由效果层几何 spec 守，见文件头边界）：\n'
        + unexpected.join('\n')
        + '\n\n出口：给每个 th 补 whitespace-nowrap，并把 <table> 包进 <div className="overflow-x-auto">；'
        + '确属固定版式（打印单据等）的登记进 FROZEN_TABLES。\n'
        + `现取集合（供登记）= ${JSON.stringify(OFFENDERS)}`,
    ).toEqual([])
  })

  it('② 每个手写药丸（inline-flex ∧ rounded-full ∧ border）都带 whitespace-nowrap', () => {
    const unexpected = PILL_OFFENDERS.filter((k) => !FROZEN_PILLS.includes(k))
    expect(
      unexpected,
      '这些手写药丸缺 whitespace-nowrap（min-content = 一个汉字 ⇒ 窄容器里标签竖排）：\n'
        + unexpected.join('\n')
        + '\n\n出口：优先**复用共享原语** `@/components/ui` 的 Badge（自带 nowrap，且在 UI-056 面内）；'
        + '否则就地补 whitespace-nowrap。\n'
        + `现取集合（供登记）= ${JSON.stringify(PILL_OFFENDERS)}`,
    ).toEqual([])
  })

  it('台账不得腐坏：登记的条目必须仍是缺陷（双向相等）+ 只许缩短', () => {
    const deadTables = FROZEN_TABLES.filter((k) => !OFFENDERS.includes(k))
    expect(
      deadTables,
      `这些台账条目已不是缺陷（修好了）⇒ 死条目，请从 FROZEN_TABLES 删除：${deadTables.join('、')}`,
    ).toEqual([])
    const deadPills = FROZEN_PILLS.filter((k) => !PILL_OFFENDERS.includes(k))
    expect(
      deadPills,
      `这些药丸台账条目已不是缺陷（修好了）⇒ 死条目，请从 FROZEN_PILLS 删除：${deadPills.join('、')}`,
    ).toEqual([])
    expect(FROZEN_TABLES.length, '表格台账只许缩短：修好一处必须同时下调基线（不留松弛量）').toBe(TABLE_BASELINE)
    expect(FROZEN_PILLS.length, '药丸台账只许缩短：修好一处必须同时下调基线（不留松弛量）').toBe(PILL_BASELINE)
  })

  it('判别力自证：内存注入的八种形态各自判定正确（不落盘）', () => {
    // `cell` 默认 = 已平铺单元格（nowrap）；传 `className="px-3"` 即造「半平铺」
    const tbl = (th: string, wrapper = '', cell = 'className="px-3 whitespace-nowrap"') =>
      `<div className="${wrapper}"><table className="w-full text-sm"><thead><tr>${th}</tr></thead>`
      + `<tbody><tr><td ${cell}>1 / 50</td></tr></tbody></table></div>`
    const badTh = '<th className="px-3 py-2.5">行数 / 总数量</th>'
    const goodTh = '<th className="px-3 py-2.5 whitespace-nowrap">行数 / 总数量</th>'
    // ① 无 nowrap + 无逃逸口 ⇒ 缺陷
    expect(scanTables('x.tsx', tbl(badTh))).toHaveLength(1)
    // ② 只加逃逸口、表头仍无 nowrap ⇒ **仍是缺陷**（逃逸口治不了列被压扁）
    expect(scanTables('x.tsx', tbl(badTh, 'overflow-x-auto'))).toHaveLength(1)
    // ③ 逃逸口 + th/td 都 nowrap ⇒ 绿
    expect(scanTables('x.tsx', tbl(goodTh, 'overflow-x-auto'))).toEqual([])
    // ④ 边界：`<td>` 当表头的单据表格不在面内
    expect(scanTables('x.tsx', '<table className="w-full"><tbody><tr><td>合计</td></tr></tbody></table>')).toEqual([])
    // ⑤ 手写药丸缺 nowrap ⇒ 缺陷；⑥ 补上 ⇒ 绿
    const pill = '<span className="inline-flex items-center rounded-full border px-2 py-0.5 text-xs">已过账</span>'
    expect(scanPills('x.tsx', pill)).toHaveLength(1)
    expect(scanPills('x.tsx', pill.replace('text-xs', 'text-xs whitespace-nowrap'))).toEqual([])
    // ⑦ **边界（有意，不是漏判）**：th 全 nowrap、td 未 nowrap ⇒ **本静态规则不红**
    //    （「单元格能不能折行」取决于数据与列语义 ⇒ 静态判不了；由效果层几何 spec 逐单元格守）。
    //    ⚠️ 若哪天把规则扩到 td，这一行会先红 —— 那时必须**显式**改这条边界并同步文件头。
    expect(scanTables('x.tsx', tbl(goodTh, 'overflow-x-auto', 'className="px-3"'))).toEqual([])
    // ⑧ 边界：`colSpan` 占位行（空态 / 分组行）不是「一列」⇒ 不参与
    expect(
      scanTables(
        'x.tsx',
        '<div className="overflow-x-auto"><table className="w-full"><thead><tr>'
          + '<th className="whitespace-nowrap">供应商</th></tr></thead><tbody><tr>'
          + '<td colSpan={9} className="py-10 text-center">暂无入库单</td></tr></tbody></table></div>',
      ),
    ).toEqual([])
    // ⑨ 逃逸口认 `overflow-auto`（本仓既有写法）—— 不能因为写法不同就误红
    expect(scanTables('x.tsx', tbl(goodTh, 'overflow-auto'))).toEqual([])
  })
})
