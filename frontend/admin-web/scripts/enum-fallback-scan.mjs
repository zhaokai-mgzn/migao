/**
 * 「表达式兜底」扫描器（issue #6668 盲区①）—— **纯函数**，与同名 vitest 共用一个判定本体。
 *
 * ## 病灶
 *
 * `user-copy-jargon-guard.test.ts`（UI-093）扫**源码字面量**；`jsx-machine-key-guard.test.ts`
 * （UI-094）扫**文本位的纯成员链**。两者的交集之外有一整族形态**两张网都扫不到**：
 *
 * ```tsx
 * <td>{KIND_LABEL[row.pieceKind] ?? row.pieceKind}</td>   // 枚举一未命中 ⇒ 机器码上屏
 * <td>{LABELS[x] || x}</td>                               // 同上（`||` 形态）
 * <div>{orderNoById[r.orderRef] ?? r.orderRef}</div>      // 标识兜底 ⇒ 内部号上屏
 * ```
 *
 * 它们**既不是字面量**（左半边是变量），**也不是纯成员链**（整个表达式是二元运算）
 * ⇒ 正好落在两张网中间。本扫描器把这一族补上：**兜底值 = 原始值**（不是人话）即命中。
 *
 * ## 判什么（形态，不看语义）
 *
 * 面 = **二元表达式**，运算符 ∈ {`||`, `??`}，左侧是**查表**、右侧是**裸值兜底**：
 * - 左侧：`X[...]`（元素访问）或 `X.LABELS`（属性名以 `LABELS/Labels/Names/Texts` 结尾）；
 * - 右侧：**标识符 / 成员链**（`x` / `a.b` / `a?.b`）—— 即「查不到就把原值印出来」；
 * - 右侧是**字面量**（`'其他'` / `'—'` / `[]` / `{}` / `null`）或**同一个根的另一项**
 *   （`LABELS[x] || LABELS.other`，样式/缺省兜底）⇒ **不判**。
 *
 * ## 分类：**台账说了算**（不靠启发式猜）
 *
 * 扫描器把命中标成 `RISK`（可能上屏），把「不判面」交给**唯一真值** = 台账
 * `enum-fallback-ledger.json` 的 `benign` 条目（每条必须逐字写出理由）。
 * ⇒ 新增一处兜底 ⇒ **未登记即红**（`EF-unregistered`），逼着当下的作者做处置决定：
 * 要么换成 `displayEnum` 的人话兜底（首选），要么**逐条**登记它为什么不会把机器值印上屏。
 * 台账 `RISK` 条目只许缩短（不再命中 ⇒ 删掉，不留僵尸豁免）。
 *
 * ## 边界（照实登记，§19.1）
 *
 * - 只认**源码文本形态**：`if (!L[x]) y = x` / 三元 `L[x] ? L[x] : x` **不在面内**
 *   （换写法可绕过 —— **有意**的射程限制，不是"已覆盖"）；
 * - **判不了「这个值此刻是不是人话」**：命中 ≠ 必有线上缺陷；它是一份**必须被处置**的清单
 *   （处置 = 改人话兜底，或证明兜底值可控并降格 `benign`）；
 * - 不改业务语义、不改任何门禁的通过条件。
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative, sep } from 'node:path'

/** 扫描面（与既有两条上屏类守卫同口径：只扫前端源码） */
export const SCOPE = 'src'

const SKIP_DIRS = new Set(['node_modules', '.next', 'dist', 'coverage', '__pycache__'])

/**
 * 机器键指纹（**与 `frontend/admin-web/tests/unit/jsx-machine-key-guard.test.ts`（UI-094）
 * 的 `MACHINE_KEY_RULES` 同口径**；不 import 是因为跨 `.mjs` → `.ts` 的运行时导入不可移植）。
 * 差异一处：本条额外收 `*Ref`（`orderRef` 这类内部引用键，实测在 `production/pool` 上屏）。
 */
export const MACHINE_KEY = /(?:^|\.)[a-z][A-Za-z0-9]*(?:Key|Uuid|Hash|Token|Ref)$|(?:^|\.)(?:hash|token|uuid|orderRef)$/

/** 属性访问形态的左侧：属性名得像一张"标签表" */
export const LABEL_MAP_SUFFIX = /(?:Labels?|Names?|Texts?|LABELS|NAMES|TEXTS)$/

/** 右侧「标识符 / 成员链」——即"把原值印出来"的形态 */
export const RAW_VALUE = /^[A-Za-z_$][\w$]*(?:[?!]?\.[A-Za-z_$][\w$]*)*$/

/** 右侧「人话/缺省」形态：字面量、模板串、数组、对象、null/布尔/数字 —— 一律不判 */
export const HUMAN_OR_SENTINEL = /^(['"`]|\[|\{|true$|false$|null$|undefined$|NaN$|-?\d)/

/**
 * 语料层面的**排除面**（逐条给理由；不是"眼不见为净"）：
 * - `开放域名清单` 一类**默认值兜底**（`visibleDomains[0] ?? PARAM_DOMAINS`）：右侧是**前端自建常量数组**，
 *   不是服务端枚举值 ⇒ 不可能把机器值印上屏；
 * - `NAMED_ENTITIES[lower] ?? whole`（HTML 实体表）：兜底值是**原文本身**，那是内容不是标识。
 */
export const EXCLUDED_ROOTS = /visibleDomains|NAMED_ENTITIES/

/**
 * @typedef {object} FallbackSite
 * @property {string} file 本包内相对路径（`/` 分隔）
 * @property {number} line 行号（归因用；**不要**写进文档引用，见 §16.7 引用纪律）
 * @property {string} expr 表达式文本（逐字，便于 `grep`）
 * @property {'RISK'|'BENIGN'} kind `RISK` = 兜底值可能上屏；`BENIGN` 由台账改写（扫描器自己不猜）
 * @property {string} rule 命中规则 id（具名报红用）
 */

const RE =
  /([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*(\[\s*[^\]]{1,80}?\]|\.[A-Za-z_$][\w$]*)\s*(\|\||\?\?)\s*([A-Za-z_$][\w$]*(?:[?!]?\.[A-Za-z_$][\w$]*)*)/g

/**
 * 从一份源码里抽出所有「查表 + 裸值兜底」表达式（纯函数：不做文件 IO、不做分类决策）。
 *
 * 用**去注释后的正则**而非 `typescript` AST：本判据只在**表达式文本**上判定，
 * 而这族形态固定（`X[…]` + `||`/`??` + 裸值）、不需要作用域信息 ⇒ 引 AST 只会把
 * 「扫描面自证」变复杂（同族先例：`frontend/admin-web/scripts/user-copy-scan.mjs`）。
 */
export function findFallbackSites(source, file = '<memory>') {
  /** @type {FallbackSite[]} */
  const out = []
  const stripped = source
    .replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ' ')) // 块注释 → 保留行号
    .replace(/^\s*\/\/.*$/gm, '') // 行注释
  const lines = stripped.split('\n')
  for (const m of stripped.matchAll(RE)) {
    const [expr, lhs, accessor, , right] = m
    if (!accessor.startsWith('[') && !LABEL_MAP_SUFFIX.test(accessor.slice(1))) continue
    if (!RAW_VALUE.test(right) || HUMAN_OR_SENTINEL.test(right)) continue
    // 右侧带调用/多余点（`categories.find` 一类：正则贪到了下一个成员）⇒ 不是"裸值兜底"
    if (/\(/.test(expr) || / as /.test(expr)) continue
    // 正则可能在「裸值」后面**贪到下一个成员**（`categories.find`）：此时右侧/左侧以 `.` 收尾
    // ⇒ 真正的右侧是那个前缀（`categories`），那既不是原值也不是裸值兜底 ⇒ 不判。
    if (/\.$/.test(right) || /\.$/.test(lhs)) continue
    // 右侧紧跟 `(` ⇒ 它是**调用**（`categories.find(…)`）而不是裸值兜底
    if (stripped[(m.index ?? 0) + expr.length] === '(') continue
    if (EXCLUDED_ROOTS.test(lhs) || EXCLUDED_ROOTS.test(right)) continue
    // 右侧与左侧同根 ⇒ `LABELS[x] || LABELS.other`（样式/缺省兜底，不是"原值"）
    if (right.split(/[.?]/)[0] === lhs.split('.')[0]) continue
    const line = stripped.slice(0, m.index ?? 0).split('\n').length
    const inJsx = lines[line - 1]?.includes('>') ?? false
    out.push({
      file,
      line,
      expr: expr.trim(),
      kind: 'RISK',
      rule: MACHINE_KEY.test(`.${right}`) ? 'EF-machine-key-value' : inJsx ? 'EF-jsx-raw-value' : 'EF-row-raw-value',
    })
  }
  return out
}

/** 走一遍扫描面，返回全部命中（排序稳定 ⇒ 读数可复算） */
export function scanFallbackSites(root) {
  /** @type {string[]} */
  const files = []
  /** @type {FallbackSite[]} */
  const sites = []
  /** @param {string} dir */
  const walk = (dir) => {
    for (const name of readdirSync(dir).sort()) {
      if (SKIP_DIRS.has(name)) continue
      const full = join(dir, name)
      if (statSync(full).isDirectory()) walk(full)
      else if (/\.(ts|tsx)$/.test(name) && !/\.(test|spec)\.(ts|tsx)$/.test(name)) {
        const rel = relative(root, full).split(sep).join('/')
        files.push(rel)
        sites.push(...findFallbackSites(readFileSync(full, 'utf-8'), rel))
      }
    }
  }
  walk(join(root, SCOPE))
  return { files, sites }
}
