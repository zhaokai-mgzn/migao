// case_ids: CH-011
/**
 * mask 脱敏工具测试（数据安全：手机号脱敏展示）
 */
import { maskPhone, maskPhoneInText } from '../src/utils/mask'

describe('mask', () => {
  it('maskPhone 保留前 3 后 4', () => {
    expect(maskPhone('13800138000')).toBe('138****8000')
  })

  it('maskPhone 短号码返回 ****', () => {
    expect(maskPhone('12345')).toBe('****')
  })

  it('maskPhone 空值返回空串', () => {
    expect(maskPhone('')).toBe('')
    expect(maskPhone(null)).toBe('')
    expect(maskPhone(undefined)).toBe('')
  })

  it('maskPhoneInText 脱敏文本中的手机号', () => {
    expect(maskPhoneInText('请联系 13800138000 确认')).toBe('请联系 138****8000 确认')
  })

  it('maskPhoneInText 无手机号时不改动', () => {
    expect(maskPhoneInText('没有敏感信息')).toBe('没有敏感信息')
  })
})
