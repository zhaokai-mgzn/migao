/**
 * 敏感信息脱敏工具（C 端展示层，对齐后端 LogSanitizer）
 */

/** 手机号脱敏：保留前 3 后 4，如 13800138000 → 138****8000 */
export function maskPhone(phone?: string | null): string {
  const p = (phone || '').trim()
  if (!p) return ''
  if (p.length >= 7) return `${p.slice(0, 3)}****${p.slice(-4)}`
  return '****'
}

/** 对任意文本中的手机号进行脱敏（用于聊天记录展示，如用户转述他人手机号） */
export function maskPhoneInText(text: string): string {
  return (text || '').replace(/(1[3-9]\d{9})/g, (m) => maskPhone(m))
}

export default { maskPhone, maskPhoneInText }
