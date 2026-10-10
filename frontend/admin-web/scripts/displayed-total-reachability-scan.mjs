#!/usr/bin/env node
// case_ids: UI-057
/**
 * 「屏上显示了 total ⇒ 该集合必须可达」判据**单一源**（issue #6697）。
 *
 * ## 为什么要有它
 *
 * `/production/remnants` 修前逐字 `remnantApi.ledger({ status, page: 1, size: 100 })`，
 * 而屏上照旧渲染服务端给的 `page.total`（租户 25 实测 332）⇒ **232 条（70%）无任何可达路径**，
 * 且「共 332 块」让商家以为能数到全部 —— **界面承诺与可达集合不一致**
 * （与本批「读失败伪装成空态」同族：界面说的事情与事实不符，而商家据此做决定）。
 * 只把这一页接上分页 = 没修：下一个列表页可以把 `page: 1, size: 100` 原样写回来，
 * **而没有任何东西会变红**（这才是本文件存在的理由）。
 *
 * ## 判的是哪个形态（口径）
 *
 * 扫描面（`SCOPE`）= `src/app/(dashboard)/production` —— 本缺陷所在**族**（生产域页面，
 * 文件所有权相邻）。一个 `.tsx` 页面**算候选** ⇐ 命中下面任一形态：
 *
 * - **A 形态**：把**分页信封**的 total 交给屏上渲染 —— `page?.total` / `data?.total` /
 *   `result?.total` / `res…?.total` / `…page.total`（含三元的 `cond ? a.total : b.total`）。
 *   屏上承诺了一个总数，商家就会按它去数；
 * - **B 形态**：**请求里钉死** `page: 1` **且** `size: 100`（同一行）—— 本单的逐字形态：
 *   只拉前 100 条，第 101 条起**结构性不可达**（`roles` / `orders/new` 两处即此形态）；
 * - **C 形态**：屏上写了「共 … 条 / 条记录」**且**同一行引用了 `.total`（集合计数上屏）。
 *
 * 🔴 **有意不判**（实测的假红面，逐条给理由 —— 不许凭感觉加）：
 * - **进度计数**（`p.total` 与 `p.done` 并列，如 `production/page.tsx` 的 `x/y`）：
 *   它是**分子分母**，不是「屏上有多少条等着你看」，且该页**已接**共享分页；
 * - **服务端对象字段**（`board?.total` 是 `{savedMeters, savedAmount}` 对象、`report?.total` 是金额）：
 *   名字叫 total 但**不是集合条数**，判定为不可达没有意义。
 *   判据形态上靠「`.total` 不在 `page/data/result/res` 信封上」把它们排除。
 *
 * 候选必须**同时**满足「引入并用上了共享 `Pagination`」（`<Pagination` 出现），否则：
 * - 在 `LEDGER` 里 ⇒ 记为**已登记缺口**（未修，逐条给理由；本单只放同形态观察项）；
 * - 不在 `LEDGER` 里 ⇒ 判红（**未登记即红**）。
 *
 * ## 出口
 *
 * 复用 `frontend/admin-web/src/components/ui/Pagination.tsx`（`customers` / `after-sales` /
 * `knowledge` / `production` / `finance` / `notifications` 六页已在用），
 * 把 `page` / `size` 放进 state、翻页**真发请求**；参考实现 =
 * `frontend/admin-web/src/app/(dashboard)/production/remnants/page.tsx`。
 *
 * ## 边界（照实登记，`migao-dev-flow` §19.1）
 *
 * - **扫描面只有 `production/**`，不声明全站覆盖**：`(dashboard)` 下还有 `roles` / `orders/new`
 *   两处 B 形态（本单**只登记不修**，见 `LEDGER`）。把它们并进来需要先给该租户真实条数证明会超 100
 *   （issue #6697 正文的口径），属另一个包。
 * - 只认**源码文本形态**：注释里的同形态会被剥离（`stripLineComments`），但**多行 JSX**
 *   （`共` 与 `.total` 不在同一行）会漏判 —— 与 `Pagination` 锚同因，属可接受漏判；
 *   **自造分页控件**（不引共享组件）同样漏判：那是「不只简化实现」的另一族，不在本条射程。
 * - 只读：命令行跑只打印，本文件不写任何文件。
 */
import { readdirSync, statSync, readFileSync } from 'node:fs'
import { join, relative } from 'node:path'

/** 判据面：生产域页面（本缺陷所在族） */
export const SCOPE = 'src/app/(dashboard)/production'
const SKIP_DIRS = new Set(['node_modules', '.next', 'dist', 'coverage'])

/** A 形态：**分页信封**上的 total 被交给屏上渲染 */
const ENVELOPE_TOTAL_RE = /(page|data|result|res)\s*\??\s*\.\s*total(?!s)/
/** C 形态：屏上写「共 … 条 / 条记录」且同一行引用 `.total` */
const DISPLAYED_COUNT_LINE_RE = /共|条记录/
const ANY_TOTAL_RE = /\??\s*\.\s*total(?!s)/
/** B 形态：请求里钉死 `page: 1` + `size: 100`（同一行） */
const PINNED_FIRST_PAGE_RE = /page:\s*1\s*,[^)]*size:\s*100|size:\s*100\s*,[^)]*page:\s*1/
/** 「接上了共享分页组件」的锚（引入 + 使用） */
const SHARED_PAGINATION_RE = /<Pagination\b/

/**
 * 台账（**只许缩短**）：已登记缺口 —— 命中判据但**本单不修**的条目，逐条给理由。
 * 新增任何条目都会让守卫的「台账只许缩短」判据红 ⇒ 必须先在 PR body 说明为什么。
 * 条目形态 = `<仓库相对全路径>::<形态>（理由）`（**不写行号**：活跃文件的裸行号几分钟就失效）。
 */
export const LEDGER = [
  'src/app/(dashboard)/roles/page.tsx::B（page:1,size:100；岗位数通常远小于 100，未实测到可见危害 —— 只登记不修，issue #6697 正文口径）',
  'src/app/(dashboard)/orders/new/page.tsx::B（page:1,size:100；加工项目录选择器，>100 项会静默截断选不到第 101 个 —— 只登记不修，issue #6697 正文口径）',
]

/**
 * 台账条数**冻结基线**（只许缩短；守卫里与 `LEDGER.length` 比对）。
 * ⚠️ 上面两条都在**扫描面外**（`roles` / `orders/new` 不属 `production/**`）⇒ 机器核不了它们，
 * 只由条数上界 + PR 评审兜底（如实登记，见「边界」）。
 */
export const LEDGER_FLOOR = 2

/** 只剥行注释（`//` 在 `http://` 上不误伤） */
function stripLineComments(code) {
  return code
    .split('\n')
    .map((l) => l.replace(/(^|[^:])\/\/.*$/, '$1'))
    .join('\n')
}

/** 递归收集 `SCOPE` 下的全部 `.tsx`（含子目录） */
export function listPageFiles(repoRoot) {
  const out = []
  const walk = (dir) => {
    for (const name of readdirSync(dir).sort()) {
      const abs = join(dir, name)
      if (statSync(abs).isDirectory()) {
        if (!SKIP_DIRS.has(name)) walk(abs)
      } else if (name.endsWith('.tsx')) {
        out.push(relative(repoRoot, abs).split('\\').join('/'))
      }
    }
  }
  walk(join(repoRoot, SCOPE))
  return out
}

/**
 * 单文件判据（纯函数：守卫的判别力自证直接喂文本进来）。
 * 返回 `null`（不是候选）或 `{ file, forms, hasPagination }`。
 */
export function classify(file, source) {
  const lines = stripLineComments(source).split('\n')
  const code = lines.join('\n')
  const forms = []
  if (ENVELOPE_TOTAL_RE.test(code)) forms.push('A')
  if (PINNED_FIRST_PAGE_RE.test(code)) forms.push('B')
  if (lines.some((l) => DISPLAYED_COUNT_LINE_RE.test(l) && ANY_TOTAL_RE.test(l))) forms.push('C')
  if (forms.length === 0) return null
  return { file, forms, hasPagination: SHARED_PAGINATION_RE.test(code) }
}

/** 解析台账条目 ⇒ `{ file, form }` */
export function parseLedgerEntry(entry) {
  const [file, rest = ''] = entry.split('::')
  const m = rest.match(/^([ABC])/)
  return { file, form: m ? m[1] : null }
}

/** 该文件是否落在本次扫描面内（面外条目无从核对，见「边界」） */
export function inScope(file) {
  return file.startsWith(`${SCOPE}/`)
}

/**
 * 全仓扫描 ⇒ `{ candidates, offenders, unregistered, staleLedger }`：
 * - `offenders` = 命中 ∧ **没接**共享分页（必须全部在台账里，否则 `unregistered` 非空）；
 * - `unregistered` = 命中 ∧ 没接共享分页 ∧ **未登记** ⇒ 判红面；
 * - `staleLedger` = **面内**台账条目里**不再命中**、或**形态已变**的（僵尸豁免 / 过期理由）；
 *   ⚠️ **面外**条目（`roles` / `orders/new`）无从核对 ⇒ 不参与本条（如实登记为边界）。
 */
export function scan(repoRoot, ledger = LEDGER) {
  const candidates = []
  for (const file of listPageFiles(repoRoot)) {
    const hit = classify(file, readFileSync(join(repoRoot, file), 'utf8'))
    if (hit) candidates.push(hit)
  }
  const offenders = candidates.filter((c) => !c.hasPagination)
  const entries = ledger.map(parseLedgerEntry)
  const unregistered = offenders.filter((c) => !entries.some((e) => e.file === c.file))
  const staleLedger = entries.filter(
    (e) =>
      inScope(e.file) && !candidates.some((c) => c.file === e.file && e.form && c.forms.includes(e.form)),
  )
  return { candidates, offenders, unregistered, staleLedger }
}
