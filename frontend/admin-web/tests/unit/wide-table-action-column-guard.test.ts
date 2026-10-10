// case_ids: UI-086
// 类级元守卫（issue #6717）：**宽表的「操作」列不得落在默认视口外**。
//
// 病灶（真机实测 main `2adad8660`，两档视口 1440×980 / 1280×800）：
// `/orders` 表格宽 1835px、容器 `overflow-x-auto` 只有 1044px ⇒ 溢出 791px，
// 「操作」列表头 left = **1929**（视口右缘 2181）⇒ 商家必须横滚才能**够到行操作**；
// 同形态另有 `/inbound-orders`（1280 下操作列 1317 出屏）、`/production`（1368 出屏）。
// `/processing-orders` 只是 `redirect('/production')`，不单独成页。
//
// 为什么是**类级**而不是只钉 `/orders`：`/orders` 那一处是 6 列里的 1 列，**形态**是
// 「宽表把主操作推到右端 + 容器只负责横向滚动、从不冻结任何列」——本仓四张主表 `sticky` 命中数
// 曾一度为 **0**。表单页/新列表页复制粘贴就会再长出一张同样的表 ⇒ 判据必须是**普查**，
// 与 `frontend/admin-web/tests/unit/list-table-nowrap-guard.test.ts`（UI-086，表格 nowrap 那一族）同范式。
//
// ## 判据（静态、可机械判）
// 凡**表头里含「操作」列**的表格，其「操作」列表头必须满足**二者之一**：
//   ① 标注 `sticky` + `right-0`（≠行首的那一列，右缘冻结；`left-0` 不算 —— 那冻的是左端）；
//   ② 落在**前 3 列**内（右移后仍在窄容器可视区，无需冻结）。
// 否则 ⇒ 红。（现状 = 4 页全部违反 ⇒ 全部登记进下面的冻结台账；本包修 3 页、留 1 页登记。）
//
// ## 🔴 边界（有意不做，如实登记 —— 别把这条读成「列可见性都守住了」）
//   · **「前 3 列」是静态近似**：`table-layout: auto` 下列宽随数据浮动，静态判不了「累积像素」。
//     真正的可见性/可点性由**效果层**判据逐像素守 ——
//     `tests/e2e/specs/orders/key-columns-reachability.spec.ts`（两档视口 × 逐按钮
//     `elementFromPoint(中心点) ∈ {自己, 自己内部节点}`）。
//   · **「状态」列前置这一半没有静态判据**：`after-sales`（9 列，状态在第 5 列）与
//     `inbound-orders`（9 列，状态在第 8 列）列数相同而可见性相反 ⇒ 「第几列」不是「可不可见」的
//     代理量，静态规则只会误红。故 **「状态列在视口外」只由上面的 E2E 逐像素判据守**，
//     本文件只守**操作列**这一半（冻结的、零误红的）。这条边界由下面的「判别力自证」钉住。
//   · 只扫 `src/app/(dashboard)/**` 的**页面**（`page.tsx` / 同目录同源组件）+ 共享列表件
//     `src/components/orders/OrderTable.tsx`。设置类弹窗里的 3~4 列小表（`processing-config/*`）
//     不在面内：它们的「操作」列在第 3 列、容器宽裕，不属「宽表主操作出屏」形态。
//
// ## 存量台账（`FROZEN_ACTION_OFFSCREEN`）：**双向相等 + 只许缩短**
//   现取违反集合必须**逐条登记**（新形态进不来），登记的条目必须**仍是违反**
//   （修好了必须删掉 —— 死条目即红）。条目 = `<仓库相对路径>::表[<表头…>]`（**不写行号**）。
//   冻结于 2026-10-11（issue #6717 修复前）：**4 条** ⇒ 本包修掉 3 页（orders / inbound-orders /
//   production）后应缩到 **1 条**（`shipments` —— 不在本包边界内，见下）。
//   `ACTION_OFFSCREEN_BASELINE` 是**冻结读数**：条数必须与台账数组长度**逐值相等**（不留松弛量）。
//
// ## 已知未覆盖（照实登记）
//   · `src/app/(dashboard)/shipments/page.tsx`（8 列，操作在第 8 列）当前**同样违反**本规则，
//     但不在 issue #6717 的边界（另一批并行包在动列表页面）⇒ 留作**冻结条目**并在此登记，
//     未在本包修复。它的存在**不会**让本判据变绿或变红（它就是台账里那 1 条）。
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'fs'
import { join, relative, sep } from 'path'

const SRC_DIR = join(process.cwd(), 'src')
/** 扫描根：`(dashboard)` 下的页面（含页面同目录的同源组件）+ 共享列表件目录。 */
const SCAN_DIRS = [join(SRC_DIR, 'app', '(dashboard)'), join(SRC_DIR, 'components', 'orders')]
/** 面外（有意）：设置类弹窗的小表 —— 它们的「操作」列本就在第 3 列、不是「宽表出屏」形态。 */
const OUT_OF_SCOPE = ['src/components/production-config/']

/** 冻结台账（只许缩短）：`<仓库相对路径>::表[<表头文本…>]`，**不含行号**。 */
const FROZEN_ACTION_OFFSCREEN: string[] = [
  // ⚠️ 这三条**不在 issue #6717 的边界内**（本包只改 orders / inbound-orders / production 三页），
  // 但同属「8~9 列表 + 操作列在末位」的形态 ⇒ 登记为冻结条目（**只许缩短**），
  // 由各自的包按同一改法收口（给操作列加 `sticky right-0`）后从下表删除并下调基线。
  //   · shipments：8 列。**归属已由集成侧裁定为「保留台账，不另派包」**（裁定 2026-10-11）：
  //     集成侧的布局普查在 `/shipments` 上量到「溢出 0、无出屏列」，但**该租户当时没有数据行**
  //     （空表）⇒ 有数据时的真实列宽量不到 ⇒ **既不能证实也不能证伪**本判据的命中。
  //     🔴 因此：本条目**只表示「静态形态命中」**，**不代表**「/shipments 有问题」也**不代表**它干净；
  //     待有数据行后复核（复核读数落 issue，见 #6717 的评论）。
  //   · after-sales：9 列；**本仓实测在 1440/1280 两档都干净**（操作按钮够得到）——
  //     但它的空态行 `colSpan={9}` 与数据行的**实际格数不一致**（数据行少一格）⇒ 静态判不了、
  //     留作观察项，不在本包改（边界：不在 #6717 面内）。
  //   · production/pool：7 列（其中一列是 3 列的小表同页）⇒ 无冻结列，登记观察。
  'src/app/(dashboard)/shipments/page.tsx::表[发货单号|订单号|客户|来源|发货人|发货时间|实发|操作]',
  'src/app/(dashboard)/after-sales/page.tsx::表[工单号|关联订单|客户|售后类型|状态|优先级|创建时间|更新时间|操作]',
  'src/app/(dashboard)/production/pool/page.tsx::表[单号|物料（商品 × 颜色 × 门幅）|需求米数|等待时长|加急标记|到货日|操作]',
]
/** 冻结读数：台账条数（**只许缩短**；修好一处必须同时下调本数字）。 */
const ACTION_OFFSCREEN_BASELINE = 3

/**
 * 存量台账·规则 ①b（冻结格背景不透明）：**当前为空**（归零基线）。
 *
 * 为什么现在可以是空的：`bg-inherit` 是 #6717 引入的**新**写法，只出现在本次修的 3 处，
 * 本包一次性收口 ⇒ 现取集合应为空。留这个数组（而不是直接断言 `[]`）= 让「确需豁免」的
 * 条目有**显式登记**的地方（未登记即红；登记了也不许增加 `FROZEN_INHERIT_BG_BASELINE`）。
 */
const FROZEN_INHERIT_BG: string[] = []
const FROZEN_INHERIT_BG_BASELINE = 0

/** 前 N 列之内算「无需冻结也够得到」（N = 3：checkbox / 首列标识 / 次列）。 */
const FRONT_COLUMNS = 3

export interface ActionColumnFinding {
  /** 台账锚：`<相对路径>::表[表头1|表头2|…]` */
  key: string
  /** 「操作」列的下标（0 起） */
  actionIndex: number
  /** 该表头元素是否标注了「右缘冻结」（`sticky` ∧ `right-0`） */
  frozenRight: boolean
}

const stripTags = (s: string): string =>
  s
    .replace(/<[^>]*>/g, '')
    .replace(/\{[^{}]*\}/g, '~')
    .replace(/\s+/g, ' ')
    .trim()

/**
 * 元素的 class 文本。三种写法都认：
 *   `class="…"` / `className="…"` / `className={cn('…', x ? '…' : '…')}`。
 *
 * ⚠️ issue #6729 实测踩过：只认带引号的写法时，`className={cn('sticky right-0 …', checked ? 'bg-primary-50' : 'bg-white')}`
 * 会解析成**空串** ⇒ 判据把「明明声明了不透明底色」的格子判红（**假红**，比漏判更坏：会逼人乱改）。
 * 花括号写法取整个 `{…}` 里的全部字符串字面量（条件类的两个分支都算「用过」——
 * 判据只问「有没有声明不透明背景」，不判哪个分支此刻生效）。
 */
function classOf(tag: string): string {
  const quoted = /\bclass(?:Name)?\s*=\s*"([^"]*)"/.exec(tag) ?? /\bclass(?:Name)?\s*=\s*'([^']*)'/.exec(tag)
  if (quoted) return quoted[1]
  // 花括号写法可能**换行**（prettier 会把长 className 折成多行）⇒ 贪婪吃到行尾/标签尾，
  // 并优先保留**最后一个** `{…}`（属性值本身），避免把条件表达式外层当成属性值
  const braced = /\bclass(?:Name)?\s*=\s*\{([\s\S]*)\}\s*\/?>/.exec(tag)
  if (!braced) return ''
  return Array.from(braced[1].matchAll(/'([^']*)'|"([^"]*)"/g))
    .map((m) => m[1] ?? m[2] ?? '')
    .join(' ')
}

/**
 * 规则本体（**纯函数，不含文件 IO** ⇒ 内存可注入取证）。
 *
 * 只收**表头里含「操作」**的表格；抽出每个 `<th>` 的**整体开标签**（`[^>]*` 足够，
 * 因为 `className="…"` 里不带 `>`）与表头文本，判「操作」列是否满足 ①右缘冻结 或 ②前 3 列。
 */
export function scanActionColumns(relPath: string, source: string): ActionColumnFinding[] {
  const out: ActionColumnFinding[] = []
  const seen = new Map<string, number>()
  const tableOpen = /<table\b[^>]*>/g
  let m: RegExpExecArray | null
  while ((m = tableOpen.exec(source)) !== null) {
    const close = source.indexOf('</table>', m.index)
    const body = source.slice(m.index + m[0].length, close === -1 ? source.length : close)
    const ths = Array.from(body.matchAll(/<th\b[^>]*>([\s\S]*?)<\/th>/g))
    if (ths.length === 0) continue
    const headers = ths.map((t) => stripTags(t[1]) || '~')
    const actionIndex = headers.indexOf('操作')
    if (actionIndex < 0) continue
    const frozenRight = /sticky/.test(classOf(ths[actionIndex][0])) && /right-0/.test(classOf(ths[actionIndex][0]))
    if (frozenRight || actionIndex < FRONT_COLUMNS) continue
    const base = `${relPath}::表[${headers.join('|')}]`
    const n = (seen.get(base) ?? 0) + 1
    seen.set(base, n)
    out.push({ key: n === 1 ? base : `${base}#${n}`, actionIndex, frozenRight })
  }
  return out
}

// ── issue #6729：**冻结列在任何交互态下有效背景必须不透明**（覆盖层那一半的判据） ──
//
// 病灶（#6717 的回归）：`sticky right-0` 的「操作」格写 `bg-inherit`，继承的是 `<tr>` 的背景，
// 而**选中态的行背景本身就是半透明**（`bg-primary-50/40` = `rgba(238,242,248,0.4)`）
// ⇒ 继承到的也半透明 ⇒ 横滚时下层列的内容（姓名/电话/地址）**穿透**进冻结列
// （真机 `getComputedStyle` 读数 alpha=0.4 + 读图双重实证）。
//
// 判据：冻结列的数据格**必须自己声明一个不透明的背景类**；`bg-inherit` **一律判红**
// —— 它是「把不透明性外包给祖先」的形态，而祖先（`<tr>`）的底色可以（且确实）是半透明的。
//
// 🔴 为什么静态只认白名单里的类：Tailwind 的 `bg-primary-50/40` 这类**透明度后缀**在类名里，
// 但 `bg-white` / `bg-primary-50` 是不是不透明只有调色板知道。白名单 = 已知不透明的调色板值；
// 换用别的既有不透明色（如 `bg-neutral-50`）⇒ 加进白名单即可（`KNOWN_OPAQUE_BG`）；
// 新写一个**不在白名单**的背景类 ⇒ 判红并具名报出 —— 这是 **fail-closed**（宁可让作者显式登记，
// 也不放一个可能半透明的背景进去）。
const KNOWN_OPAQUE_BG = new Set([
  'bg-white',
  'bg-neutral-50',
  'bg-neutral-100',
  'bg-slate-50',
  'bg-primary-50-lit',
  'bg-primary-50',
  'bg-primary-100',
])

/** 该 class 文本里有没有「确实不透明」的背景类。 */
function hasOpaqueBackground(classText: string): boolean {
  const tokens = classText.split(/\s+/).filter(Boolean)
  if (tokens.some((t) => KNOWN_OPAQUE_BG.has(t))) return true
  // 任意值写法：`bg-[#faf7f2]` / `bg-[rgb(250,247,242)]` —— **只接受不带透明度通道**的形态。
  // `bg-[#faf7f2]/40`、`rgba(...)`、`color-mix(...)` 一律不放行（它们可能是半透明的）。
  return tokens.some(
    (t) =>
      /^bg-\[(#[0-9a-fA-F]{3}|#[0-9a-fA-F]{6}|#[0-9a-fA-F]{8}|rgb\(\s*\d+\s*[,\s]+\d+\s*[,\s]+\d+\s*\)|white)\]$/.test(t) &&
      !/#[0-9a-fA-F]{8}/.test(t),
  )
}

export interface FrozenCellFinding {
  /** 台账锚：`<相对路径>::冻结格[<表头…>]` */
  key: string
  /** 违规的单元格个数（缺失 / 半透明背景） */
  badCells: number
  /** 命中的形态说明（给判红信息用） */
  reasons: string[]
}

/**
 * 规则本体·之二（**纯函数**）：扫一份源码里**所有 `sticky` 单元格**的 `className`，
 * 要求每个都自己声明**不透明**背景。
 *
 * 纯函数（内存可注入取证）。`bg-inherit` 与「一个背景类都没有」都判红：
 * 前者把不透明性外包给祖先（祖先可能半透明），后者直接透明。
 */
export function scanFrozenCellOpacity(relPath: string, source: string): FrozenCellFinding[] {
  const out: FrozenCellFinding[] = []
  const seen = new Map<string, number>()
  const tableOpen = /<table\b[^>]*>/g
  let m: RegExpExecArray | null
  while ((m = tableOpen.exec(source)) !== null) {
    const close = source.indexOf('</table>', m.index)
    const body = source.slice(m.index + m[0].length, close === -1 ? source.length : close)
    const headers = Array.from(body.matchAll(/<th\b[^>]*>([\s\S]*?)<\/th>/g)).map((t) => stripTags(t[1]) || '~')
    // 表头里的「冻结」列（本仓约定：合并成一行写法）
    const thFindings = Array.from(body.matchAll(/<th\b([\s\S]*?)\/?>/g)).filter(
      (t) => /sticky/.test(t[1]) && /right-0/.test(t[1]),
    )
    // 单元格：sticky 的 `td`（className 可能是 "…" 或 {cn('…', …)}）
    const tdFindings = Array.from(body.matchAll(/<td\b([\s\S]*?)(?:\/>|>)/g)).filter((t) =>
      /sticky/.test(t[1]),
    )
    if (thFindings.length === 0 && tdFindings.length === 0) continue
    const reasons: string[] = []
    let bad = 0
    for (const t of thFindings) {
      const cls = classOf(`<th${t[1]}>`)
      if (!hasOpaqueBackground(cls)) {
        bad += 1
        reasons.push(`th 背景不透明性未声明：className=${JSON.stringify(cls)}`)
      }
    }
    for (const t of tdFindings) {
      const cls = classOf(`<td${t[1]}>`)
      if (/bg-inherit/.test(cls)) {
        bad += 1
        reasons.push(`td 用 bg-inherit 把不透明性外包给祖先（祖先可能是半透明的选中行）：className=${JSON.stringify(cls)}`)
      } else if (!hasOpaqueBackground(cls)) {
        bad += 1
        reasons.push(`td 未声明不透明背景类：className=${JSON.stringify(cls)}`)
      }
    }
    if (bad === 0) continue
    const base = `${relPath}::冻结格[${headers.join('|')}]`
    const n = (seen.get(base) ?? 0) + 1
    seen.set(base, n)
    out.push({ key: n === 1 ? base : `${base}#${n}`, badCells: bad, reasons })
  }
  return out
}

function walk(dir: string): string[] {
  const files: string[] = []
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) files.push(...walk(full))
    else if (name.endsWith('.tsx')) files.push(full)
  }
  return files
}

const rel = (full: string) => relative(process.cwd(), full).split(sep).join('/')
const CORPUS = SCAN_DIRS.flatMap((d) => walk(d))
  .map((full) => ({ path: rel(full), source: readFileSync(full, 'utf-8') }))
  .filter((f) => !OUT_OF_SCOPE.some((p) => f.path.startsWith(p)))
const OFFENDERS = CORPUS.flatMap((f) => scanActionColumns(f.path, f.source).map((t) => t.key)).sort()
const OPACITY_OFFENDERS = CORPUS.flatMap((f) => scanFrozenCellOpacity(f.path, f.source).map((t) => t.key)).sort()

describe('宽表「操作」列可达性守卫（issue #6717）', () => {
  it('普查面非空且覆盖已知对象（改名/搬走 ⇒ 本判据先红，而不是静默空跑）', () => {
    expect(CORPUS.length, '扫不到页面源码 ⇒ 判据在扫空气').toBeGreaterThanOrEqual(30)
    const tables = CORPUS.reduce((n, f) => n + (f.source.match(/<table\b/g)?.length ?? 0), 0)
    expect(tables, '扫不到表格 ⇒ 判据在扫空气').toBeGreaterThanOrEqual(10)
    // 已知对象必须在场：本单现场（订单列表的共享表格件）
    const orders = CORPUS.find((f) => f.path.endsWith('components/orders/OrderTable.tsx'))
    expect(orders?.path, '找不到共享表格件 OrderTable.tsx ⇒ 本判据的坐标系已漂移').toBe(
      'src/components/orders/OrderTable.tsx',
    )
    // 语料面自证：该表的**「操作」列必须真被扫到**（用原始计数，避免「修好了 ⇒ 计数 0 ⇒ 自毁」）
    const hasAction = /<th\b[^>]*>[\s\S]{0,400}?操作/.test(orders!.source)
    expect(hasAction, 'OrderTable 里数不到「操作」表头 ⇒ 扫描面已漂移（不是「没有缺陷」）').toBe(true)
  })

  it('① 含「操作」列的表格：该列必须右缘冻结（sticky + right-0）或落在前 3 列内', () => {
    const unexpected = OFFENDERS.filter((k) => !FROZEN_ACTION_OFFSCREEN.includes(k))
    expect(
      unexpected,
      '这些表格的「操作」列既没有 `sticky right-0`、也不在前 3 列内 ⇒ 窄视口下它落在容器右缘之外，'
        + '商家必须横向滚动才够得到行操作（issue #6717 的现场形态）：\n'
        + unexpected.join('\n')
        + '\n\n出口（按序）：① 给该列表头与每个数据格加 `sticky right-0`（表头 `z-20 bg-*`、'
        + '数据格 `z-10` + 不透明背景/`bg-inherit`，行背景要随状态变时把背景类挂在 `<tr>` 上）；'
        + '② 或把「操作」列前移到前 3 列；③ 确属「宽表豁免」的登记进 FROZEN_ACTION_OFFSCREEN'
        + '（只许缩短，并同步下调 ACTION_OFFSCREEN_BASELINE）。\n'
        + `现取集合（供登记）= ${JSON.stringify(OFFENDERS)}`,
    ).toEqual([])
  })

  it('①b 冻结列（sticky）单元格必须自己声明**不透明**背景（issue #6729：选中态不许半透明）', () => {
    const unexpected = OPACITY_OFFENDERS.filter((k) => !FROZEN_INHERIT_BG.includes(k))
    expect(
      unexpected,
      '这些 `sticky` 冻结单元格把不透明性外包给了祖先（`bg-inherit`）或根本没声明背景 ⇒ ' +
        '行底色一旦是半透明（如选中态 `bg-primary-50/40`），冻结列就会**透出**横向滚过的下层列内容：\n' +
        unexpected.join('\n') +
        '\n\n出口：给冻结格自己声明**不透明**背景（既有色如 `bg-white` / `bg-primary-50`），' +
        '或在 `KNOWN_OPAQUE_BG` 里登记你用的那个不透明色；**`bg-inherit` 一律不接受**（它继承的可能是半透明行色）。\n' +
        `现取集合（供登记）= ${JSON.stringify(OPACITY_OFFENDERS)}`,
    ).toEqual([])
  })

  it('② 台账不得腐坏：登记的条目必须仍是缺陷（双向相等）+ 只许缩短', () => {
    const dead = FROZEN_ACTION_OFFSCREEN.filter((k) => !OFFENDERS.includes(k))
    expect(
      dead,
      `这些台账条目已不是缺陷（操作列已冻结 / 已前移）⇒ 死条目，请从 FROZEN_ACTION_OFFSCREEN 删除：${dead.join('、')}`,
    ).toEqual([])
    expect(
      FROZEN_ACTION_OFFSCREEN.length,
      '台账只许缩短：修好一处必须同时下调 ACTION_OFFSCREEN_BASELINE（不留松弛量）',
    ).toBe(ACTION_OFFSCREEN_BASELINE)
    const deadInherit = FROZEN_INHERIT_BG.filter((k) => !OPACITY_OFFENDERS.includes(k))
    expect(deadInherit, `这些冻结格台账条目已不是缺陷 ⇒ 死条目，请从 FROZEN_INHERIT_BG 删除：${deadInherit.join('、')}`).toEqual([])
    expect(
      FROZEN_INHERIT_BG.length,
      '冻结格台账只许缩短：修好一处必须同时下调 FROZEN_INHERIT_BG_BASELINE（不留松弛量）',
    ).toBe(FROZEN_INHERIT_BG_BASELINE)
  })

  it('③ 判别力自证：内存注入的六种形态各自判定正确（不落盘）', () => {
    const table = (th: string[]) =>
      `<div className="overflow-x-auto"><table className="w-full"><thead><tr>${th.join('')}</tr></thead>`
      + '<tbody><tr><td>x</td></tr></tbody></table></div>'
    const plain = (t: string) => `<th className="px-3 py-2 whitespace-nowrap">${t}</th>`
    const frozen = (t: string) => `<th className="px-3 py-2 whitespace-nowrap sticky right-0 z-20 bg-white">${t}</th>`
    // ① 8 列、操作在末列、未冻结 ⇒ 缺陷（= 本单现场形态）
    expect(scanActionColumns('x.tsx', table(['单号', '客户', '状态', '金额', '备注', '日期', '来源', '操作'].map(plain)))).toHaveLength(1)
    // ② 同一张表，操作列冻结 ⇒ 绿
    const cols = ['单号', '客户', '状态', '金额', '备注', '日期', '来源'].map(plain).concat(frozen('操作'))
    expect(scanActionColumns('x.tsx', table(cols))).toEqual([])
    // ③ 操作列在前 3 列内 ⇒ 绿（无需冻结）
    expect(scanActionColumns('x.tsx', table([plain('操作'), plain('单号'), plain('状态')]))).toEqual([])
    // ③b 操作列正好是第 4 列（index 3）⇒ **仍红**：列数越多的表越靠右的累积宽度越大，
    //     静态判不了像素，只认「前 3 列」这个确定的下界（误红出口 = 登记台账）
    expect(
      scanActionColumns('x.tsx', table([plain('单号'), plain('客户'), plain('状态'), plain('操作')])),
    ).toHaveLength(1)
    // ④ 只有 `left-0`（冻的是左端，不是操作列所在的那一端）⇒ **仍红**（易混的假修）
    const leftFrozen = '<th className="px-3 py-2 whitespace-nowrap sticky left-0 z-20 bg-white">操作</th>'
    expect(scanActionColumns('x.tsx', table(['单号', '客户', '状态', '金额', '备注', '日期'].map(plain).concat(leftFrozen)))).toHaveLength(1)
    // ⑤ `sticky` 与 `right-0` 拆在两个类名里（非相邻）⇒ 仍算冻结（不能因为写法不同误红）
    const split = '<th className="sticky z-20 bg-white px-3 py-2 right-0">操作</th>'
    expect(scanActionColumns('x.tsx', table(['单号', '客户', '状态', '金额', '备注', '日期'].map(plain).concat(split)))).toEqual([])
    // ⑥ 不含「操作」列的表（如看板汇总表）⇒ 不在本规则面内（**有意**：没有行操作就没有这个形态）
    expect(scanActionColumns('x.tsx', table(['日期', '收入', '退款', '净额'].map(plain)))).toEqual([])
  })

  it('④ 判别力自证·冻结格不透明（issue #6729）：半透明形态在内存里必红', () => {
    const page = (cell: string, row = '<tr className="group">') =>
      `<div className="overflow-x-auto"><table className="w-full"><thead><tr>`
      + `<th className="px-3 whitespace-nowrap">单号</th>`
      + `<th className="sticky right-0 z-20 bg-white px-3 whitespace-nowrap">操作</th>`
      + `</tr></thead><tbody><tr>${row}<td className="px-3">A</td>${cell}</tr></tbody></table></div>`
    // ① 违规形态（= #6717 的写法）：`bg-inherit` ⇒ 必红
    expect(scanFrozenCellOpacity('x.tsx', page('<td className="sticky right-0 z-10 border-l bg-inherit px-3">查看</td>'))).toHaveLength(1)
    // ② 违规形态：一个背景类都没有（透明）⇒ 必红
    expect(scanFrozenCellOpacity('x.tsx', page('<td className="sticky right-0 z-10 px-3">查看</td>'))).toHaveLength(1)
    // ③ 修好的形态：自己声明不透明背景 ⇒ 绿
    expect(scanFrozenCellOpacity('x.tsx', page('<td className="sticky right-0 z-10 border-l bg-white px-3">查看</td>'))).toEqual([])
    // ④ 选中态取不透明等效色（本包用的 `bg-slate-50`）⇒ 也算绿（这是本包采用的修法）
    expect(scanFrozenCellOpacity('x.tsx', page('<td className="sticky right-0 z-10 border-l bg-slate-50 px-3">查看</td>'))).toEqual([])
    // ④b `bg-primary-50`（既有不透明色）同样算绿
    expect(scanFrozenCellOpacity('x.tsx', page('<td className="sticky right-0 z-10 border-l bg-primary-50 px-3">查看</td>'))).toEqual([])
    // ⑤ `cn(...)` 写法（条件类）⇒ 仍能被解析（本仓真实写法）
    expect(
      scanFrozenCellOpacity('x.tsx', page("<td className={cn('sticky right-0 z-10 border-l px-3', checked ? 'bg-slate-50' : 'bg-white')}>查看</td>")),
    ).toEqual([])
    // ⑤b 任意值写法的不透明色（如 `bg-[#faf7f2]`）⇒ 算绿（本仓 /inbound-orders 用的就是它）
    expect(
      scanFrozenCellOpacity('x.tsx', page('<td className="sticky right-0 z-10 border-l bg-[#faf7f2] px-3">查看</td>')),
    ).toEqual([])
    // ⑤c 任意值 + 透明度后缀 ⇒ **仍必红**（`/40` 不在 `]` 里，但 rgba/8 位 hex 要拦住）
    expect(
      scanFrozenCellOpacity('x.tsx', page('<td className="sticky right-0 z-10 border-l bg-[#faf7f2]/40 px-3">查看</td>')),
    ).toHaveLength(1)
    expect(
      scanFrozenCellOpacity('x.tsx', page('<td className="sticky right-0 z-10 border-l bg-[rgba(250,247,242,0.4)] px-3">查看</td>')),
    ).toHaveLength(1)
    // ⑥ 半透明后缀（`bg-primary-50/40`）**不是**白名单里的不透明色 ⇒ 必红（fail-closed）
    expect(
      scanFrozenCellOpacity('x.tsx', page('<td className="sticky right-0 z-10 border-l bg-primary-50/40 px-3">查看</td>')),
    ).toHaveLength(1)
    // ⑦ 反向对照：不带 sticky 的普通格（它由行底色负责）**不在本规则面内**
    expect(scanFrozenCellOpacity('x.tsx', page('<td className="px-3 bg-inherit">查看</td>'))).toEqual([])
  })
})
