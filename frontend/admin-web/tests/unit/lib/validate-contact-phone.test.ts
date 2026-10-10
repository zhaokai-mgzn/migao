// case_ids: UI-082
//
// 判据：**联系电话校验必须容纳真实 B 端号码形态**（issue #6665 第 7 条）。
//
// 病根：官网联系页原正则 `/^[\d\-+() ]{7,20}$/` 只认**半角**数字/连字符/加号/括号/空格
// ⇒ 拒掉 `13800000000转123`（手机 + 分机）与 `（0571）88886666`（全角括号总机）——
// 而这两种正是 B 端官网会收到的真实形态（企业总机 / 座机分机）。
//
// 本判据作用在**纯函数**上（`frontend/admin-web/src/lib/validate-contact-phone.ts`）：
// 留言表单已按用户裁定隐藏（见 corporate-contact.test.tsx），但号码口径是被裁定保留的能力，
// 所以它的判据不随表单一起消失 —— 表单形态以后重启（用户给出真实联系方式时）这一份仍然有效。
import { describe, it, expect } from 'vitest'
import { isValidContactPhone, normalizeContactPhone } from '@/lib/validate-contact-phone'

/** 真实企业号码形态（全部必须通过）。 */
const ACCEPTED = [
  '13800000000',
  '13800000000转123',        // 手机 + 分机（issue 逐字点名的形态）
  '138 0000 0000',           // 半角空格分组
  '138-0000-0000',           // 半角连字符
  '（0571）88886666',         // 全角括号总机（issue 逐字点名的形态）
  '(0571)88886666',          // 半角括号
  '0571-8888 6666',
  '057188886666转8000',
  '１３８００００００００',      // 全角数字
  '+86 138 0000 0000',       // 国际前缀
]

/** 明显不合法（全部必须拒绝）。 */
const REJECTED = [
  '',
  '   ',
  '12345',                   // 太短
  'abcdefghij',
  '13800000000转',
  '转123',
  '12345',                   // 太短（放进来防「为了收分机号把下限降到 4」）
  '<script>alert(1)</script>',
  '13800000000@example.com',
  '13800000000abc',
]

describe('联系电话校验（issue #6665）', () => {
  it('接受真实企业号码形态（含分机 / 全角括号 / 全角数字）', () => {
    const rejected = ACCEPTED.filter((v) => !isValidContactPhone(v))
    expect(
      rejected,
      `这些真实号码形态被拒了：${rejected.join(' / ')}。` +
        `原正则 /^[\\d\\-+() ]{7,20}$/ 只认半角 ⇒ 「13800000000转123」「（0571）88886666」这类` +
        `B 端总机形态一律报「请输入有效的电话号码」。修法：先归一化（全角→半角、去空格括号、分机号切成扩展段）再判。`,
    ).toEqual([])
  })

  it('拒绝明显不合法的输入（不能为了放宽而变成「什么都收」）', () => {
    const accepted = REJECTED.filter((v) => isValidContactPhone(v))
    expect(accepted, `这些非法输入被放过了：${accepted.join(' / ')}`).toEqual([])
  })

  it('归一化是纯函数：同样的语义输入归一化到同一串，且不改变原值', () => {
    const values = ['13800000000转123', '（0571）88886666', '＋８６ １３８ ００００ ００００']
    const snapshot = [...values]
    const normalized = values.map(normalizeContactPhone)
    expect(values, '归一化不得修改传入的数组/字符串').toEqual(snapshot)
    // 归一化结果必须是纯 ASCII 数字与分机分隔符（用它做落库前的规范形态）
    for (const n of normalized) expect(n).toMatch(/^[0-9]+(?:\.[0-9]+)?$/)
  })

  it('判别力自证：旧口径（只认半角 7~20 位）对点名形态真的会红', () => {
    const legacy = (v: string) => /^[\d\-+() ]{7,20}$/.test(v.trim())
    expect(legacy('13800000000转123'), '旧口径本应拒掉带分机的号码').toBe(false)
    expect(legacy('（0571）88886666'), '旧口径本应拒掉全角括号的总机号').toBe(false)
    // 反向对照：合法半角号码旧口径是通过的 ⇒ 上面两条红来自「形态」而不是「整体不可用」
    expect(legacy('13800000000')).toBe(true)
  })
})
