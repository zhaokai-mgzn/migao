// case_ids: OR-058, UI-057
/**
 * 发货幂等键生成口径（`src/lib/client-request-id.ts`，issue #6935 / #6983 / #8013）。
 *
 * 这个键是「同一次发货」的身份证：客户端超时重试（HTTP 25s / 工具 30s 窗口客观存在）不得把运单号
 * 静默覆写 —— 服务端按 `(tenant_id, client_request_id)` 去重、同键回放首次结果。
 * 故本文件的判据只有两条，但都**会红**：
 *
 * ① **唯一**：连续多次生成不得重复（重复 = 两件不同的发货被服务端当成同一次，第二次直接回放第一次的
 *    结果 ⇒ 运单号丢失）；
 * ② **`crypto.randomUUID` 不可用时仍可用**（老浏览器 / 非安全上下文）：回落形态有 `req-` 前缀、
 *    且**仍然唯一**（不能退化成固定串 —— 那等于全站共用一个键）。
 *
 * 边界：本函数只负责「生成」。**何时生成 / 何时作废**（提交期间一次生成、失败复用、成功作废）是
 * 调用方（整页发货页 / 行内发货录入区）的职责，判据在各自的测试文件里，不在这里重复。
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { newClientRequestId } from '@/lib/client-request-id'

afterEach(() => {
  // 只还原**本文件**用 vi.stubGlobal 装上的替身（不要用 restoreAllMocks：它会把模块级 vi.fn()
  // 的实现清成 undefined，CI 的测试守卫会判红 —— 那条纪律见 tests/unit_ci_workflows/test_restore_all_mocks_scope.py）
  vi.unstubAllGlobals()
})

describe('newClientRequestId（发货幂等键）', () => {
  it('① 返回非空字符串，且连续 200 次互不相同', () => {
    const ids = Array.from({ length: 200 }, () => newClientRequestId())

    expect(ids.length).toBe(200)
    for (const id of ids) {
      expect(typeof id).toBe('string')
      expect(id.length).toBeGreaterThan(0)
    }
    // 唯一性 = 本函数存在的**唯一理由**（重复 ⇒ 服务端把两次发货当同一次）
    expect(new Set(ids).size).toBe(200)
  })

  it('② crypto.randomUUID 不可用 ⇒ 回落形态仍唯一（前缀 req-）', () => {
    vi.stubGlobal('crypto', {})

    const ids = Array.from({ length: 50 }, () => newClientRequestId())

    for (const id of ids) {
      expect(id.startsWith('req-')).toBe(true)
    }
    expect(new Set(ids).size).toBe(50)
  })
})
