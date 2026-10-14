// case_ids: BM-040
import * as fs from 'fs'
import * as path from 'path'

/**
 * 售卖方式展示名**同源守卫**（issue #6901 包 B，铁律 8「类级固化」）。
 *
 * ## 治的形态
 *
 * 加工单面要印「售卖方式」，而 `order_items.processing_info.sellingMethod` 落的是**内部键**
 * （`bulk_cut` / `full_roll`）。bmini 是**独立 npm 工程**（不许 import admin-web 的 TS）
 * ⇒ 只有两条路：① 复制一份映射（会漂的那一份）；② 把内部键直接摆上商家可见面
 * （`migao-dev-flow` §31 **P3「不摆内部标识」**，实测反面形态 = 料组标题原样渲染服务端
 * `materialKey`）。
 *
 * 本包选「复制 + **锁死**」：副本住在 `frontend/bmini-app/src/utils/selling-method.ts`，
 * **单一真值**在 `frontend/admin-web/src/types/index.ts` 的 `SellingMethodLabels`。
 * 下面这条判据把它变成「改一侧不改另一侧 ⇒ 必红」——这正是
 * `tests/unit_ci_workflows/test_craft_display_same_source.py` 对 `craft-display.ts` 的同一范式
 * （那份管**工艺规格标签**，本份管**售卖方式标签**，两者字段族不同、不重复覆盖）。
 *
 * ## 判据（红证 = 怎么让它单独变红）
 *
 * | # | 判据 | 红证 |
 * |---|---|---|
 * | 1 | 键值逐项相等（**两侧现取，不写死数字**） | 只改任一侧的键或文案 ⇒ 必红 |
 * | 2 | 两侧都真的解析出了条目（防「都空 ⇒ 相等」的假绿） | 把任一侧表清空 ⇒ 必红 |
 * | 3 | `sellingMethodLabel('bulk_cut')` 用展示名、未知键如实回显、空/非串 ⇒ `null` | 改成回显内部键 ⇒ 判据 1/3 红 |
 */
// 🔴 路径必须写成**单个相对字面量**（别把上跳三级再拼「frontend/...」两段拼起来）：
// `tests/unit_ci_workflows/test_local_gate_matrix.py` 的「触发面闭包」判据静态抽取**源码里的相对路径字面量**
// （**不区分注释** ⇒ 注释里也别写这类字面量，PR #6904 实测：注释里的字面量一样被抽到并被判红）。
// 拆成两段时它抽到的是「上跳三级」那一段、归一成仓根 ⇒ 既报不出真实输入、也说不清耦合对象。
// 写成下面这样，两个真实输入都会现形：bmini 自己那个在触发面内；admin-web 那个登记在
// tests/unit_ci_workflows/local_gate_matrix.json 的 trigger_face_uncovered_inputs
// （理由与既有 print-media.json 条目同款：bmini 是独立 npm 工程、不许 import admin-web 的 TS，
//  只读源码逐值比对 ⇒ 有意不纳入触发面，靠 admin-web 侧兜）。
const BIMINI_LABELS = path.join(__dirname, '../src/utils/selling-method.ts')
const ADMIN_TYPES = path.join(__dirname, '../../admin-web/src/types/index.ts')

/** 取不到就抛（不是弱断言）。同款写法见 `frontend/bmini-app/tests/processing-order-detail-page.test.tsx` 的 `must()`。 */
function must<T>(value: T | null | undefined, what: string): T {
  if (value === null || value === undefined) {
    throw new Error(`取不到 ${what}（文件/写法漂了？）`)
  }
  return value
}

/**
 * 从 TypeScript 源码里取一份 `Record<string, string>` 字面量的**键值对**（保序）。
 *
 * 只吃本仓那两种写法（`export const X: Record<…> = { … }` / 类型别名后的对象字面量），
 * 键可带引号、值只认单双引号字符串 —— 取不到条目由判据 2 报红（不静默通过）。
 */
function recordEntries(src: string, name: string): Record<string, string> {
  const start = must(src.indexOf(name), `源码里的 ${name}`)
  const open = must(src.indexOf('{', start), `${name} 的对象字面量起点`)
  const close = must(src.indexOf('}', open), `${name} 的对象字面量终点`)
  const body = src.slice(open + 1, close)
  const out: Record<string, string> = {}
  for (const line of body.split('\n')) {
    const m = line.match(/^\s*['"]?([\w-]+)['"]?\s*:\s*['"]([^'"]*)['"]\s*,?\s*$/)
    if (m) out[m[1]] = m[2]
  }
  return out
}

describe('售卖方式展示名同源（issue #6901 包 B · 类级固化）', () => {
  it('判据 1+2：bmini 副本与 admin-web 单一真值**逐项键值相等**，且两侧都非空', () => {
    const bmini = recordEntries(fs.readFileSync(BIMINI_LABELS, 'utf8'), 'SELLING_METHOD_LABELS')
    const admin = recordEntries(fs.readFileSync(ADMIN_TYPES, 'utf8'), 'SellingMethodLabels')
    // 反空跑：两侧都真的解析出了条目（都空 = 相等 ⇒ 假绿）
    expect(Object.keys(bmini).length).toBeGreaterThan(0)
    expect(Object.keys(admin).length).toBeGreaterThan(0)
    expect(bmini).toEqual(admin)
  })

  it('判据 3：登记键 ⇒ 展示名；未知键 ⇒ 如实回显；空 / 非串 / 缺值 ⇒ null（不渲染）', () => {
    const { sellingMethodLabel } = require('../src/utils/selling-method')

    expect(sellingMethodLabel('bulk_cut')).toBe('散剪')
    expect(sellingMethodLabel('full_roll')).toBe('整卷')
    // 未登记键如实回显（与 ProcessingOrderBlock 同口径：至少可核对，不吞成空）
    expect(sellingMethodLabel('mystery_mode')).toBe('mystery_mode')
    // 空 / 非串 / 缺值 ⇒ null（调用方据此**不渲染那一行**）
    expect(sellingMethodLabel('')).toBeNull()
    expect(sellingMethodLabel('   ')).toBeNull()
    expect(sellingMethodLabel(null)).toBeNull()
    expect(sellingMethodLabel(undefined)).toBeNull()
    expect(sellingMethodLabel(3)).toBeNull()
  })
})
