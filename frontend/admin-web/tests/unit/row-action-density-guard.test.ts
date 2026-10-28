// case_ids: UI-057, UI-058, UI-130
/**
 * 类级元守卫：**「操作」列一行同时可点 ≤ 2**（issue #8038，依据 #8035 审计）。
 *
 * ## 为什么是类级（而不是再来一页一测）
 *
 * #8011 已在 `/orders` 落了那句判据（`tests/unit/pages/orders-list-row-actions.test.tsx` 的
 * 「每行操作区可点元素 ≤ 2」），但它**只看一页** ⇒ 同一形态在 `products`（5 个）/ `knowledge`（4 个）/
 * `approvals` / `rework-orders` / `employees`（各 3 个）又长了一遍（#8035 审计：`≥3 个同级可点` 共 5 页）。
 * 本文件把那句判据抽成**扫描器 + 台账**，判据实现只有一份
 * （`frontend/admin-web/scripts/row-action-density-scan.mjs`），命令行与守卫共用。
 *
 * ## 判据（各自能单独变红）
 *
 * ① **未登记即红**：某「操作」列密度 > 2 且不在台账 ⇒ 红（具名文件 + 读数）；
 * ② **台账只许缩短**：条目数 > `frozen_count` ⇒ 红；条目**已不再是缺陷** ⇒ 僵尸红（逼着删）；
 * ③ **债务不许放大**：台账条目的当前密度 > 登记时 `frozen` ⇒ 红；
 * ④ **正向锚**：已收口的 `orders` / `products` / `knowledge` 必须逐字含 `<RowActions` ——
 *    「把整列删掉」也能让密度读成 0，这条堵掉那种假绿；
 * ⑤ **判别力自证**（本文件）：改前的**逐字坏形态**必红、改后形态不红、注释里的同形态不误伤、
 *    委托式动作面（`{renderActions(order)}`）会被跟随 —— 守卫自己退化成绿时先在这里红。
 *
 * ## 边界（照实登记，`migao-dev-flow` §19.1）
 *
 * - 静态判据：判不了菜单展开后的**落点 / 遮挡**（真机视觉，集成侧截图复核），也判不了运行时
 *   「收起态不进 DOM」（那是 `tests/unit/components/RowActions.test.tsx`）；
 * - 跨组件不可见：动作面渲染**别的文件**里的格子组件时计 0（有意不做跨文件调用图）；
 * - 同字段互斥分支语法上是平级条件 ⇒ 计 2（真实同行 1 个）：偏保守、**不会假绿**。
 */
import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  MAX_CLICKABLE_PER_ROW,
  PRIMITIVE,
  SCOPES,
  FIXED_SURFACES,
  actionSurfacesFromSource,
  grownLedger,
  loadLedger,
  missingFixedAnchors,
  offendersOf,
  rowActionSites,
  staleLedger,
} from '../../scripts/row-action-density-scan.mjs'

const ADMIN_WEB_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')

/**
 * 改前的**逐字**坏形态（`git show origin/main:frontend/admin-web/src/components/products/ProductTable.tsx`
 * 的 `:286-303` 区段）：在架行 5 个平级文字链、下架行 4 个 —— `products` 是审计里密度最高的一页。
 */
const PRE_FIX_PRODUCTS_COLUMN = `
const columns = [
  {
    key: 'actions',
    title: '操作',
    render: (record: Product) => (
      <div className="flex items-center gap-3 text-sm whitespace-nowrap">
        {record.status === 'on_sale' && (
          <>
            <button onClick={() => onView(record)}>查看</button>
            <button onClick={() => onEdit(record)}>编辑</button>
            <button onClick={() => onRecommend(record)}>推荐</button>
            <button onClick={() => onTakeOffShelf(record)}>下架</button>
            <button onClick={() => onDelete(record)}>删除</button>
          </>
        )}
      </div>
    ),
  },
]`

/** 改后形态（共享原语）：主行动走 children、其余进 items 数据（不产生平级可点元素） */
const POST_FIX_PRODUCTS_COLUMN = `
const columns = [
  {
    key: 'actions',
    title: '操作',
    render: (record: Product) => (
      <RowActions menuTestId={\`product-menu-\${record.id}\`} items={itemsFor(record)}>
        <Button variant="ghost" size="sm" onClick={() => onEdit(record)}>编辑</Button>
      </RowActions>
    ),
  },
]`

/** 改前 `knowledge` 形态：一个平级按钮 + `{canWrite && <>…3 个…</>}` = 4 */
const PRE_FIX_KNOWLEDGE_COLUMN = `
const columns = [
  {
    key: 'actions',
    title: '操作',
    render: (entry) => (
      <div className="flex items-center gap-1 whitespace-nowrap">
        <Button size="sm" variant="ghost" onClick={() => setViewTarget(entry)}>查看</Button>
        {canWrite && (
          <>
            <Button size="sm" variant="ghost" onClick={() => openEdit(entry)}>编辑</Button>
            <Button size="sm" variant="ghost" onClick={() => archiveCard(entry)}>归档</Button>
            <Button size="sm" variant="ghost" onClick={() => setDeleteTarget(entry)}>删除</Button>
          </>
        )}
      </div>
    ),
  },
]`

const density = (source: string) =>
  Math.max(0, ...actionSurfacesFromSource(source, { file: '<probe>.tsx' }).map((s) => s.density))

describe('类级守卫：「操作」列行内动作密度 ≤ 2（issue #8038）', () => {
  it('① 未登记即红：密度 > 2 且不在台账 ⇒ 无名额（台账之外一处都不许有）', () => {
    const { sites, offenders } = offendersOf(ADMIN_WEB_ROOT)

    // 语料面自证：该扫的文件族非空、且「操作」列真被扫到（否则判据是空跑）
    expect(SCOPES.length).toBeGreaterThan(0)
    expect(sites.length, '扫不到任何「操作」列 ⇒ 扫描面已漂移（不是「没有缺陷」）').toBeGreaterThanOrEqual(20)

    expect(
      offenders,
      `以下「操作」列一行同时可点 > ${MAX_CLICKABLE_PER_ROW} 且未登记台账 ⇒ 请改用共享原语 `
        + `\`<${PRIMITIVE}>\`（1 主行动 + ⋯ 菜单），或按「未登记即红」登记进 `
        + 'tests/unit/row-action-density-ledger.json：\n'
        + offenders.map((o) => `  · ${o.key} 密度 ${o.density}（面 ${o.surfaces}）`).join('\n'),
    ).toEqual([])
  })

  it('② 台账只许缩短：条数 ≤ frozen_count，且没有僵尸条目', () => {
    const ledger = loadLedger()
    expect(
      Object.keys(ledger.ledger).length,
      '台账只许缩短：修好一页就删一条，不许为了让扫描器变绿而加条目',
    ).toBeLessThanOrEqual(ledger.frozen_count)

    const stale = staleLedger(ADMIN_WEB_ROOT)
    expect(
      stale,
      `这些台账条目已不再是缺陷（密度 ≤ ${MAX_CLICKABLE_PER_ROW}）⇒ 僵尸条目，请从 `
        + `row-action-density-ledger.json 删除：${stale.join('、')}`,
    ).toEqual([])
  })

  it('③ 债务不许放大：台账条目当前密度不得高于登记时的 frozen 读数', () => {
    const grown = grownLedger(ADMIN_WEB_ROOT)
    expect(
      grown,
      '存量债的密度变高了（又往平级里加动作）⇒ 红：'
        + grown.map((g) => `${g.key} 冻结 ${g.frozen} → 现 ${g.now}`).join('、'),
    ).toEqual([])
  })

  it('④ 正向锚：已收口的五面（orders / products / knowledge / 工人档案 / 仓位面板）必须真用共享原语', () => {
    // 五面都在扫描面内（台账以外不许有僵尸面）
    const { sites } = rowActionSites(ADMIN_WEB_ROOT)
    const keys = new Set(sites.map((s) => s.key))
    for (const f of FIXED_SURFACES) {
      expect(keys.has(f.file), `${f.name}（${f.file}）没被扫到 ⇒ 扫描面漂移`).toBe(true)
    }
    expect(missingFixedAnchors(ADMIN_WEB_ROOT)).toEqual([])
  })

  it('⑤ 判别力自证：改前形态必红、改后形态不红、注释不误伤', () => {
    // 改前：5 个平级 → 5 > 2（= #8035 审计的现场读数）
    expect(density(PRE_FIX_PRODUCTS_COLUMN)).toBe(5)
    expect(density(PRE_FIX_PRODUCTS_COLUMN)).toBeGreaterThan(MAX_CLICKABLE_PER_ROW)

    // 改前 knowledge：1 个平级 + canWrite 分支里 3 个 = 4
    expect(density(PRE_FIX_KNOWLEDGE_COLUMN)).toBe(4)

    // 改后：主行动 1 + 原语内置触发器 1 = 2（恰好达标，不是 0 —— 0 说明扫描面没读到）
    expect(density(POST_FIX_PRODUCTS_COLUMN)).toBe(MAX_CLICKABLE_PER_ROW)

    // 反向对照：把整段注掉 ⇒ 扫不到动作面（这才是「删掉整列」的读数，靠 ④ 的正向锚兜住）
    expect(actionSurfacesFromSource(`// ${PRE_FIX_PRODUCTS_COLUMN.replace(/\n/g, '\n// ')}`)).toEqual([])

    // 注释里提到「操作」不算动作面（AST 只认真节点）
    expect(
      actionSurfacesFromSource('/** 这里以前是 title: \'操作\' 的 5 个按钮 */\nexport const x = 1'),
    ).toEqual([])
  })

  it('⑤ 判别力自证：条件分支取最大值（互斥不叠加）、委托式动作面会被跟随', () => {
    // `cond ? A : B` 互斥 ⇒ max(1, 2) = 2，不是 3
    expect(
      density(`
const columns = [{ key: 'actions', title: '操作', render: (r) =>
  <div>{r.ok ? <Button>查看</Button> : <><Button>编辑</Button><Button>删除</Button></>}</div> }]`),
    ).toBe(2)

    // 表体委托给本文件的渲染函数（`{renderActions(order)}`，= OrderTable 的形态）⇒ 必须跟随进去量，
    // 否则读成 0 = 假绿（这是 #8011 那页唯一的真实形态）
    expect(
      density(`
function Row({ renderActions }: any) {
  return (
    <table>
      <thead><tr><th className="sticky right-0">操作</th></tr></thead>
      <tbody><tr><td className="sticky right-0">{renderActions(row)}</td></tr></tbody>
    </table>
  )
}
const renderActions = (row: any) => (
  <div><button>查看</button><button>备注</button><button>发货</button><button>处理退款</button></div>
)`),
    ).toBe(4)
  })
})
