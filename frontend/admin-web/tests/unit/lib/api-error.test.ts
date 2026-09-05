// case_ids: UI-024
import { describe, it, expect, vi, beforeEach } from 'vitest'

// Mock sonner 顶层（toastRequestError 依赖）
vi.mock('sonner', () => ({
  toast: { error: vi.fn(), dismiss: vi.fn() },
}))

import { toast } from 'sonner'
import {
  isErrorToastShown,
  markErrorToastShown,
  toastRequestError,
} from '@/lib/api-error'

describe('api-error（请求错误提示去重）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('isErrorToastShown', () => {
    it('未标记的错误返回 false', () => {
      expect(isErrorToastShown(new Error('x'))).toBe(false)
    })

    it('非对象/空值返回 false（防御，不抛错）', () => {
      expect(isErrorToastShown(null)).toBe(false)
      expect(isErrorToastShown(undefined)).toBe(false)
      expect(isErrorToastShown('string')).toBe(false)
      expect(isErrorToastShown(42)).toBe(false)
    })

    it('markErrorToastShown 标记后返回 true', () => {
      const err = new Error('库存不足')
      markErrorToastShown(err)
      expect(isErrorToastShown(err)).toBe(true)
    })
  })

  describe('markErrorToastShown', () => {
    it('对非对象静默忽略（不抛错）', () => {
      expect(() => markErrorToastShown(null)).not.toThrow()
      expect(() => markErrorToastShown('str')).not.toThrow()
    })
  })

  describe('toastRequestError', () => {
    it('错误已被拦截器提示过（已标记）→ 不再弹 fallback', () => {
      const err = new Error('商品库存不足')
      markErrorToastShown(err)
      toastRequestError(err, '确认付款失败')
      expect(toast.error).not.toHaveBeenCalled()
    })

    it('未标记的错误 → 弹 fallback', () => {
      const err = new Error('client-side error')
      toastRequestError(err, '确认付款失败')
      expect(toast.error).toHaveBeenCalledTimes(1)
      expect(toast.error).toHaveBeenCalledWith('确认付款失败')
    })

    it('已标记 + 传 loading toast id → dismiss 该 id，不弹 fallback（loading 不卡住）', () => {
      const err = { message: 'x' }
      markErrorToastShown(err)
      toastRequestError(err, '确认付款失败', { id: 'loading-1' })
      expect(toast.dismiss).toHaveBeenCalledWith('loading-1')
      expect(toast.error).not.toHaveBeenCalled()
    })

    it('未标记 + 传 loading toast id → toast.error 以 { id } 替换 loading', () => {
      const err = new Error('y')
      toastRequestError(err, '确认付款失败', { id: 'loading-2' })
      expect(toast.error).toHaveBeenCalledTimes(1)
      expect(toast.error).toHaveBeenCalledWith('确认付款失败', { id: 'loading-2' })
    })
  })
})