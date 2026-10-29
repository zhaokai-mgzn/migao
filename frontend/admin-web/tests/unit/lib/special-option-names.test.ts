// case_ids: OR-035
/**
 * 特殊选项的**布/纱派生族**口径（issue #8007 立机制；issue #8108 接入「绑带」族）—— 纯函数判据。
 *
 * 用户逐字（#8007，2026-10-28）：「特殊选项里的这两项要改，只需要展示**余料带回**即可，后面的
 * `-布` 和 `-纱` 应该是默认**跟随订单套行的帘种**来决定的，这样语义更清晰」
 * 「这个规则要**适用于全系统中**」。
 *
 * 用户逐字（#8108，2026-10-29）：「把这两项也合并成一个绑带选项，布/纱是跟随帘种来确定的」
 * （「这两项」= 特殊选项里的 `布绑带` / `纱绑带`）。
 *
 * 判据（每条都能红）：
 * 1. **录入/展示词表**只出语义名（19 项 join key → **17** 个可选项：不含 `-布` / `-纱`，
 *    也不含 `布绑带` / `纱绑带`）；
 * 2. **落库键按帘种派生**：缺省 / 布帘 / 帘头 ⇒ cloth 键，纱帘 ⇒ sheer 键；非族选项原样；
 * 3. **展示反向收敛**：`craft-display` 的「特殊选项」行不出现派生键；
 * 4. 🔴 **类级元守卫**：`SPECIAL_OPTIONS` 里任何成对的布/纱变体名（`X-布` / `X-纱` 后缀、
 *    `布X` / `纱X` 前缀两种形态）都**必须**登记在本派生族里 —— 以后新增同类变体而忘了登记
 *    ⇒ 本判据红（不是静默回到「人选材料」）；
 * 5. **非族名不折叠**：`加立边` / `加logo条` / `余料做绑带` 是**独立**选项名（各有独立工序），
 *    不得被当族成员。
 */
import { describe, it, expect } from 'vitest'
import {
  SPECIAL_OPTIONS,
  SPECIAL_OPTION_FAMILIES,
  derivedSpecialOptionValues,
  resolveSpecialOptionName,
  selectedSpecialOptionDisplayNames,
  specialOptionDisplayName,
  specialOptionDisplayOptions,
  specialOptionFamilyOf,
} from '@/lib/order-craft-fields'
import { craftSpecRows } from '@/lib/craft-display'

/** 从展示行里取某个标签的值（与 `craft-display.test.ts` 同款） */
function rowValue(rows: { label: string; value: string }[], label: string): string | undefined {
  return rows.find((row) => row.label === label)?.value
}

describe('特殊选项布/纱派生族（issue #8007 / #8108）', () => {
  it('录入/展示词表：19 项 join key 折叠成 17 个语义选项，且不含 -布 / -纱 / 布绑带 / 纱绑带', () => {
    const display = specialOptionDisplayOptions()
    expect(display).toHaveLength(17)
    // 两族的语义名都沿用 join key 清单里的首次出现位置
    expect(display.slice(0, 2)).toEqual(['余料带回', '绑带'])
    expect(display.filter((name) => /-(布|纱)$/.test(name))).toEqual([])
    expect(display).not.toContain('布绑带')
    expect(display).not.toContain('纱绑带')
    // 其余项一个不少（只合并了这两族）
    expect(new Set(display)).toEqual(new Set(SPECIAL_OPTIONS.map(specialOptionDisplayName)))
  })

  it('落库键派生：缺省 / 布帘 / 帘头 ⇒ cloth 键；纱帘 ⇒ sheer 键（两族同口径）', () => {
    expect(resolveSpecialOptionName('余料带回')).toBe('余料带回-布')
    expect(resolveSpecialOptionName('余料带回', '布帘')).toBe('余料带回-布')
    expect(resolveSpecialOptionName('余料带回', '帘头')).toBe('余料带回-布')
    expect(resolveSpecialOptionName('余料带回', '纱帘')).toBe('余料带回-纱')

    expect(resolveSpecialOptionName('绑带')).toBe('布绑带')
    expect(resolveSpecialOptionName('绑带', '布帘')).toBe('布绑带')
    expect(resolveSpecialOptionName('绑带', '帘头')).toBe('布绑带')
    expect(resolveSpecialOptionName('绑带', '纱帘')).toBe('纱绑带')

    // 已带派生键的旧值 ⇒ 按目标帘种重新派生（切帘体时不会留下跨帘种的旧键）
    expect(resolveSpecialOptionName('余料带回-布', '纱帘')).toBe('余料带回-纱')
    expect(resolveSpecialOptionName('布绑带', '纱帘')).toBe('纱绑带')
    expect(resolveSpecialOptionName('纱绑带', '布帘')).toBe('布绑带')
  })

  it('非族选项原样落库（不因帘种改名）；勾选整份派生保持其余项不变', () => {
    expect(resolveSpecialOptionName('加铅块', '纱帘')).toBe('加铅块')
    expect(derivedSpecialOptionValues(['余料带回', '加铅块'], '纱帘')).toEqual([
      '余料带回-纱',
      '加铅块',
    ])
    expect(derivedSpecialOptionValues(['余料带回', '绑带'], '布帘')).toEqual([
      '余料带回-布',
      '布绑带',
    ])
    expect(derivedSpecialOptionValues(['绑带', '加铅块'], '纱帘')).toEqual(['纱绑带', '加铅块'])
  })

  it('展示反向收敛：存量派生键显示为语义名；同族两键并存折叠成一个', () => {
    expect(specialOptionDisplayName('余料带回-布')).toBe('余料带回')
    expect(specialOptionDisplayName('余料带回-纱')).toBe('余料带回')
    expect(specialOptionDisplayName('布绑带')).toBe('绑带')
    expect(specialOptionDisplayName('纱绑带')).toBe('绑带')
    expect(specialOptionDisplayName('加铅块')).toBe('加铅块')
    expect(selectedSpecialOptionDisplayNames(['余料带回-布', '余料带回-纱', '加铅块'])).toEqual([
      '余料带回',
      '加铅块',
    ])
    expect(selectedSpecialOptionDisplayNames(['布绑带', '纱绑带', '加铅块'])).toEqual([
      '绑带',
      '加铅块',
    ])
  })

  it('🔴 展示面（craft-display）：订单详情 / 加工单 / 打印 / 水洗唛都读它 ⇒ 不出现派生键', () => {
    expect(rowValue(craftSpecRows({ specialOptions: ['余料带回-布'] }), '特殊选项')).toBe('余料带回')
    expect(rowValue(craftSpecRows({ special_options: ['余料带回-纱'] }), '特殊选项')).toBe('余料带回')
    expect(rowValue(craftSpecRows({ specialOptions: ['布绑带'] }), '特殊选项')).toBe('绑带')
    expect(rowValue(craftSpecRows({ special_options: ['纱绑带'] }), '特殊选项')).toBe('绑带')
  })

  it('非族名不折叠：加立边 / 加logo条 / 余料做绑带 是独立选项名（类级防误伤）', () => {
    expect(specialOptionFamilyOf('加立边')).toBeNull()
    expect(specialOptionFamilyOf('加logo条')).toBeNull()
    // 名字里也含「绑带」字样，但它是一个**独立**选项（自己一道工序，不跟随帘种）
    expect(specialOptionFamilyOf('余料做绑带')).toBeNull()
    expect(specialOptionFamilyOf('余料带回')).toBe('余料带回')
    expect(specialOptionFamilyOf('余料带回-布')).toBe('余料带回')
    expect(specialOptionFamilyOf('余料带回-纱')).toBe('余料带回')
    expect(specialOptionFamilyOf('绑带')).toBe('绑带')
    expect(specialOptionFamilyOf('布绑带')).toBe('绑带')
    expect(specialOptionFamilyOf('纱绑带')).toBe('绑带')
  })

  it('🔴 类级元守卫：清单里成对的布/纱变体（后缀与前缀两种形态）都必须登记在派生族里', () => {
    // 形态 A：`X-布` / `X-纱` 后缀对
    const unregisteredSuffix = SPECIAL_OPTIONS.filter(
      (name) => /-(布|纱)$/.test(name) && specialOptionFamilyOf(name) === null
    )
    expect(unregisteredSuffix).toEqual([])
    // 形态 B：`布X` / `纱X` 前缀对（「绑带」族就是这个形态 —— 只查后缀会漏掉它）
    const unregisteredPrefix = SPECIAL_OPTIONS.filter((name) => {
      if (specialOptionFamilyOf(name) !== null) return false
      const matched = /^([布纱])(.+)$/.exec(name)
      if (!matched) return false
      const sibling = (matched[1] === '布' ? '纱' : '布') + matched[2]
      return (SPECIAL_OPTIONS as readonly string[]).includes(sibling)
    })
    expect(unregisteredPrefix).toEqual([])
    // 族登记表的两个派生键都必须真在 join key 清单里（登记了却不在册 = 永远查不到）
    for (const variants of Object.values(SPECIAL_OPTION_FAMILIES)) {
      for (const name of [variants.cloth, variants.sheer]) {
        expect(SPECIAL_OPTIONS as readonly string[]).toContain(name)
      }
    }
  })
})
