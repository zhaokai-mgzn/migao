// case_ids: UI-046, PP-010
// 类级元守卫：「读面失败时不许把失败说成别的原因」（issue #6702）。
/**
 * 类级元守卫：**读面失败 ⇒ 不得印零值、不得把非权限失败归因成权限**（issue #6702）。
 *
 * ## 为什么是类级
 *
 * `/production/remnants` 修前的形态是「注入 500 ⇒ 一边说读取失败、一边印「共 **0** 块」，
 * 同时把 500 说成「可能是当前岗位没有「工艺配置」权限」」。改这一页不解决复发：
 * 任何列表页都能把同一形态原样写回来（**同族已实测**：`stock-ledger/page.tsx` 两处
 * 与修前形态逐字相同，见 `LEDGER`）⇒ 判据必须落在**族**上，且**未登记即红**。
 *
 * ## 判据（各自能单独变红）
 *
 * ① **未登记即红**：`(dashboard)/**` 里命中 A（读失败零值上屏）/ B（非 403 被归因成权限）
 *    且**不在** `LEDGER` 里的 ⇒ 红（可复制命令：`node scripts/read-failure-copy-attribution-scan.mjs`）；
 * ② **正向核**：`POSITIVE_ANCHORS` 里每一条「已改对的页面」必须**逐字**含它声明的锚
 *    （失败锚点 `data-testid` + 真重发的重试出口 + **按状态分流**的判据函数 + 失败态计数行）
 *    ⇒ 有人把接线拆了（把 `!error` 守卫摘掉、把 `remnantReadErrorCopy` 换回硬编码）当场红；
 * ③ **台账只许缩短**：`LEDGER.length > LEDGER_FLOOR` ⇒ 红（逼着先修，而不是先加豁免）；
 *    且台账条目**仍须真命中**其声明的形态（修好了 / 删了 ⇒ 僵尸条目当场红）；
 * ④ **判别力自证**：对**历史坏形态**（本单修前的逐字写法：500 文案 + `共 {data?.page?.total ?? 0} 块`）
 *    必红；对**已修形态**（现在的工作树）不红；**注释里的同形态不误伤**
 *    （本仓注释惯例会引用这些串 —— 判据被自己的文案喂红是实测过的坑）。
 *
 * ## 与 #6701 扫描面的**边界**（两份台账不许互相打架）
 *
 * | 面 | 扫描器 | 判什么 |
 * |---|---|---|
 * | **本面**（issue #6702） | `scripts/read-failure-copy-attribution-scan.mjs` | 读失败的**话术归因**（B）+ **计数零值上屏**（A） |
 * | #6701 的**工作台金额面** | `scripts/derived-zero-fallback-scan.mjs`（`SCOPE = (dashboard)/dashboard`，**在飞**） | **派生字面量的零值回退**（工作台金额 / 图表口径） |
 *
 * 两面在 `dashboard/**` 上**有意不重叠**：本扫描器 `EXCLUDE_DIRS` 逐字排除 `dashboard`
 * ⇒ 同一行不会被两份台账各记一次（重复记账 = 修一处要改两处台账，且两份台账会互相把对方判成僵尸）。
 *
 * ## 边界（照实登记，`migao-dev-flow` §19.1）
 *
 * - **只认源码文本形态**（逐行）：多行 JSX（`共` 与 `?? 0` 不在一行）、以及「先 `const n = data?.total ?? 0`
 *   再上屏」的数据流形态会**漏判**（要判它得做数据流分析，是另一个包）；
 * - B 形态的「这一行读不读状态码」是**行内**判据：状态码比较与 `setError` 分处两行且中间没有 `if`
 *   的形态会**假红**（本仓未实测到；`settings/page.tsx` 的专业形态是同行的 `403` 比较）；
 * - **本判据不跑真实浏览器** ⇒ 「重试真的再发了一次请求、计数真的恢复成 332」由实例判据
 *   （`tests/unit/pages/production-remnants-read-failure.test.tsx`，真 `Button` + 真调用参数）
 *   与 §15.7 真机截图共同承担，不在本条射程。
 */
import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  SCOPE,
  LEDGER,
  LEDGER_FLOOR,
  LEDGER_REASONS,
  POSITIVE_ANCHORS,
  classifySource,
  copyAttributionSites,
  findOffenders,
  ledgerKey,
  listSourceFiles,
  staleLedger,
} from '../../scripts/read-failure-copy-attribution-scan.mjs'

const ADMIN_WEB_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')

/** 本单修前的**逐字**坏形态（判别力自证的夹具；与 `git show origin/main:<path>` 一致） */
const PRE_FIX_SNIPPET = `
    } catch {
      setData(null)
      setError('余料台账读取失败（可能是当前岗位没有「工艺配置」权限）—— 请联系管理员开权限后重试')
    }
  }, [status, page, pageSize])
;<span className="text-xs text-neutral-500">共 {data?.page?.total ?? 0} 块</span>`

/** 本单修后的形态（**不判红**的对照夹具） */
const POST_FIX_SNIPPET = `
    } catch (e) {
      setData(null)
      setError(remnantReadErrorCopy(e))
    }
  }, [status, page, pageSize])
;<span className="text-xs text-neutral-500">共 {error ? '—' : (data?.page?.total ?? 0)} 块</span>`

describe('类级守卫：读面失败不得印零值 / 不得归因成权限（issue #6702）', () => {
  it('① 未登记即红：(dashboard)/** 里命中 A / B 的必须逐条在台账里', () => {
    const { files, sites } = copyAttributionSites(ADMIN_WEB_ROOT)
    const { unregistered } = findOffenders(ADMIN_WEB_ROOT)

    // 面自证：候选集不许空（判据被自己扫成空集 = 假绿）
    expect(files.length).toBeGreaterThan(0)
    // 判红面必须为空
    expect(unregistered).toEqual([])
    // 且每一条命中都能在台账里逐字核对（键 = `路径::形态`），并**逐条给出理由**（双向：键 ⇄ 理由）
    for (const s of sites) {
      expect(LEDGER).toContain(ledgerKey(s))
      expect(LEDGER_REASONS[ledgerKey(s)]).toBeTruthy()
    }
    // 反向：台账里每条都必须有理由（不许只加键、不给说法）
    for (const key of LEDGER) expect(LEDGER_REASONS[key]).toBeTruthy()
  })

  it('② 正向核：已改对的页面必须逐字含失败锚点 / 重试出口 / 按状态分流的判据函数 / 失败态计数行', () => {
    for (const anchor of POSITIVE_ANCHORS) {
      const source = fs.readFileSync(path.join(ADMIN_WEB_ROOT, anchor.file), 'utf8')
      for (const needle of anchor.anchors) {
        expect(source, `${anchor.file} 缺少锚点：${needle}`).toContain(needle)
      }
      // 锚与扫描面同源（不各说各话）：该文件确实被扫到
      expect(listSourceFiles(ADMIN_WEB_ROOT)).toContain(anchor.file)
    }
    // 反向对照（正向核只锚「改后有什么」，这一半堵的是「旧形态被原样写回来」）：
    // 页面上的**用户可见错误话术**必须来自 `remnantReadErrorCopy`（按状态分流），
    // 且**不得**再出现修前那句把 500 说成权限的硬编码文案。
    // ⚠️ 断言逐字删掉 `可能是当前岗位没有「工艺配置」权限` 的**源码行**——页面 docstring 会
    // 引用它（本仓注释惯例），把它一并禁掉是假红（判据被自己的文案喂红，实测过的坑）。
    const pageSource = fs.readFileSync(
      path.join(ADMIN_WEB_ROOT, 'src/app/(dashboard)/production/remnants/page.tsx'),
      'utf8',
    )
    expect(pageSource).toContain('setError(remnantReadErrorCopy(e))')
    expect(pageSource.split('\n').filter((l) => l.includes('工艺配置'))).toEqual([
      ...pageSource.split('\n').filter((l) => l.trim().startsWith('*') && l.includes('工艺配置')),
    ])
    const codeLines = pageSource
      .split('\n')
      .filter((l) => !l.trim().startsWith('*') && !l.trim().startsWith('//'))
    expect(codeLines.some((l) => l.includes('工艺配置'))).toBe(false)
  })

  it('③ 台账只许缩短：条目数不得超过冻结基线，且每条仍须真命中其声明的形态', () => {
    expect(LEDGER.length).toBeLessThanOrEqual(LEDGER_FLOOR)
    expect(staleLedger(ADMIN_WEB_ROOT)).toEqual([])
  })

  it('④ 判别力自证：修前的逐字坏形态必红；修后形态与注释里的同形态不误伤', () => {
    // 修前形态 ⇒ 命中 A（零值上屏）。🔴 **只命中 A**：B 形态的措辞判据**检不出**修前那句
    //（「没有」与「权限」之间夹了「「工艺配置」」），放宽就会引入 2 处假红 —— 如实登记在
    // 扫描器头部「B 形态对本单修前那句 500 文案检不出」；修前那句由**实例判据**逐字承担。
    const before = classifySource('fixture/before.tsx', PRE_FIX_SNIPPET)
    expect(before.map((h) => h.form).sort()).toEqual(['A'])

    // 修后形态 ⇒ 零命中（`?? 0` 仍在，但它被 `error ? '—' :` 守着；文案不再提权限）
    expect(classifySource('fixture/after.tsx', POST_FIX_SNIPPET)).toEqual([])

    // 注释里的同形态（本仓注释惯例会引用这些串）⇒ 不命中
    const commented = PRE_FIX_SNIPPET.split('\n')
      .map((l) => `// ${l}`)
      .join('\n')
    expect(classifySource('fixture/comment.tsx', commented)).toEqual([])

    // B 形态的判别力自证（用**同类更露骨的形态**：stock-ledger 的逐字写法）
    const stockForm = `setBatchError('批次余量读取失败（可能是当前岗位没有「商品管理」权限）—— 请联系管理员开权限后重试')`
    expect(classifySource('fixture/stock.tsx', stockForm).map((h) => h.form)).toEqual(['B'])
    // …而按状态分流（同行有 `403`）不算命中
    const routed = `if (status === 403) { setError('你没有查看「余料台账」的权限 —— 请联系管理员开通后重试') }`
    expect(classifySource('fixture/routed.tsx', routed)).toEqual([])

    // 面自证之二：扫描器认的是**仓库相对路径**，且 `dashboard` 目录被有意让给 #6701
    expect(SCOPE).toBe('src/app/(dashboard)')
    const files = listSourceFiles(ADMIN_WEB_ROOT)
    expect(files.some((f) => f.startsWith('src/app/(dashboard)/dashboard/'))).toBe(false)
  })
})
