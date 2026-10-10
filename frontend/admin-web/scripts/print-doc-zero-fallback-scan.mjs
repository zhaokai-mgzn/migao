// case_ids: UI-040, UI-053
/**
 * 「**纸面**不得把『未知』印成 0」判据**单一源**（issue #6720）。
 *
 * ## 病灶（issue #6720 = #6667 移出后无人收口的悬空尾巴）
 *
 * `frontend/admin-web/src/components/orders/ShipmentDoc.tsx`（**客户拿到手的凭证**）：
 * `(amount ?? 0).toLocaleString(...)` / `String(qty ?? 0)` —— 缺值在纸面上印成 `0.00` / `0`。
 * 同文件**自己**就写着同族的判断（加工费一段）：「『本来就不收加工费』与『算不出来』长得一样，
 * 属**静默改钱的外观**」；同族的既有范式也已在仓内：`SalesDoc` 的 `SALES_DOC_MISSING = '—'`、
 * `ProcessingDoc` 的 `MISSING = '—'`、发货单自己的「发货人缺 ⇒ `-`」。
 *
 * **可达性**（不是纸面洁癖）：后端 `OrderDetailResponse.OrderItemResponse.amount` = 行
 * `unitPrice × quantity`，两者都为 null 时回落 `subtotal`；而全局 Jackson
 * `default-property-inclusion: non_null` ⇒ 为 null 的键在响应里**整个缺席**
 * ⇒ 前端拿到的是 `undefined`（见 `backend/admin-api/src/main/resources/application.yml` 与
 * `backend/admin-api/src/main/java/com/migao/admin/service/OrderService.java` 的
 * `convertToItemResponse`）。**故「缺值」是真形态**。
 *
 * ## 本文件是什么（与 `derived-zero-fallback-scan.mjs` **不互为副本**）
 *
 * 同族的两份守卫各自管**一个面**，两表不互重判：
 * | 守卫 | 面 | 判的形态 |
 * |---|---|---|
 * | `scripts/derived-zero-fallback-scan.mjs`（issue #6701） | 工作台 `/dashboard` | 屏上金额 / 计数展示位 |
 * | `scripts/read-failure-copy-attribution-scan.mjs`（issue #6702） | 读失败面 | 失败被归因成别的原因 |
 * | **本文件** | **打印单据族**（`SCOPE`） | **纸面**（客户凭证）上的数值回退成 0 |
 * 边界逐字：`SCOPE` 只含四份**印数值**的纸面单据；`/dashboard`、读失败面、其余文件族
 * **不属本台账**（那几处由上面两份守卫各自登记，本文件有意不跨界归因）。
 *
 * ## 判据（`printDocZeroFillSites`，**命令行与本测试共用，不写第二份规则**）
 *
 * 命中 ⇐ **去注释后的源码**里出现「`?? 0` / `|| 0` 直接落进一个把值印成可读数字的形态」：
 *   ① 格式化补位 `(x ?? 0).toLocaleString(...)` / `(x || 0).toFixed(...)`；
 *   ② 字符串化补位 `String(x ?? 0)`（→ 纸面印 `0`）；
 *   ③ 数值化补位 `Number(x ?? 0)`（→ 再经金额格式化进纸面）；
 *   ④ 一行内出现补位且带**格式化函数名**（`toLocaleString` / `toFixed` / `formatAmount` /
 *      `formatQty` / `formatMoney` / `formatYuan` / `lineSubtotal`）—— 覆盖
 *      「`formatAmount(item.amount ?? 0)`」这种没有 `).` 的写法（**Q3 的注入红证**）。
 *
 * 🔴 **有意不判**（实测区分过，别把它们当漏网）：
 *   - **算术中性元**：累加器 `sum + (it.processingFee || 0)`（中和 `undefined` 的加法）、
 *     `(item.subtotal || 0) + (item.processingFee || 0)`（同样是求和的中性元，
 *     且缺值语义由 `lineSubtotal` 的返回值承担 —— 它现在返回 `null` 而不是 0）；
 *   - **非纸面射程**：屏上组件 / 取数页 / 状态聚合；
 *   - **注释与文档字符串**里的反例（本仓反复踩过「把注释里的反例读成代码」，§23.4 T2）
 *     —— 判据只看**去注释后的代码**。
 * ⚠️ 判据**有意宽松**（会漏）：经中间变量（`const v = item.amount ?? 0; … formatAmount(v)`）、
 * 跨行传递、三元回退（`x ? fmt(x) : '0.00'`）都判不出来 —— 那半边由**实例判据**承担
 * （各单据测试里的「缺值不印 0」一组，真正渲染组件并读纸面文本）。
 *
 * ## 台账（`LEDGER`，**只许缩短**）
 *
 * 键 = `仓库相对路径::形态标签` —— 故意**不带行号**（一行新增就会把台账顶失效，本仓 #4668 的教训）。
 * 登记点**不再命中**（修好了）⇒ 守卫当场红，逼着同批删干净、不留僵尸豁免；
 * **现取**值 = 0（本单修完就该是 0）—— 将来若真有不可修形态，登记时必须写明理由与**死亡条件**
 * （同族范式 = `frontend/admin-web/tests/unit/lib/print-doc-paper.test.ts` 的
 * `SCOPE_TARGETS` 与 `scripts/enum-fallback-ledger.json` 的豁免口径）。
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

// 纸面判定的**口径常量与实例不变量**在 `src/lib/print-doc-paper.ts`（非测试模块 ⇒ 组件测试
// 可以直接 import，不必 import 一个 `*.test.ts`）—— 本文件只放**静态判据面**（SCOPE / 台账 / 形态）。

/** 仓库相对路径（判据面：**印数值的纸面单据**）；新增单据必须同步登记，否则守卫的「未登记即红」判据发不出声 */
export const SCOPE = [
  'src/components/orders/ShipmentDoc.tsx',
  'src/components/orders/QuotationDoc.tsx',
  'src/components/orders/SalesDoc.tsx',
  'src/components/orders/ProcessingDoc.tsx',
  // 洗水码（production/TaskCardPrint.tsx）：**当前不印任何金额 / 数量**（纸面只有文字与短码）
  // ⇒ 它对本形态**天然免疫**，登记在此是为了让「它一开印数值就有人管」：
  // 死亡条件 = 它一旦出现金额 / 数量格式化，登记行的 scope_note 与测试里的静态判据**同时**红。
  'src/components/production/TaskCardPrint.tsx',
]

/** 本单修完以后，现取值应当是这个（有豁免时必须另立条目并写明死亡条件） */
export const LEDGER = []

/** 「把值印成可读数字」的形态（命中即「坏值会被印上纸面」） */
export const PRINT_FILL_PATTERNS = [
  {
    label: '格式化补位',
    re: /(?:\?\?|\|\|)\s*0\s*\)\s*\.\s*(?:toLocaleString|toFixed)\b/g,
  },
  {
    label: '字符串化补位',
    re: /String\(\s*[\w$.\[\]'"?]+\s*(?:\?\?|\|\|)\s*0\s*\)/g,
  },
  {
    label: '数值化补位',
    re: /Number\(\s*[\w$.\[\]'"?]+\s*(?:\?\?|\|\|)\s*0\s*\)/g,
  },
  {
    // 格式化函数实参补位：`formatAmount(item.amount ?? 0)` —— 没有 `).` 的那种写法。
    // `(?<!\.)` 排除方法调用（`(amount ?? 0).toLocaleString(…)` 已由形态 ① 覆盖；
    // 不排掉会让同一次命中被记成两条 = 台账键重复）。
    label: '格式化函数实参补位',
    re: /(?<!\.)\b(?:formatAmount|formatQty|formatMoney|formatYuan|lineSubtotal|toLocaleString|toFixed)\([^)]*(?:\?\?|\|\|)\s*0\s*\)/g,
  },
]

/**
 * 剥掉 `//` 与 `/* *\/` 注释（**字符串字面量内的不剥**，含模板串）。
 *
 * 判据不得把注释里的反例（本仓的文件头都在解释「旧写法为什么错」）判成违规 —— 那是假红，
 * 会逼人删掉解释性注释（同族实现：`tests/unit_ci_workflows/test_print_doc_convention_guard.py`）。
 */
export function stripTsComments(src) {
  let out = ''
  let i = 0
  const n = src.length
  let quote = null
  while (i < n) {
    const ch = src[i]
    if (quote !== null) {
      out += ch
      if (ch === '\\' && i + 1 < n) {
        out += src[i + 1]
        i += 2
        continue
      }
      if (ch === quote) quote = null
      i += 1
      continue
    }
    if (ch === '"' || ch === "'" || ch === '`') {
      quote = ch
      out += ch
      i += 1
      continue
    }
    if (ch === '/' && i + 1 < n && src[i + 1] === '/') {
      while (i < n && src[i] !== '\n') i += 1
      continue
    }
    if (ch === '/' && i + 1 < n && src[i + 1] === '*') {
      i += 2
      while (i + 1 < n && !(src[i] === '*' && src[i + 1] === '/')) i += 1
      i += 2
      continue
    }
    out += ch
    i += 1
  }
  return out
}

/** 命中判定（**纯函数**，便于内存注入红证；`file` 只进键） */
export function printDocZeroFillSitesFromSource(source, { file = 'probe.tsx' } = {}) {
  const code = stripTsComments(source)
  const sites = []
  for (const { label, re } of PRINT_FILL_PATTERNS) {
    re.lastIndex = 0
    for (const hit of code.matchAll(re)) {
      sites.push({
        key: `${file}::${label}`,
        file,
        label,
        text: hit[0],
        line: code.slice(0, hit.index).split('\n').length,
      })
    }
  }
  return sites
}

/** 现取：按 `SCOPE` 读文件并跑判据（文件不存在 ⇒ 抛错，**不得**静默跳过） */
export function printDocZeroFillSites(root = process.cwd()) {
  const sites = []
  for (const rel of SCOPE) {
    const src = readFileSync(join(root, rel), 'utf-8')
    sites.push(...printDocZeroFillSitesFromSource(src, { file: rel }))
  }
  return sites
}

/**
 * **实例不变量**（各单据测试调用；`presence` = 该单据测试里被注入的「缺值」形态）。
 *
 * 判据本身 = 纸面文本里不许出现 `0.00` / `0` —— 这就是「未知不得印成 0」的机器读数；
 * 目标单据按 `SCOPE_TARGETS` 从**纸面 DOM** 反查注入形态，缺值 ⇒ 报出缺少的**单据标识**
 * （未登记即红：新单据的测试不调这条不变量，谁都发现不了）。
 */
export const SCOPE_TARGETS = [
  { label: '发货单 ShipmentDoc', file: 'tests/unit/components/ShipmentDoc.test.tsx' },
  { label: '报价单 QuotationDoc', file: 'tests/unit/components/QuotationDoc.test.tsx' },
  { label: '销售单 SalesDoc', file: 'tests/unit/components/SalesDoc.test.tsx' },
  { label: '加工单 ProcessingDoc', file: 'tests/unit/components/ProcessingDoc.test.tsx' },
  { label: '任务卡 TaskCardPrint', file: 'tests/unit/components/TaskCardPrint.test.tsx' },
]
