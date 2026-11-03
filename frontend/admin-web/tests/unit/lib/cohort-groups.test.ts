// case_ids: MC-152
/**
 * 会话卡「来源组」**不许把服务端内部标签摆上屏**（issue #6461 = #6459 的同类形态）。
 *
 * ## 病（本判据的存在理由）
 *
 * 批次账读面在 `cohorts[]` 上给 `cohortLabel`：`切换后（采购入库）` / `存量导入（切换前历史包袱）`
 * / `来源未知` —— 商家读不懂（issue #6459 用户逐字「让新用户如何理解」），而 B 端两端
 * （桌面 `components/chat/BatchStockCard.tsx` + 移动 `frontend/bmini-app/.../BatchStockCard.tsx`）
 * **逐字渲染**它 ⇒ 内部口径词直接上屏。`user-copy-jargon-guard` 扫的是**源码字面量**，
 * 判不了「服务端下发的字符串」这一面（它自己的注释里也照实登记了这个边界）⇒ 必须有本判据。
 *
 * ## 判据（每条都能单独变红；红证逐条写在 `it` 里）
 *
 * | # | 判据 | 红证（怎么让它**单独**红） |
 * |---|---|---|
 * | ① | 每个**已知**服务端枚举都映射出**商家话术**：非空、不含英文/下划线（内部标识形态）、不含内部口径词、互不相同 | 把 `purchase` 的文案改回 `purchase` / 改回 `切换后（采购入库）` ⇒ 红 |
 * | ② | 映射表**键集与文案**都 == 服务端（**现取** `SavingMetricViews.java` 的 `COHORT_*` 常量与 `cohortLabel()` 的 case 文案 + `default` 兜底） | 在 Java 里加一个 `COHORT_RETURN = "return"` 而不补文案 ⇒ 红；只改任一侧**一个词**（文案分叉）⇒ 也红 |
 * | ③ | 认不出的键 / 空值 ⇒ **兜底话术**，且**不回显原始值** | 把 `COHORT_GROUP_FALLBACK` 从 `cohortGroupTitle` 里摘掉 ⇒ 红 |
 * | ④ | 源码面：两个会话卡的**渲染代码**里 `cohortLabel` 零出现（只许经映射表 → 文案），且两端都真的在调映射函数 | 把 `{cohortGroupTitle(cohort.cohort)}` 换回 `{cohort.cohortLabel}` ⇒ 红 |
 * | ⑤ | **同源**：bmini 的副本与本站单一真值逐项相等（bmini 是独立 npm 工程、不许 import 本站 TS） | 只改一侧的任一词 ⇒ 红 |
 *
 * ⚠️ 判据 ② 的语料 = **Java 源码**（真值在哪一侧：枚举定义在服务端）。加来源组是服务端的事，
 * 本判据把「前端没跟上」这种**静默漂移**变成红。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { COHORT_GROUP_FALLBACK, COHORT_GROUP_TITLES, cohortGroupTitle } from '@/lib/cohort-groups'

/** 服务端枚举真值（`COHORT_*` 常量 + 标签映射都在这里） */
const JAVA_SRC = resolve(
  __dirname,
  '../../../../../backend/admin-api/src/main/java/com/migao/admin/dto/SavingMetricViews.java',
)
/** bmini 的副本（独立 npm 工程，单一真值在本站这份） */
const BIMINI_MAP_SRC = resolve(
  __dirname,
  '../../../../../frontend/bmini-app/src/utils/cohort-groups.ts',
)
/** 两个会话卡的**渲染面**（admin-web 桌面 + bmini 移动） */
const CARD_SRCS = [
  ['frontend/admin-web/src/components/chat/BatchStockCard.tsx', resolve(__dirname, '../../../src/components/chat/BatchStockCard.tsx')],
  [
    'frontend/bmini-app/src/components/cards/BatchStockCard.tsx',
    resolve(__dirname, '../../../../../frontend/bmini-app/src/components/cards/BatchStockCard.tsx'),
  ],
] as const

/** 去掉行注释 / 块注释（JSX `{/* … *\/}` 也是块注释）—— 判据只看**渲染代码**，不看说明 */
function stripComments(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/[^\n]*/g, '$1')
}

/** 取服务端来源组枚举值（`public static final String COHORT_XXX = "值";`） */
function serverCohortValues(): string[] {
  const src = readFileSync(JAVA_SRC, 'utf8')
  return [...src.matchAll(/public static final String COHORT_[A-Z_]+\s*=\s*"([^"]+)"/g)].map((m) => m[1])
}

/** 现取 Java `cohortLabel()` 的「分组键 → 商家文案」与 `default` 兜底（与服务端**逐字**比对） */
function javaCohortTitles(): { titles: Record<string, string>; fallback: string } {
  const src = readFileSync(JAVA_SRC, 'utf8')
  const start = src.indexOf('public static String cohortLabel')
  expect(start, 'Java 里找不到 cohortLabel()（写法漂了？）').toBeGreaterThan(-1)
  const body = src.slice(start, start + 1600)
  const constToCode: Record<string, string> = {}
  for (const m of src.matchAll(/public static final String (COHORT_[A-Z_]+)\s*=\s*"([^"]+)"/g)) {
    constToCode[m[1]] = m[2]
  }
  const titles: Record<string, string> = {}
  for (const m of body.matchAll(/case (COHORT_[A-Z_]+) -> "([^"]+)"/g)) {
    const code = constToCode[m[1]]
    expect(code, `Java 里的 ${m[1]} 没解析出枚举值`).toBeTruthy()
    titles[code] = m[2]
  }
  const fallback = body.match(/default -> "([^"]+)"/)
  expect(fallback, 'Java cohortLabel() 缺 default 兜底（新增枚举会静默落到「无文案」）').toBeTruthy()
  return { titles, fallback: fallback![1] }
}

/** 从 TS 源码里取一份 `Record<string, string>` 字面量的键值对（口径同 `selling-method-same-source`） */
function recordEntries(src: string, name: string): Record<string, string> {
  const start = src.indexOf(name)
  expect(start, `源码里找不到 ${name}`).toBeGreaterThan(-1)
  const open = src.indexOf('{', start)
  const close = src.indexOf('}', open)
  expect(open, `${name} 的对象字面量起点`).toBeGreaterThan(-1)
  expect(close, `${name} 的对象字面量终点`).toBeGreaterThan(-1)
  const out: Record<string, string> = {}
  for (const line of src.slice(open + 1, close).split('\n')) {
    const m = line.match(/^\s*['"]?([\w-]+)['"]?\s*:\s*['"]([^'"]*)['"]\s*,?\s*$/)
    if (m) out[m[1]] = m[2]
  }
  return out
}

describe('会话卡来源组：服务端内部标签不上屏（issue #6461）', () => {
  it('① 已知服务端值 ⇒ 商家话术（非空 / 无英文与下划线 / 无内部口径词 / 互不相同）', () => {
    const keys = Object.keys(COHORT_GROUP_TITLES)
    // 反空跑：表被清空 ⇒ 「全部通过」是假绿
    expect(keys.length).toBeGreaterThanOrEqual(3)
    for (const key of keys) {
      const copy = COHORT_GROUP_TITLES[key]
      expect(copy.trim().length, `${key} 的文案太短（读的人看不出是什么）`).toBeGreaterThan(3)
      // 内部标识形态：英文枚举 / 下划线（`purchase` / `legacy_import` / `COHORT_X`）
      expect(copy, `${key} 的文案含英文或下划线 = 内部标识上屏`).not.toMatch(/[A-Za-z_]/)
      // 服务端内部口径词（issue #6459 被判红的那三个词）
      expect(copy, `${key} 的文案是服务端内部口径词`).not.toMatch(/切换后|存量导入|来源未知/)
    }
    // 两个来源组说成同一句话 ⇒ 读的人分不出「哪些是这个月采购的」
    expect(new Set(Object.values(COHORT_GROUP_TITLES)).size).toBe(keys.length)
  })

  it('② 映射表键集 == 服务端枚举全集（Java 现取；服务端加一组而前端没跟上 ⇒ 红）', () => {
    const serverValues = serverCohortValues()
    // 反空跑：正则没抽到东西时，下面的相等断言就是「空 vs 空」的假绿
    expect(serverValues.length, '从 SavingMetricViews.java 抽不到 COHORT_* 枚举（写法漂了？）').toBeGreaterThanOrEqual(3)
    expect(serverValues.length).toBe(new Set(serverValues).size)
    expect(Object.keys(COHORT_GROUP_TITLES).sort()).toEqual([...serverValues].sort())
    // 🔴 键集一致还不够：**文案**也必须逐字一致（服务端改一句而前端没跟 ⇒ 两端说两种话）
    const java = javaCohortTitles()
    expect(Object.keys(java.titles).length, 'Java cohortLabel() 的 case 分支没解析出来').toBeGreaterThanOrEqual(3)
    expect(COHORT_GROUP_TITLES).toEqual(java.titles)
    expect(COHORT_GROUP_FALLBACK).toBe(java.fallback)
  })

  it('③ 认不出的键 / 空值 ⇒ 兜底话术，**不回显原始值**', () => {
    // 兜底本身也得是商家话术
    expect(COHORT_GROUP_FALLBACK.trim().length).toBeGreaterThan(3)
    expect(COHORT_GROUP_FALLBACK).not.toMatch(/[A-Za-z_]/)
    expect(COHORT_GROUP_FALLBACK).not.toMatch(/切换后|存量导入|来源未知/)

    // 服务端将来新增的枚举 / 存量脏数据 / 缺值：一律兜底，不许把原值摆上屏
    for (const raw of ['switched', 'legacy_import', 'return', 'COHORT_NEW', '', '   ', null, undefined]) {
      const title = cohortGroupTitle(raw as string | null | undefined)
      expect(title, `输入 ${String(raw)} 没有走兜底`).toBe(COHORT_GROUP_FALLBACK)
      if (raw && raw.trim()) {
        expect(title.toLowerCase()).not.toContain(String(raw).toLowerCase())
      }
    }
    // 对照组：已知键走表（证明上面不是「恒回兜底」的假绿）
    expect(cohortGroupTitle('opening')).toBe(COHORT_GROUP_TITLES.opening)
  })

  it('④ 两个会话卡的渲染代码里 `cohortLabel` 零出现，且都真的经映射表', () => {
    for (const [label, path] of CARD_SRCS) {
      const code = stripComments(readFileSync(path, 'utf8'))
      expect(code, `${label}：服务端标签被直接渲染了（只许经 lib/cohort-groups 映射）`).not.toContain('cohortLabel')
      // 反向判别力：去掉映射调用 ⇒ 上面那条会「因为没有标签可渲染」而假绿
      expect(code, `${label} 没有调用 cohortGroupTitle（映射表没接线？）`).toContain('cohortGroupTitle(')
    }
  })

  it('⑤ 同源：bmini 副本与本站单一真值逐项相等（改一侧不改另一侧 ⇒ 红）', () => {
    const source = readFileSync(BIMINI_MAP_SRC, 'utf8')
    const bmini = recordEntries(source, 'COHORT_GROUP_TITLES')
    expect(Object.keys(bmini).length, 'bmini 副本一个键都没解析出来').toBeGreaterThanOrEqual(3)
    expect(bmini).toEqual(COHORT_GROUP_TITLES)
    // 兜底也同源（否则两端对「认不出的来源」说法不一）
    const fallback = source.match(/COHORT_GROUP_FALLBACK\s*=\s*'([^']*)'/)
    expect(fallback, 'bmini 副本里找不到 COHORT_GROUP_FALLBACK').toBeTruthy()
    expect(fallback![1]).toBe(COHORT_GROUP_FALLBACK)
  })
})
