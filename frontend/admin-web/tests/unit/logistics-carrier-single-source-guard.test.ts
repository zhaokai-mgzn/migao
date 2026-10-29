// case_ids: CU-009, UI-047
// 类级元守卫（issue #8079）：**承运商候选只有一个读取口，且按物流类型收敛**。
//
// 病灶（#8070 真机复核）：`LOGISTICS_TYPES` 与 `LOGISTICS_COMPANIES` 原是两套互不相关的词表 ⇒
// 「物流类型 = 快递」+「物流公司 = 德邦快递 / 四季安物流」这种自相矛盾的组合随手可填。
// 修两份发货入口**不算**修：**下一个**页面只要再 `import { LOGISTICS_COMPANIES }` 直接
// `.map()` 一遍，混搭就回来了 —— 而那种回潮**不会**让任何既有判据变红。
//
// 两条规则（判据本体 = 下面的 `directConsumers` / `duplicateDeciders`，纯函数、可内存注入）：
//   ① **直连消费即红**：`src/**` 里除词表文件自己外，**不得出现** `LOGISTICS_COMPANIES`
//      标识符 —— 候选必须经 `logisticsCompaniesFor(type)` 取（它才带类型收敛）；
//   ② **判定实现唯一**：`logisticsCompaniesFor` / `switchCarrier` 只允许在词表文件里**定义**
//      （别处抄一份 = 第二份会漂的口径）。
// 另加**普查自证**（防「扫描面漂了 ⇒ 恒绿」）：已登记的 4 个消费点必须仍存在且仍在调
// `logisticsCompaniesFor(`；词表文件必须仍定义那两个函数。
//
// 边界（照实登记，§19.1）：
//   · 判**源码形态**，不判渲染结果 —— 渲染/交互由实例层守
//     （`tests/unit/pages/ship-order.test.tsx`、`tests/unit/pages/orders-inline-ship.test.tsx`
//     的 #8079 / ⑧ 组，以及 `tests/unit/lib/logistics.test.ts` 的词表口径）；
//   · 形态学判据不做语义一刀切：把词表重命名成别的常量再直连消费，本判据看不到（会随词表改名一起红）；
//   · 未知/空类型仍返回**全量**候选（档案面「未指定」不能凭空缩小），那是有意口径、不是漏收敛。
import { describe, it, expect } from 'vitest'
import { existsSync, readFileSync, readdirSync, statSync } from 'fs'
import { join, relative, sep } from 'path'

const SRC_DIR = join(process.cwd(), 'src')

/** 词表文件（唯一真值源）：只有它允许出现 `LOGISTICS_COMPANIES` 标识符 / 那两个判定函数 */
const SINGLE_SOURCE = 'src/lib/logistics.ts'

/** 已登记的消费点（**双向**：登记了就必须仍存在且仍走收敛入口，否则死条目即红） */
const REGISTERED_CONSUMERS = [
  'src/app/(dashboard)/orders/[id]/ship/ShipOrder.tsx',
  'src/components/orders/InlineShipForm.tsx',
  'src/app/(dashboard)/customers/[id]/CustomerDetail.tsx',
  'src/app/(dashboard)/orders/new/page.tsx',
]

const CANDIDATE_FN = 'logisticsCompaniesFor'
const SWITCH_FN = 'switchCarrier'

interface SourceFile {
  /** 仓库相对路径（正斜杠） */
  path: string
  text: string
}

/** 递归列出 `src/**` 下的 ts/tsx（排除测试目录）—— 只读，不改盘 */
function sourceFiles(): SourceFile[] {
  const out: SourceFile[] = []
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir)) {
      const full = join(dir, entry)
      if (statSync(full).isDirectory()) {
        walk(full)
        continue
      }
      if (!/\.(ts|tsx)$/.test(entry)) continue
      out.push({
        path: relative(process.cwd(), full).split(sep).join('/'),
        text: readFileSync(full, 'utf8'),
      })
    }
  }
  walk(SRC_DIR)
  return out
}

/** 去注释后再判 —— 沿革/说明注释里提到常量名不算直连消费（同 `craft-spec-row-source-guard` 口径） */
function stripComments(code: string): string {
  return code
    .replace(/\/\*[\s\S]*?\*\//g, '') // 块注释（含 JSX 的 {/* … */}）
    .replace(/^[ \t]*\/\/.*$/gm, '') // 整行行注释
}

/** ① 直连消费词表常量的文件（应为空） */
function directConsumers(files: SourceFile[]): string[] {
  return files
    .filter((f) => f.path !== SINGLE_SOURCE && /\bLOGISTICS_COMPANIES\b/.test(stripComments(f.text)))
    .map((f) => f.path)
}

/** ② 在词表文件之外**重复定义**判定函数的文件（应为空） */
function duplicateDeciders(files: SourceFile[]): string[] {
  const re = new RegExp(`(?:function|const|let)\\s+(?:${CANDIDATE_FN}|${SWITCH_FN})\\b`)
  return files.filter((f) => f.path !== SINGLE_SOURCE && re.test(stripComments(f.text))).map((f) => f.path)
}

const fake = (path: string, text: string): SourceFile => ({ path, text })

describe('承运商候选单一真值 + 类型收敛（类级元守卫，issue #8079）', () => {
  it('① 业务面不得直连 `LOGISTICS_COMPANIES`（绕过类型收敛）', () => {
    // 新增消费点请走 `logisticsCompaniesFor(type)` —— 它按类型收敛，且未知/空类型回全量
    expect(directConsumers(sourceFiles())).toEqual([])
  })

  it('② 判定实现唯一：`logisticsCompaniesFor` / `switchCarrier` 只在词表文件里定义', () => {
    expect(duplicateDeciders(sourceFiles())).toEqual([])
  })

  it('普查自证：已登记的消费点仍存在、且仍在走收敛入口（防「扫描面漂了 ⇒ 恒绿」）', () => {
    const files = sourceFiles()
    const byPath = new Map(files.map((f) => [f.path, f.text]))
    for (const path of REGISTERED_CONSUMERS) {
      expect(existsSync(join(process.cwd(), path)), `消费点不见了：${path}`).toBe(true)
      expect(byPath.get(path), `消费点未被扫到：${path}`).toMatch(
        new RegExp(`${CANDIDATE_FN}\\(`),
      )
    }
    const lib = byPath.get(SINGLE_SOURCE) ?? ''
    expect(lib).toContain(`export function ${CANDIDATE_FN}`)
    expect(lib).toContain(`export function ${SWITCH_FN}`)
  })

  it('判别力自证（内存注入，不落盘）：三种坏形态各自判红、合规形态不红', () => {
    // 直连消费 ⇒ 红；词表文件自己持有该常量 ⇒ 不红；走收敛入口 ⇒ 不红
    expect(
      directConsumers([
        fake('src/app/(dashboard)/x/page.tsx', "import { LOGISTICS_COMPANIES } from '@/lib/logistics'"),
      ]),
    ).toEqual(['src/app/(dashboard)/x/page.tsx'])
    expect(directConsumers([fake(SINGLE_SOURCE, 'export const LOGISTICS_COMPANIES = []')])).toEqual(
      [],
    )
    expect(
      directConsumers([fake('src/app/(dashboard)/x/page.tsx', "logisticsCompaniesFor('express')")]),
    ).toEqual([])

    // 别处再定义一份判定 ⇒ 红；只是调用/解构 ⇒ 不红
    expect(
      duplicateDeciders([fake('src/app/(dashboard)/x/page.tsx', 'function switchCarrier(a, b) {}')]),
    ).toEqual(['src/app/(dashboard)/x/page.tsx'])
    expect(
      duplicateDeciders([fake('src/app/(dashboard)/x/page.tsx', 'const switchCarrier = (a, b) => a')]),
    ).toEqual(['src/app/(dashboard)/x/page.tsx'])
    expect(
      duplicateDeciders([fake('src/app/(dashboard)/x/page.tsx', 'switchCarrier(a, b)')]),
    ).toEqual([])

    // 只在**注释**里提到常量名 ⇒ 不红（沿革说明不是直连消费）
    expect(
      directConsumers([
        fake(
          'src/app/(dashboard)/x/page.tsx',
          "/* 沿革：这里曾直接 map LOGISTICS_COMPANIES */\n// LOGISTICS_COMPANIES 曾在此直连\nconst y = 1",
        ),
      ]),
    ).toEqual([])
  })
})
