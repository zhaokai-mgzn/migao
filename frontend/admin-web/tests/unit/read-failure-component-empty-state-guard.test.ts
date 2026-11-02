// case_ids: UI-147
/**
 * 类级元守卫（issue #8200 · P1-06）：**组件式空态（`<EmptyState>`）不得冒充读失败**。
 *
 * ## 病灶（这一步之前**全绿**，而现场就是缺陷）
 *
 * 上线审计 P1-06 的观测面 = `frontend/admin-web/src/components/common/ListLoadError.tsx` 只被
 * **28 个文件**引用，而 `find frontend/admin-web/src/app -name page.tsx` = **58~59** 个页
 * ⇒ 按「有没有引用那个共享件」数，**37 页**被点成缺口。逐页复核（读码 + 渲染期注入）后，
 * 那 37 页里绝大多数**已经有**自己的常驻失败面（`/products` 的 `products-load-failed`、
 * `/dashboard` 的 `dashboard-load-failed`、`/production` 的 `production-board-error`、
 * `/orders/[id]` 的 `order-detail-load-error` …）⇒ **「引用数」是一个会把缺陷放大 36 倍的代理指标**。
 *
 * 真正的缺口只有一处，而且它是**被三条既有判据同时漏掉的形态**：
 * `src/app/(dashboard)/categories/page.tsx` 的空态是**组件式**的
 * `<EmptyState testId="categories-empty" title="还没有商品分类" … />` ——
 *   ① 空的 `catch` 只写了「Error handled by API layer」（读面失败被吞）；
 *   ② 空态文案 `还没有商品分类` 不以「记录/数据/内容」收尾 ⇒ 不命中 `EMPTY_TEXT_RE`；
 *   ③ 于是 `EMPTY_STATE_LEDGER` / `FAILURE_ANCHORS` / `READ_SURFACES` 三张表都不会因此变红。
 * ⇒ 读接口 500 时屏上写的是「还没有商品分类」+「先建一个分类，再往里加商品」——
 * **把「没读到」说成「本来就没有」**（DQ-1 明令：空态/读不到不得互相冒充）。
 *
 * ## 判据（各自能单独变红）
 *
 * ① **未登记即红**：面内（`(dashboard)` + `src/components`，纯展示原语除外）凡渲染 `<EmptyState`
 *    的文件必须带**读面失败锚**（`hasFailureAnchor`，与判据 ③ 同一份判定、不写第二份正则）；
 *    不满足且未登记进 `COMPONENT_EMPTY_LEDGER` ⇒ 红并**具名**报出文件。
 * ② **面自证**：扫描面非空、命中非空、`/categories` 在面里 —— 判据被自己扫成空集 = 假绿。
 * ③ **台账只许缩短**：`COMPONENT_EMPTY_LEDGER.length > COMPONENT_EMPTY_LEDGER_FLOOR` ⇒ 红；
 *    条目**不再命中**（修好了）⇒ 僵尸红 ⇒ 逼着删干净。
 * ④ **判别力自证（注入式，内存）**：修前形态（`<EmptyState>` 且无失败锚）**必红**、修后形态不红、
 *    注释里的同形态不误伤、`<EmptyState` 的自闭合形态同样被识别。
 * ⑤ **与判据 ③ 的分工**（**盲区证词**，不是重复判定）：同一段修前源码，判据 ③ 的文案面
 *    **一处都扫不到**，而本判据能命中 —— 这条用例存在的意义就是钉住「③ 为什么会漏」。
 *
 * ## 边界（照实登记，§19.1）
 *
 * - **只认共享原语**的调用点：手写空态自行承担（③ 的文案面 / ⑤ 的运行期面各管一半）；
 * - **只判源码形态**：「失败锚有没有真的接到这次读失败上」判不了 —— 那一半是实例判据
 *   （`tests/unit/pages/categories.test.tsx`：失败 ⇒ 常驻失败面 + 重试真的重发 + 空态**不在**）；
 * - 判不了「失败面够不够显眼」（§15.7 读图面）；
 * - 不改任何门禁的通过条件、不新增 required check。
 */
import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  COMPONENT_EMPTY_LEDGER,
  COMPONENT_EMPTY_LEDGER_FLOOR,
  COMPONENT_EMPTY_SCOPES,
  componentEmptyStateOffenders,
  componentEmptyStateSitesFromSource,
  componentEmptyStateStale,
  emptyStateSitesFromSource,
  hasFailureAnchor,
} from '../../scripts/read-failure-empty-state-scan.mjs'

const ADMIN_WEB_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const read = (rel: string) => fs.readFileSync(path.join(ADMIN_WEB_ROOT, rel), 'utf8')

const CATEGORIES_PAGE = 'src/app/(dashboard)/categories/page.tsx'

/**
 * 修前形态（**逐字**取自 `git show origin/main:frontend/admin-web/src/app/(dashboard)/categories/page.tsx`）：
 * 空的 `catch` + 组件式空态，且**没有任何失败锚** —— 读失败与真空态在屏上不可区分。
 */
const PRE_FIX_SNIPPET = `
  const loadCategories = useCallback(async () => {
    setLoading(true)
    try {
      const res = await categoryApi.getCategories()
      setCategories(res.data.data || [])
    } catch (e) {
      // Error handled by API layer
    } finally {
      setLoading(false)
    }
  }, [])
  return (
    <PageCard>
      {loading ? (
        <Loading text="加载中…" />
      ) : categories.length === 0 ? (
        <EmptyState
          testId="categories-empty"
          icon="package"
          title="还没有商品分类"
          description="先建一个分类，再往里加商品。"
        />
      ) : (
        <CategoryTree categories={categories} />
      )}
    </PageCard>
  )`

/** 修后形态（**不判红**的对照夹具；与工作树里的 `page.tsx` 同构） */
const POST_FIX_SNIPPET = `
  const [categoriesLoadFailed, setCategoriesLoadFailed] = useState(false)
  return (
    <PageCard>
      {categoriesLoadFailed && (
        <ListLoadError testId="categories-load-error" message="分类没读到" onRetry={loadCategories} />
      )}
      {loading ? (
        <Loading text="加载中…" />
      ) : categories.length === 0 ? (
        categoriesLoadFailed ? null : (
          <EmptyState testId="categories-empty" icon="package" title="还没有商品分类" />
        )
      ) : (
        <CategoryTree categories={categories} />
      )}
    </PageCard>
  )`

describe('类级守卫：组件式空态必须带读面失败锚（issue #8200 P1-06）', () => {
  it('① 未登记即红：面内渲染 `<EmptyState` 的文件必须带失败锚（现取读数 = 0 条未登记）', () => {
    const { files, sites, unregistered, stale } = componentEmptyStateOffenders(ADMIN_WEB_ROOT)

    // ② 面自证：面非空、命中非空、病灶页在面里（空集 = 判据在扫空气）
    expect(files.length).toBeGreaterThanOrEqual(100)
    expect(sites.length).toBeGreaterThanOrEqual(8)
    expect(files).toContain(CATEGORIES_PAGE)
    expect(COMPONENT_EMPTY_SCOPES).toEqual(['src/app/(dashboard)', 'src/components'])

    // ① 判红面必须为空（每个渲染 `<EmptyState` 的文件都已有常驻失败面）
    expect(unregistered.map((s) => s.key)).toEqual([])
    // ③ 台账只许缩短 + 无僵尸条目
    expect(COMPONENT_EMPTY_LEDGER.length).toBeLessThanOrEqual(COMPONENT_EMPTY_LEDGER_FLOOR)
    expect(stale).toEqual([])

    // 反向核：病灶页修复后**真的**带上了失败锚（不是把条目挪进台账骗绿）
    expect(hasFailureAnchor(read(CATEGORIES_PAGE))).toBe(true)
    // 且它的空态锚仍在（「失败 ≠ 空」不等于「把空态删了」）
    expect(read(CATEGORIES_PAGE)).toContain('testId="categories-empty"')
  })

  it('④ 判别力自证（内存变异）：修前形态必红、修后与「注释里提及」不红、自闭合形态同样识别', () => {
    const opts = { file: CATEGORIES_PAGE }

    // 修前形态 ⇒ 命中，且**没有**失败锚（这正是「读失败 ⇒ 空态」的机器形态）
    expect(componentEmptyStateSitesFromSource(PRE_FIX_SNIPPET, opts).length).toBe(1)
    expect(hasFailureAnchor(PRE_FIX_SNIPPET)).toBe(false)
    // 修后形态 ⇒ 同样命中空态（不藏），但**带了**失败锚 ⇒ 不判红
    expect(componentEmptyStateSitesFromSource(POST_FIX_SNIPPET, opts).length).toBe(1)
    expect(hasFailureAnchor(POST_FIX_SNIPPET)).toBe(true)

    // 自闭合形态（`<EmptyState … />`）与跨行形态都认
    expect(componentEmptyStateSitesFromSource(`<EmptyState testId="x-empty" />`, opts).length).toBe(1)
    // 非 JSX 的提及（import / 注释）**不算**渲染 —— 本仓注释惯例会引用这些串
    expect(componentEmptyStateSitesFromSource(`import EmptyState from './EmptyState'`, opts)).toEqual([])
    expect(componentEmptyStateSitesFromSource(`// 旧形态：<EmptyState title="暂无数据" />`, opts)).toEqual([])
    // 别的组件不算（只认共享原语 `EmptyState`）
    expect(componentEmptyStateSitesFromSource(`<EmptyPlaceholder title="x" />`, opts)).toEqual([])

    // 台账空转（只许缩短）：登记一个**不存在**的未接线文件 ⇒ 僵尸红
    expect(componentEmptyStateStale(ADMIN_WEB_ROOT, ['src/app/(dashboard)/probe/page.tsx'])).toEqual([
      'src/app/(dashboard)/probe/page.tsx',
    ])
    // 反向读数：真台账（空）+ 真扫面 ⇒ 不报
    expect(componentEmptyStateStale(ADMIN_WEB_ROOT, [])).toEqual([])
  })

  it('⑤ 盲区证词：同一段修前源码，文案面判据（③）**一处都扫不到** —— 这就是为什么要有本条', () => {
    // ③ 的空态文案口径（`EMPTY_TEXT_RE`）在修前形态上**零命中**（`还没有商品分类` 不以
    // 「记录/数据/内容」收尾）⇒ 三条既有判据全绿，而屏上写的正是「没有分类」这个事实性断言。
    expect(emptyStateSitesFromSource(PRE_FIX_SNIPPET, { file: CATEGORIES_PAGE })).toEqual([])
    // 本判据（⑥）在同一段源码上**命中** —— 两条判据的射程是互补的，不是重复判定。
    expect(componentEmptyStateSitesFromSource(PRE_FIX_SNIPPET, { file: CATEGORIES_PAGE }).length).toBe(1)
  })
})
