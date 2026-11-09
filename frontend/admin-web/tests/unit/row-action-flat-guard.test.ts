// case_ids: UI-057, UI-058, UI-130
/**
 * 类级元守卫：**「操作」列按钮逐条平铺、不得收进「⋯」**（2026-11-09 用户裁定，issue #8849）。
 *
 * ## 为什么口径反转了
 *
 * #8011 / #8038 / #8039 曾把「操作列 ≥3 个同级可点」判成缺陷，收成「1 主行动 + ⋯ 菜单」；
 * 2026-11-07 用户对销售订单列表反向裁定「按钮直接展示、不要收在『...』里面」（#8837），
 * 2026-11-09 把同一裁定推广到观星台全部列表页（#8849）。⇒ 密度上限作废，本守卫只判**形态**：
 * 动作面里不得出现折叠原语，且已收口面必须仍是平铺。
 *
 * ## 判据（各自能单独变红）
 *
 * ① **折叠面即红**：任何「操作」列动作面出现 `<RowActions>` / `aria-label="更多操作"` /
 *    `aria-haspopup` / `<MoreHorizontal>` ⇒ 具名红；扫描面为空也红（防判据空跑）。
 * ② **退役原语即红**：全 `src/` 不许再 import / 渲染 `RowActions`，也不许出现「更多操作」。
 * ③ **正向锚**：台账 `flat_surfaces` 每条都必须仍被扫到、且逐字含 `<RowActionLink>` ——
 *    「把整列删掉」也能让折叠数变 0，这条堵掉那种假绿。
 * ④ **判别力自证**：折叠形态必红、平铺形态不红、注释不误伤、委托式动作面会被跟随。
 * ⑤ **正向锚的反向对照**：缺平铺锚 / 又出现折叠原语 / 缺文件 ⇒ 红。
 */
import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  MORE_LABEL,
  RETIRED_PRIMITIVE,
  SCOPES,
  actionSurfacesFromSource,
  flatAnchorViolations,
  flatAnchorViolationsFrom,
  flatSurfaceEntries,
  flatSurfaceFiles,
  foldedAnchorsInNode,
  foldedSurfaces,
  foldedViolationsFromSource,
  loadLedger,
  retiredUsages,
  retiredUsagesFromSource,
  rowActionSites,
} from '../../scripts/row-action-flat-scan.mjs'

const ADMIN_WEB_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')

/** 改前形态（`git show origin/main:frontend/admin-web/src/components/products/ProductTable.tsx` 的 ⋯ 菜单）：必红 */
const FOLDED_COLUMN_PROBE = `
const columns = [
  {
    key: 'actions',
    title: '操作',
    render: (record: Product) => (
      <RowActions menuTestId={\`product-menu-\${record.id}\`} items={itemsFor(record)}>
        <Button variant="ghost" size="sm">编辑</Button>
      </RowActions>
    ),
  },
]`

/** 改后形态（平铺）：不红 */
const FLAT_COLUMN_PROBE = `
const columns = [
  {
    key: 'actions',
    title: '操作',
    render: (record: Product) => (
      <div className="flex items-center gap-1 whitespace-nowrap">
        <Button variant="ghost" size="sm" onClick={() => onEdit(record)}>编辑</Button>
        <RowActionLink onClick={() => onView(record)}>查看</RowActionLink>
        <RowActionLink tone="danger" onClick={() => onDelete(record)}>删除</RowActionLink>
      </div>
    ),
  },
]`

describe('类级守卫：「操作」列按钮逐条平铺、不得收进「⋯」（2026-11-09 用户裁定）', () => {
  it('① 折叠面即红：全部「操作」列动作面必须是平铺形态', () => {
    const { sites } = rowActionSites(ADMIN_WEB_ROOT)
    // 语料面自证：该扫的文件族非空、且「操作」列真被扫到（否则判据是空跑）
    expect(SCOPES.length).toBeGreaterThan(0)
    expect(sites.length, '扫不到任何「操作」列 ⇒ 扫描面已漂移（不是「没有折叠」）').toBeGreaterThanOrEqual(20)

    const folded = foldedSurfaces(ADMIN_WEB_ROOT)
    expect(
      folded,
      '以下「操作」列仍在折叠 ⇒ 按用户 2026-11-09 裁定改成平铺（主行动 `Button ghost` + 其余 `RowActionLink`）：\n'
        + folded.map((v) => `  · ${v.file}（${v.anchors.join(' / ')}）`).join('\n'),
    ).toEqual([])
  })

  it(`② 退役原语即红：全 src 不许再用 ${RETIRED_PRIMITIVE} / 「${MORE_LABEL}」`, () => {
    const retired = retiredUsages(ADMIN_WEB_ROOT)
    expect(
      retired,
      `以下文件还在用退役原语（应改成 \`RowActionLink\` 平铺）：\n`
        + retired.map((v) => `  · ${v.file}（${v.anchors.join(' / ')}）`).join('\n'),
    ).toEqual([])

    // 组件本身不得留在桶里（「没人 import」不等于「原语没退场」）
    const barrel = fs.readFileSync(path.join(ADMIN_WEB_ROOT, 'src/components/ui/index.ts'), 'utf8')
    expect(barrel).not.toContain(`${RETIRED_PRIMITIVE}'`)
    expect(fs.existsSync(path.join(ADMIN_WEB_ROOT, 'src/components/ui/RowActions.tsx'))).toBe(false)
  })

  it('③ 正向锚：每个已收口面仍在扫描面内、且逐字含 <RowActionLink（防「删整列」假绿）', () => {
    const entries = flatSurfaceEntries() as Array<{
      file: string
      name: string
      source: string
      requires: string[]
    }>
    expect(entries.length, '平铺面台账不能为空（空数组 = 判据在扫空气）').toBeGreaterThanOrEqual(8)

    // 每条都必须带**可追溯的裁定来源**
    for (const e of entries) {
      expect(e.source, `${e.file} 缺裁定来源`).toMatch(/\d{4}-\d{2}-\d{2}/)
      expect(e.source, `${e.file} 的裁定来源没写「用户」`).toMatch(/用户/)
      expect(e.requires?.length, `${e.file} 缺平铺锚点（requires）`).toBeGreaterThan(0)
    }

    const { sites } = rowActionSites(ADMIN_WEB_ROOT)
    const keys = new Set(sites.map((s) => s.key))
    for (const e of entries) {
      expect(keys.has(e.file), `${e.name}（${e.file}）没被扫到 ⇒ 扫描面漂移 / 整列被搬走`).toBe(true)
    }
    expect(flatAnchorViolations(ADMIN_WEB_ROOT)).toEqual([])
    expect(flatSurfaceFiles().size).toBe(new Set(entries.map((e) => e.file)).size)
  })

  it('④ 判别力自证：折叠形态必红、平铺形态不红、注释不误伤', () => {
    // 折叠列：判红，且命中锚点 = 退役原语
    const foldedProbe = foldedViolationsFromSource(FOLDED_COLUMN_PROBE)
    expect(foldedProbe).toHaveLength(1)
    expect(foldedProbe[0].anchors).toContain(RETIRED_PRIMITIVE)

    // 平铺列：0 红
    expect(foldedViolationsFromSource(FLAT_COLUMN_PROBE)).toEqual([])

    // 注释里提到折叠原语不算（AST 只认节点）——
    // 这正是「文本判据会把修好的页面判红」的反例，必须守住。
    const commented = `/** 旧形态是 <RowActions> + 「${MORE_LABEL}」，本页已平铺（2026-11-09） */\n${FLAT_COLUMN_PROBE}`
    expect(foldedViolationsFromSource(commented)).toEqual([])

    // 全局退役原语：import / 渲染都算
    expect(retiredUsagesFromSource(`import { ${RETIRED_PRIMITIVE} } from '@/components/ui'`)).toContain(
      RETIRED_PRIMITIVE,
    )
    expect(retiredUsagesFromSource(`/** 注释里的 ${RETIRED_PRIMITIVE} 不算 */\nexport const x = 1`)).toEqual([])
    expect(retiredUsagesFromSource(`export const a = <button aria-label="${MORE_LABEL}" />`)).toContain(MORE_LABEL)
  })

  it('⑤ 判别力自证：原生表头式的折叠格也红（aria-haspopup / MoreHorizontal 形态）', () => {
    const raw = (actions: string) => `
function Row() {
  return (
    <table>
      <thead><tr><th className="sticky right-0">操作</th></tr></thead>
      <tbody><tr><td className="sticky right-0">${actions}</td></tr></tbody>
    </table>
  )
}`
    const folded = foldedViolationsFromSource(
      raw('<button aria-haspopup="menu" aria-label="更多操作"><MoreHorizontal /></button>'),
    )
    expect(folded).toHaveLength(1)
    expect(folded[0].anchors).toEqual(expect.arrayContaining(['aria-haspopup', MORE_LABEL, 'MoreHorizontal']))

    expect(
      foldedViolationsFromSource(raw('<Button>开工</Button><RowActionLink>取消</RowActionLink>')),
    ).toEqual([])
  })

  it('⑥ 委托式动作面会被跟随（`render: renderActions` 不能读成空面）', () => {
    const source = `
const renderActions = (row: any) => (
  <div>
    <Button>收款</Button>
    <RowActionLink>查看详情</RowActionLink>
    <RowActionLink>备注</RowActionLink>
  </div>
)
const columns = [{ key: 'actions', title: '操作', render: renderActions }]`
    const surfaces = actionSurfacesFromSource(source, { file: '<probe>.tsx' })
    expect(surfaces).toHaveLength(1)
    expect(foldedAnchorsInNode(surfaces[0].node)).toEqual([])
  })

  it('⑦ 正向锚的反向对照：缺平铺锚 / 又出现折叠原语 / 缺文件 ⇒ 红', () => {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'migao-flat-anchor-'))
    const rel = 'src/components/products/ProductTable.tsx'
    const abs = path.join(tmp, rel)
    fs.mkdirSync(path.dirname(abs), { recursive: true })
    const entry = {
      name: '商品管理列表（自证探针）',
      file: rel,
      requires: ['<RowActionLink'],
    }

    // 正向：平铺形态不红
    fs.writeFileSync(abs, FLAT_COLUMN_PROBE)
    expect(flatAnchorViolationsFrom(tmp, [entry])).toEqual([])

    // 反向 ①：平铺锚点被换掉（例如改回手拼 <button>）⇒ 缺锚红
    fs.writeFileSync(abs, FLAT_COLUMN_PROBE.replace(/<RowActionLink/g, '<button'))
    expect(flatAnchorViolationsFrom(tmp, [entry]).length).toBeGreaterThan(0)

    // 反向 ②：又出现折叠原语 ⇒ 红（即使平铺锚还在）
    fs.writeFileSync(abs, `${FLAT_COLUMN_PROBE}\nexport const y = <RowActions items={[]} />`)
    expect(flatAnchorViolationsFrom(tmp, [entry]).length).toBeGreaterThan(0)

    // 反向 ③：文件没了 ⇒ 红（整列被搬走 / 文件改名不能静默）
    fs.unlinkSync(abs)
    expect(flatAnchorViolationsFrom(tmp, [entry]).length).toBeGreaterThan(0)

    fs.rmSync(tmp, { recursive: true, force: true })
  })

  it('⑧ 台账本体可读、条目字段完整（防手写 JSON 漂移成判据读空气）', () => {
    const ledger = loadLedger()
    expect(ledger.scope).toContain('src/')
    expect(ledger.boundary.length).toBeGreaterThan(0)
    for (const e of ledger.flat_surfaces as Array<{ file: string; name: string; requires: string[] }>) {
      expect(e.file).toMatch(/^src\/.*\.tsx$/)
      expect(e.name.length).toBeGreaterThan(0)
      expect(e.requires).toContain('<RowActionLink')
    }
  })
})
