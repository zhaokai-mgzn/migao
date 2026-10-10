// case_ids: UI-057, UI-058
/**
 * `server-reason.ts` 的判据（issue #6663）——「服务端拒绝理由 ⇒ 商家可读行」的口径守卫。
 *
 * ## 这个文件的判别力锚在哪（不是为了让闸变绿的空壳）
 *
 * 本模块只做**两件事**，判据就逐条钉这两件事；并且**每条断言都配一个「坏形态会红」的对照**：
 *
 * 1. **服务端给的 `message` 用服务端的**（不改写语义、不自己编话术、不静默丢弃被拒的项）；
 * 2. **只在服务端没给理由时才回落**到调用方的 `fallback`（不猜病因）；
 * 3. **内部标识不上屏**：`field` 丢掉、JSON 示例整段去掉、残留字段名擦成「该项」。
 *
 * 🔴 **红证**（把实现改成这些形态，本文件当场判红 —— 每条断言后括号里注明是哪一条）：
 * - **直接透传服务端原文**（不擦字段名 / 不丢 `field`）⇒ 「字段名与 JSON 示例不上屏」两组红；
 * - **把回落文案写死**（不管 `fallback` 传什么都返回同一句）⇒ 「回落用调用方那句」红；
 * - **只认 `details[0]`**（丢其余条目）⇒ 「逐条都在且顺序不变」红；
 * - **服务端给了 `message` 却仍去回落** ⇒ 「有服务端理由就不回落」红。
 */
import { describe, expect, it } from 'vitest'

import { merchantReasonsOf, stripInternalTokens } from '@/lib/settings/server-reason'

/** 服务端 422 的真实信封形状（`{ success:false, error:{ message, details } }`） */
const envelope = (error: unknown) => ({ response: { data: { error } } })

describe('stripInternalTokens：只擦内部标识，不动语义', () => {
  it('JSON / 数组示例整段去掉（商家照着 `["report","order"]` 填不了任何东西）', () => {
    expect(stripInternalTokens('必须是数组（如 ["report","order"]）')).toBe('必须是数组')
    expect(stripInternalTokens("必须是数组(如 ['a','b'])")).toBe('必须是数组')
  })

  it('snake_case / camelCase 字段名擦成「该项」（含 `item_key = …` 的空白边界）', () => {
    expect(stripInternalTokens('小件配置缺少 item_key（= 该小件对应的工序名）')).toBe(
      '小件配置缺少该项（= 该小件对应的工序名）',
    )
    expect(stripInternalTokens('必须为正数（item_key = 「绑带-布」）')).toBe(
      '必须为正数（该项 = 「绑带-布」）',
    )
    expect(stripInternalTokens('lengthM 必须大于 0')).toBe('该项 必须大于 0')
  })

  it('lookbehind：`params.x` 只擦尾巴，不把前缀一起切掉（不在词中间误伤）', () => {
    expect(stripInternalTokens('params.oversize_height_threshold 超了')).toBe('params.该项 超了')
    // 纯小写单段标识符（不是 snake/camel）不动 —— 那不是本模块的射程
    expect(stripInternalTokens('必须是数组')).toBe('必须是数组')
  })

  it('掏空后不留下空括号（`（item_key）` ⇒ 整段连括号去掉）', () => {
    expect(stripInternalTokens('缺少 item_key（item_key）')).toBe('缺少该项')
    expect(stripInternalTokens('校验失败（）')).toBe('校验失败')
  })

  it('好文案**一字不动**（判别力自证的另一侧：不许把正常中文改写掉）', () => {
    const good = '每一行都要填用料长与用料宽，且都为正数'
    expect(stripInternalTokens(good)).toBe(good)
  })
})

describe('merchantReasonsOf：服务端给理由就用服务端的', () => {
  it('逐条保留服务端 `message`（**不改写语义**），且顺序不变、不合并', () => {
    const lines = merchantReasonsOf(
      envelope({
        message: '工人端页面配置有 2 处不合法',
        details: [
          { field: 'pages', message: '不能为空' },
          { field: 'pages[3]', message: '不是工人端页面键：stock' },
        ],
      }),
      '保存失败（请检查页面清单后重试）',
    )
    expect(lines).toEqual(['不能为空', '不是工人端页面键：stock'])
    // 🔴 红证①：`details[0]` 之外的条目被丢掉 ⇒ 这里只剩 1 条而红
    expect(lines).toHaveLength(2)
  })

  it('🔴 内部标识不上屏：`field` 丢掉、字段名与 JSON 示例不在结果里（红证②：直接透传原文必红）', () => {
    const lines = merchantReasonsOf(
      envelope({
        message: '工人端页面配置有 2 处不合法',
        details: [
          { field: 'pages', message: '必须是数组（如 ["report","order"]）' },
          { field: 'items[0].lengthM', message: '必须为正数（item_key = 「绑带-布」）' },
        ],
      }),
      '保存失败',
    )
    const joined = lines.join('；')
    // 服务端语义在
    expect(joined).toContain('必须是数组')
    expect(joined).toContain('必须为正数')
    // 内部标识一个都不在
    expect(joined).not.toContain('pages')
    expect(joined).not.toContain('items[')
    expect(joined).not.toContain('lengthM')
    expect(joined).not.toContain('item_key')
    expect(joined).not.toContain('["')
    expect(joined).not.toContain('"report"')
    // 也不许把 `field` 当理由贴出来（`pages：必须是数组` 那种形态）
    expect(lines.some((l) => l.startsWith('pages'))).toBe(false)
  })

  it('`details` 里 message 为空的条目被丢掉，其余照旧（不静默丢**有效**条目）', () => {
    const lines = merchantReasonsOf(
      envelope({
        details: [{ field: 'a' }, { field: 'b', message: '这一项要重选' }, { message: '' }],
      }),
      '保存失败',
    )
    expect(lines).toEqual(['这一项要重选'])
  })
})

describe('merchantReasonsOf：只在服务端没给理由时才回落', () => {
  const FALLBACK = '保存失败（请检查页面清单后重试）'

  it('🔴 回落用**调用方那句**（红证③：把回落文案写死 ⇒ 这里必红）', () => {
    for (const broken of [undefined, null, {}, { response: {} }, { response: { data: {} } }]) {
      expect(merchantReasonsOf(broken, FALLBACK)).toEqual([FALLBACK])
    }
    // 换个调用方、换一句话 ⇒ 回落的必须是它自己那句（写死的实现过不了这条）
    expect(merchantReasonsOf(undefined, '小件配置保存失败')).toEqual(['小件配置保存失败'])
  })

  it('`details` 空数组 ⇒ 回落（空数组不是「服务端说了理由」）', () => {
    expect(merchantReasonsOf(envelope({ details: [] }), FALLBACK)).toEqual([FALLBACK])
  })

  it('`details` 非数组 ⇒ 回落（形状不对不猜）', () => {
    expect(merchantReasonsOf(envelope({ details: 'pages 不对' }), FALLBACK)).toEqual([FALLBACK])
  })

  it('🔴 有服务端 `message` 就不回落（红证④：该用服务端理由却回落 ⇒ 这里红）', () => {
    expect(merchantReasonsOf(envelope({ message: '配置有 1 处不合法' }), FALLBACK)).toEqual([
      '配置有 1 处不合法',
    ])
    // 摘要里的 snake_case 标识符同样要擦掉（不能因为走的是摘要路径就放行内部标识）
    // 实例：`RemnantService` 直接 `validationError("小件配置缺少 item_key（= …）")`（**无 details**）⇒ 走这条路径
    expect(merchantReasonsOf(envelope({ message: '小件配置缺少 item_key（= 该小件对应的工序名）' }), FALLBACK))
      .toEqual(['小件配置缺少该项（= 该小件对应的工序名）'])
  })

  /**
   * 🔴 **边界（照实登记，别把它读成漏网）**：本模块只擦**可机械识别的内部标识** ——
   * `snake_case` / `camelCase` 标识符与 JSON 代码示例。
   *
   * **单个小写英文词**（如 `pages`）**有意不擦**：
   * ① 它与「商家自己填的值」**无法机械区分** —— 同一个位置的 `stock`（`不是工人端页面键：stock`）
   *    是商家**输入的内容**，擦掉就把可行动的提示改坏了；
   * ② 实务上不会漏：本包射程内两个服务的 422 **摘要**分别是
   *    「工人端页面配置有 N 处不合法」（`WorkerPageConfigService.java:173`，不带字段名）
   *    与 `小件配置缺少 item_key（…）`（`RemnantService.java:292`，带 snake_case ⇒ 已被上面那条擦掉）
   *    ⇒ **字段名只出现在 `details[].field` 与 `details[].message`**，而 `field` 被整个丢掉。
   */
  it('边界：单个小写词不擦（那是商家输入的值，不是标识符）—— 防止把可行动提示改坏', () => {
    expect(stripInternalTokens('不是工人端页面键：stock')).toBe('不是工人端页面键：stock')
    expect(stripInternalTokens('pages 必须是数组')).toBe('pages 必须是数组')
  })

  it('`details` 全为无效条目、但有 `message` ⇒ 用摘要（不是回落）', () => {
    expect(merchantReasonsOf(envelope({ message: '有 1 处不合法', details: [{}] }), FALLBACK)).toEqual([
      '有 1 处不合法',
    ])
  })
})
