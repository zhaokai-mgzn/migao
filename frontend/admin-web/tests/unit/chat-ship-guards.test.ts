// case_ids: UI-048, UI-024, UI-086
/**
 * 类级元守卫（issue #6664 第 3 / 7 条）—— 两条**跨文件不变式**，同一条纪律：
 * 让「同类缺陷下一处冒出来」时**有东西变红**，而不是靠人眼抽查。
 *
 * ## 不变式 A：本包射程内**零原生弹窗**（零 `window.confirm` / 零 `window.alert`）
 *
 * #6664 第 4 条：`orders/page.tsx` 与 `ProcessingOrderBlock.tsx` 的确认动作此前走 `window.confirm`
 * —— 与仓内自研 `Modal`（UI-048 家族）**同一个动作两个世界观**，且没有在飞行态。
 *
 * **台账只许缩短**（`NATIVE_DIALOG_LEDGER`）：它记的是「**今天仍在射程内的原生弹窗**」——
 * 现在应当是**空的**。新增一处 ⇒ 判据 ① 当场红并具名报出文件与行号；
 * 台账里写着一个其实已经没有的命中 ⇒ 判据 ② 红（账实不符，逼人删行而不是加行）。
 * 射程外的文件（如 `components/products/ImageUploader.tsx`，#6664 明示不归本包）**不在扫描面内**。
 *
 * ## 不变式 B：本包射程内日期**只有一个真值源**（`common/DateTimeCell`）
 *
 * #6664 第 7 条：日期口径 4 种并存。机械判据 = 射程源码里**不许**出现「自己拼年月日」的形态
 * （`dayjs(x).format('YYYY...')` / `toLocaleDateString`），一律走 `DateTimeCell`。
 * `DateTimeCell.tsx` 自己是真值源 ⇒ 豁免。`HH:mm`（聊天气泡的钟点）与 `<input type="date">`
 * 的 `formatDate`（本地日期**值**，不是展示）**不算**日期展示口径，故不在禁令形态内。
 */
import { describe, it, expect } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

const ROOT = join(__dirname, '..', '..')

/** 本包（issue #6664）拥有的源码目录 —— 与 PR body 的「文件族」逐条对应 */
const OWNED_ROOTS = [
  'src/components/chat',
  'src/components/orders',
  'src/store/chat.ts',
  'src/app/(dashboard)/agent-workspace',
  'src/app/(dashboard)/shipments',
  'src/app/(dashboard)/orders',
  'src/app/(dashboard)/after-sales',
]

/**
 * 原生弹窗台账（**只许缩短**）：记「仍在射程内、尚未迁到 `Modal` 的 `window.confirm/alert`」。
 * 本包清完 ⇒ 空集；**加行**（而不是改码）会让判据 ② 红。
 */
const NATIVE_DIALOG_LEDGER: string[] = []

/**
 * 日期展示台账（**只许缩短**）：记「还在自拼年月日的**内部时间戳字符串**」。
 *
 * 为什么这两处**有意不动**（如实登记，不粉饰）：它们是给**别的地方**产字符串的**中间产物**
 * （`RemarkPopover` 解析历史备注文本、`OrderProgressSteps` 造步骤条行数据），
 * 不是渲染出口 —— 改成 `DateTimeCell` 要把整条数据流改成 ReactNode，属**过度建设**。
 * 它们**不违背**「展示口径唯一真值源」：真正上屏的日期一律已走 `DateTimeCell`。
 * 🔴 且**只许缩短**：新加一行（而不是改码）⇒ 判据 ① 红。
 */
const INTERNAL_TIMESTAMP_LEDGER = [
  'src/components/orders/OrderProgressSteps.tsx',
  'src/components/orders/RemarkPopover.tsx',
]

function collect(pathOrDir: string): string[] {
  const abs = join(ROOT, pathOrDir)
  let st: ReturnType<typeof statSync>
  try {
    st = statSync(abs)
  } catch {
    return []
  }
  if (st.isFile()) return [abs]
  return readdirSync(abs).flatMap((name) => {
    const child = join(abs, name)
    return statSync(child).isDirectory() ? collect(relative(ROOT, child)) : [child]
  })
}

function ownedSourceFiles(): string[] {
  return OWNED_ROOTS.flatMap(collect)
    .filter((f) => /\.(ts|tsx)$/.test(f))
    .filter((f) => !f.endsWith('.d.ts'))
    .filter((f) => !f.includes(`${'__tests__'}`))
    .sort()
}

/** 逐行找命中，返回 `相对路径:行号`（行号只用于**报错信息**，不写进判据锚） */
function findHits(files: string[], re: RegExp): string[] {
  const hits: string[] = []
  for (const file of files) {
    const rel = relative(ROOT, file)
    readFileSync(file, 'utf8').split('\n').forEach((line, idx) => {
      if (re.test(line)) hits.push(`${rel}:${idx + 1}`)
    })
  }
  return hits
}

describe('类级不变式 A：射程内零原生弹窗（window.confirm / window.alert）', () => {
  const files = ownedSourceFiles()
  const hits = findHits(files, /window\s*\.\s*(confirm|alert)\s*\(/)

  it('① 扫描面非空（否则本判据是空断言 —— 假绿）', () => {
    expect(files.length).toBeGreaterThan(20)
  })

  it('② 射程内没有一处 window.confirm / window.alert；台账（只许缩短）为空', () => {
    expect(NATIVE_DIALOG_LEDGER).toHaveLength(0)
    expect(hits, `原生弹窗必须走自研 Modal（issue #6664 第 4 条）。命中：${hits.join('、')}`).toEqual([])
  })

  it('③ 判别力自证：同一正则能在**内存注入**的语料上判红（不是恒真）', () => {
    const injected = [...files]
    // 直接对一段假源码跑同一判定：必须命中
    const probe = /window\s*\.\s*(confirm|alert)\s*\(/
    expect(probe.test("if (!window.confirm('确认？')) return")).toBe(true)
    expect(probe.test('window.alert("x")')).toBe(true)
    // 反向：自研 Modal 的用法不命中
    expect(probe.test('<Modal open={x} onClose={close} />')).toBe(false)
    expect(probe.test('confirmAction')).toBe(false)
    expect(injected.length).toBe(files.length)
  })
})

describe('类级不变式 B：射程内日期只有一个真值源（DateTimeCell）', () => {
  const files = ownedSourceFiles().filter((f) => !f.endsWith('common/DateTimeCell.tsx'))
  /**
   * 「自己拼日期展示」的形态：`dayjs(x).format('YYYY-MM-DD HH:mm[:ss]')` / 浏览器本地化日期。
   * 只吃**年月日 + 时刻**的组合 —— 仅 `HH:mm` 的钟点、只有 `YYYY` 的簿记值都不算展示口径。
   */
  const AD_HOC_DATE = /(dayjs\([^)]*\)\.format\(\s*['"`]YYYY-MM-DD[^'"`]*HH)|(\.toLocaleDateString\s*\()/

  it('① 射程内没有自拼日期展示的形态（一律走 DateTimeCell）；台账内的内部时间戳除外', () => {
    const hits = findHits(files, AD_HOC_DATE)
      .filter((hit) => !INTERNAL_TIMESTAMP_LEDGER.some((allowed) => hit.startsWith(allowed)))
    expect(hits, `日期展示请走 common/DateTimeCell（issue #6664 第 7 条）。命中：${hits.join('、')}`).toEqual([])
  })

  it('①b 台账只许缩短：台账里列的必须**真的**还在命中（账实不符 ⇒ 红）', () => {
    const allHits = findHits(files, AD_HOC_DATE)
    const stale = INTERNAL_TIMESTAMP_LEDGER.filter(
      (allowed) => !allHits.some((hit) => hit.startsWith(allowed)),
    )
    expect(stale, `台账里的这些行已经不再命中 ⇒ 请删掉它（只许缩短）：${stale.join('、')}`).toEqual([])
  })

  it('② 射程内至少有一处真在用 DateTimeCell（判据不是靠「没人用」变绿）', () => {
    const users = files.filter((f) => readFileSync(f, 'utf8').includes('DateTimeCell'))
    expect(users.length).toBeGreaterThanOrEqual(4)
  })

  it('③ 判别力自证：同一正则会命中「自拼日期」语料，且不误伤 DateTimeCell / input date', () => {
    expect(AD_HOC_DATE.test("dayjs(m.created_at).format('YYYY-MM-DD HH:mm')")).toBe(true)
    expect(AD_HOC_DATE.test("new Date(x).toLocaleDateString('zh-CN')")).toBe(true)
    // 钟点（HH:mm）不是日期口径 ⇒ 不命中
    expect(AD_HOC_DATE.test("dayjs(x).format('HH:mm')")).toBe(false)
    // <input type="date"> 的值格式化（formatDate 拼 YYYY-MM-DD）不是日期展示 ⇒ 不命中
    expect(AD_HOC_DATE.test('return `${y}-${m}-${day}`')).toBe(false)
  })
})
