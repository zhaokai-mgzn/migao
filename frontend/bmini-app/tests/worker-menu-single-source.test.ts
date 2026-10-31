// case_ids: BM-059
/**
 * 工人菜单**页面键命名空间**的跨语言同源守卫（目标 ⑤，issue #8196）
 *
 * ## 治的形态
 *
 * 「工人端出现哪些页面」的**唯一真值**在后端 `backend/admin-api/src/main/java/com/migao/admin/worker/WorkerPages.java`
 * 的常量闭词表（`report` / `order` / `cut_calc` / `piecework` / `shipment` / `to_ship` / `inspect` /
 * `rework` / `stock`）。bmini 的 `src/utils/workerMenu.ts` 为了做入口显隐**又抄了一份字面量**
 * （`WORKER_MENU_KEYS`）—— 这是同一真值的**第二份**：
 *
 * - 前端拼错一个键（`toShip: 'toShip'` / `cut_calc` 写成 `cutcalc`）⇒ 商家在后台勾了，
 *   工人端**永远不出现**那个入口，而两边各自的测试都绿（各自只断言自己那份）；
 * - 后端删 / 改名一个键 ⇒ 前端那份变成**幽灵键**，同样没有任何东西会红。
 *
 * 本守卫把「**bmini 的键集 ⊆ 后端 `WorkerPages` 的常量值**」变成可执行判据（只许缩小方向：
 * 后端新增键**不**强制小程序加菜单 —— 后端键还服务 `/w/` 与工人档案配置；但前端**不许发明**
 * 后端没有的键，也不许两个菜单名指向同一个键）。
 *
 * | # | 判据 | 回归时会怎么红 |
 * |---|---|---|
 * | 1 | bmini 的每个键都必须能在后端 `WorkerPages` 里逐字找到 | 前端加一个 `'kitchen'` ⇒ 具名红（列出该键） |
 * | 2 | bmini 的键值唯一（两个菜单名同一个键 ⇒ 显隐判据互相串） | 复制一行 / 两个常量同值 ⇒ 红 |
 * | 3 | 后端闭词表**非空**且解析到的键数 ≥ 现取条数（解析器没跑空） | 后端改了声明形态 ⇒ 红（先对齐解析器，不许静默空跑） |
 * | 4 | 判别力自证（真语料上做内存变异）：发明键 / 重复键 / 后端撤键 ⇒ 各自判红 | 判据退化成恒真 ⇒ 红 |
 *
 * ## 边界（照实登记，§19.1）
 * ① 判的是**键名**的同源，**不是**菜单项文案 / 顺序 / 路由（那些只在 bmini 一份，后端不下发）；
 * ② 它**不跑** Java 测试（不嵌套第二个套件）：后端键的**行为**（默认集合 / 逐人开关）由
 *    `WorkerPagesTest` / `WorkerProfileControllerTest` 承担；
 * ③ 它不改任何门禁的通过条件、不新增豁免。
 */
import fs from 'fs'
import path from 'path'
import { WORKER_MENU_KEYS } from '../src/utils/workerMenu'

const BMINI_ROOT = path.join(__dirname, '..')
const REPO_ROOT = path.join(BMINI_ROOT, '..', '..')
const WORKER_PAGES_JAVA = path.join(
  REPO_ROOT,
  'backend',
  'admin-api',
  'src',
  'main',
  'java',
  'com',
  'migao',
  'admin',
  'worker',
  'WorkerPages.java',
)

/** 现取后端页面键闭词表：`public static final String X = "key";`（唯一解析口径） */
export function backendPageKeys(source: string): string[] {
  const keys: string[] = []
  const re = /public\s+static\s+final\s+String\s+[A-Z0-9_]+\s*=\s*"([^"]+)"\s*;/g
  let hit: RegExpExecArray | null
  while ((hit = re.exec(source)) !== null) keys.push(hit[1])
  return keys
}

/**
 * 核心判定（真判据与注入式红证**共用同一份** —— 红证必须走真判据，见 `migao-dev-flow` §23.5）。
 *
 * @param menuValues bmini 侧的菜单键（现取 = `Object.values(WORKER_MENU_KEYS)`）
 * @param backendKeys 后端 `WorkerPages` 的常量值（现取 = `backendPageKeys()`）
 */
export function menuKeyProblems(menuValues: string[], backendKeys: string[]): string[] {
  const problems: string[] = []
  const backend = new Set(backendKeys)

  if (backendKeys.length === 0) {
    // fail-closed：解析不到后端键 ⇒ 判据会变成恒真（空集是任何集合的子集）
    problems.push('后端 WorkerPages 的常量闭词表解析为空 ⇒ 本判据会退化成空断言（先对齐解析器）')
  }
  if (menuValues.length === 0) {
    problems.push('bmini 的 WORKER_MENU_KEYS 为空 ⇒ fail-closed（工人的菜单入口全部消失）')
  }

  const seen = new Set<string>()
  for (const key of menuValues) {
    if (!backend.has(key)) {
      problems.push(
        `发明键：bmini 的 WORKER_MENU_KEYS 出现「${key}」，而后端 WorkerPages 没有这个页面键 —— ` +
          '商家后台勾不到它、`/api/worker/me` 也永远不会下发（入口必然不出现，且无人会红）',
      )
    }
    if (seen.has(key)) {
      problems.push(`重复键：「${key}」在 WORKER_MENU_KEYS 里出现了两次 —— 两个菜单名会互相影响显隐`)
    }
    seen.add(key)
  }
  return problems
}

describe('工人菜单页面键：bmini ⊆ 后端 WorkerPages（目标 ⑤ / issue #8196）', () => {
  const source = fs.readFileSync(WORKER_PAGES_JAVA, 'utf8')
  const backendKeys = backendPageKeys(source)
  const menuValues = Object.values(WORKER_MENU_KEYS) as string[]

  it('③ 坐标自证：后端闭词表解析到了现取条数（判据没跑空）', () => {
    // 后端常量声明形态一旦变化，这条先红（而不是让「发明键」判据静默变绿）
    expect(backendKeys.length).toBeGreaterThanOrEqual(9)
    for (const must of ['report', 'piecework', 'order', 'cut_calc', 'shipment', 'to_ship', 'inspect', 'rework', 'stock']) {
      expect(backendKeys).toContain(must)
    }
    expect(menuValues.length).toBeGreaterThan(0)
  })

  it('① 真语料：bmini 的每个键都在后端闭词表里（不许发明）', () => {
    expect(menuKeyProblems(menuValues, backendKeys)).toEqual([])
  })

  it('② 真语料：键值唯一（没有两个菜单名指向同一个键）', () => {
    expect(new Set(menuValues).size).toBe(menuValues.length)
  })

  it('④ 判别力自证：发明键 / 重复键 / 后端撤键 ⇒ 各自判红（内存变异走真判据）', () => {
    const invented = menuKeyProblems([...menuValues, 'kitchen'], backendKeys)
    expect(invented.join('\n')).toContain('kitchen')

    const duplicated = menuKeyProblems([...menuValues, menuValues[0]], backendKeys)
    expect(duplicated.join('\n')).toContain('重复键')

    // 后端撤掉一个 bmini 正在用的键（模拟「后端改名了、前端没跟上」）
    const dropped = backendKeys.filter((key) => key !== 'to_ship')
    expect(menuKeyProblems(menuValues, dropped).join('\n')).toContain('to_ship')

    // 解析空 ⇒ fail-closed（空集不许当"全部合规"）
    expect(menuKeyProblems(menuValues, []).length).toBeGreaterThan(0)
  })
})
