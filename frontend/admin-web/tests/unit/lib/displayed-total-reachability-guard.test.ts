// case_ids: UI-057
/**
 * 类级元守卫：**屏上显示了 total ⇒ 该集合必须可达**（issue #6697）。
 *
 * ## 为什么是类级
 *
 * `/production/remnants` 修前的形态是「屏上写 `page.total` + 请求里钉死 `page: 1, size: 100`」
 * —— 商家看到 332、只能翻到 100，其余 232 条**没有任何入口**。改这一页不解决复发：
 * 任何列表页都能把同一形态原样写回来（同族实证：`roles/page.tsx` / `orders/new/page.tsx`
 * 两处 B 形态，本单只登记不修）⇒ 判据必须落在**族**上，且**未登记即红**。
 *
 * ## 判据
 *
 * ① **未登记即红**：`production/**` 里命中「A 分页信封 total 上屏 / B 请求钉死 page:1+size:100 /
 *    C 屏上写「共 N 条」且引 `.total`」且**没接**共享 `Pagination` 的页面 ⇒ 必须在 `LEDGER` 里
 *    （可复制命令：`node scripts/displayed-total-reachability-scan.mjs`）；
 * ② **正向核**：`POSITIVE_ANCHORS` 里每一条「已改对的页面」必须**逐字**含它声明的锚
 *    （共享分页接线的 `data-testid` + 真请求的 `page` / `size` 传参）⇒ 有人把接线拆了当场红
 *    （只靠 ① 会**假绿**：把 Pagination 拆掉后该文件从「已接」变「未接」，
 *    但它在台账里挂着 ⇒ ① 照样绿 ⇒ 必须由 ② 堵这条路）；
 * ③ **台账只许缩短**：`LEDGER.length > LEDGER_FLOOR` ⇒ 红（逼着先修，而不是先加豁免）；
 *    且台账条目**仍须真命中其声明的形态**（修好了/删了 ⇒ 僵尸条目当场红）；
 * ④ **判别力自证**：对**历史坏形态**（本单修前的逐字写法：`page: 1, size: 100` + `page?.total`
 *    且零 Pagination）必红；对**已修形态**（现在的工作树）不红；注释里的同形态不误伤。
 *
 * ## 边界（照实登记，`migao-dev-flow` §19.1）
 *
 * - **扫描面只有 `src/app/(dashboard)/production`，不声明全站覆盖**（理由逐条在扫描器头部）；
 * - 只认**源码文本形态**（多行 JSX、自造分页控件漏判）；
 * - **本判据不跑真实浏览器** ⇒ 「控件在屏幕上真的可点」由实例判据
 *   （`tests/unit/pages/production-remnants-paging.test.tsx`，真 `Pagination` + 真请求参数）
 *   与 §15.7 真机截图共同承担，不在本条射程。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  SCOPE,
  LEDGER,
  LEDGER_FLOOR,
  classify,
  listPageFiles,
  scan,
} from '../../../scripts/displayed-total-reachability-scan.mjs'

const ADMIN_WEB_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')

/**
 * 正向核（已改对的页面必须逐字含这些锚）：`<file>::<锚>`。
 * 锚 = **接线本身**（共享组件的 testid + 真请求传参），不是文案。
 */
const POSITIVE_ANCHORS = [
  "src/app/(dashboard)/production/remnants/page.tsx::data-testid=\"remnant-pagination\"",
  'src/app/(dashboard)/production/remnants/page.tsx::<Pagination',
  'src/app/(dashboard)/production/remnants/page.tsx::size: pageSize',
]

/** 本单修前的逐字坏形态（判别力自证的夹具 —— 与 `git show origin/main:<path>` 一致） */
const PRE_FIX_REMNANTS = `
  const load = useCallback(async () => {
    const res = await remnantApi.ledger({ status: status || undefined, page: 1, size: 100 })
    setData(res.data?.data ?? null)
  }, [status])
  // 下面这行是屏上的承诺：
  ;<span>共 {data?.page?.total ?? 0} 块</span>
`

describe('类级守卫：屏上显示了 total ⇒ 该集合必须可达（issue #6697）', () => {
  it('① 未登记即红：production/** 里「命中且没接共享分页」的页面必须逐条在台账里', () => {
    const { candidates, offenders, unregistered } = scan(ADMIN_WEB_ROOT)

    // 面自证：候选集不许空（判据被自己扫成空集 = 假绿）
    expect(candidates.length).toBeGreaterThan(0)
    // 本页必须在候选里（它是这条判据的靶子）
    expect(candidates.map((c) => c.file)).toContain(
      'src/app/(dashboard)/production/remnants/page.tsx',
    )
    // 判红面必须为空
    expect(unregistered).toEqual([])
    // 且每一个「命中且没接」的都在台账里逐条登记
    for (const o of offenders) {
      expect(LEDGER.some((e) => e.startsWith(`${o.file}::`))).toBe(true)
    }
  })

  it('② 正向核：已改对的页面必须逐字含共享分页接线（拆掉接线 ⇒ 红）', () => {
    for (const anchor of POSITIVE_ANCHORS) {
      const [file, needle] = anchor.split('::')
      const source = readFileSync(path.join(ADMIN_WEB_ROOT, file), 'utf8')
      expect(source).toContain(needle)
    }
    // 且该文件确实被扫到了（锚与扫描面同源，不各说各话）
    expect(listPageFiles(ADMIN_WEB_ROOT)).toContain('src/app/(dashboard)/production/remnants/page.tsx')
  })

  it('③ 台账只许缩短：条目数不得超过冻结基线，且每条仍须真命中其声明的形态', () => {
    expect(LEDGER.length).toBeLessThanOrEqual(LEDGER_FLOOR)
    const { staleLedger } = scan(ADMIN_WEB_ROOT)
    expect(staleLedger).toEqual([])
  })

  it('④ 判别力自证：修前的逐字坏形态必红；注释里的同形态不误伤', () => {
    // 修前形态 ⇒ 命中 A + B、且没接 Pagination
    const before = classify('fixture/before.tsx', PRE_FIX_REMNANTS)
    expect(before?.file).toBe('fixture/before.tsx')
    expect(before?.forms).toEqual(expect.arrayContaining(['A', 'B']))
    expect(before?.hasPagination).toBe(false)

    // 修后形态（真 `<Pagination` 接线）⇒ 命中但 hasPagination = true（因此不判红）
    const after = classify(
      'fixture/after.tsx',
      `${PRE_FIX_REMNANTS}\n;<Pagination current={page} pageSize={pageSize} total={data?.page?.total ?? 0} />`,
    )
    expect(after?.hasPagination).toBe(true)

    // 注释里的同形态（本仓注释惯例会引用这些串）⇒ 不命中（判据被自己的文案喂红是实测过的坑）
    const commented = classify(
      'fixture/comment.tsx',
      '// 修前：remnantApi.ledger({ status, page: 1, size: 100 }) 且屏上渲染 data?.page?.total\nconst x = 1\n',
    )
    expect(commented).toBeNull()

    // 有意不判的假红面 ⇒ 不命中（进度计数 / 服务端对象字段）
    expect(classify('fixture/progress.tsx', 'const x = `{p.done ?? 0}/{p.total ?? 0}`\n')).toBeNull()
    expect(classify('fixture/board.tsx', 'const total = board?.total\n')).toBeNull()
  })

  it('⑤ 判据面自证：扫描面就是生产域（不是全站，也不空）', () => {
    expect(SCOPE).toBe('src/app/(dashboard)/production')
    const files = listPageFiles(ADMIN_WEB_ROOT)
    expect(files.every((f) => f.startsWith(`${SCOPE}/`))).toBe(true)
    expect(files.length).toBeGreaterThanOrEqual(9)
  })
})
