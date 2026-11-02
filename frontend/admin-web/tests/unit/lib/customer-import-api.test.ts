// case_ids: MIG-009, MIG-010
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * 客户迁移请求层（issue #8295）：三端点都上传同一份文件，multipart 头 + 放宽超时；
 * mapping 是 target→source 的 JSON，updateExisting 落成字符串 "true"/"false"。
 *
 * 页面测试只证明「点了按钮会调用方法」；本文件锚**真正发给后端的 wire 形态** ——
 * 少一个 `mapping` / 把 boolean 直接塞进 FormData / 用默认 JSON 头，后端都会解析不到。
 */

const mockPost = vi.fn()

vi.mock('@/lib/request', () => ({
  default: {
    get: vi.fn(),
    post: (...args: unknown[]) => mockPost(...args),
    patch: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}))

import { customerImportApi } from '@/lib/customer-import-api'

const file = new File(['excel-bytes'], 'customers.xlsx', {
  type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
})
const mapping = { externalId: 0, displayName: 1 }

function call(index = 0) {
  const [path, form, config] = mockPost.mock.calls[index] as [
    string,
    FormData,
    { headers: Record<string, string>; timeout: number },
  ]
  return { path, form, config }
}

describe('customerImportApi 请求形态', () => {
  beforeEach(() => {
    mockPost.mockReset().mockResolvedValue({ data: { success: true, data: {} } })
  })

  it('analyze：POST multipart 文件，120s 超时', async () => {
    await customerImportApi.analyzeImport(file)

    const { path, form, config } = call()
    expect(path).toBe('/api/admin/customers/import/analyze')
    expect(form).toBeInstanceOf(FormData)
    expect(form.get('file')).toBe(file)
    expect(form.get('mapping')).toBeNull()
    expect(config).toEqual({
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120_000,
    })
  })

  it('preview：同文件 + mapping JSON + updateExisting=false，180s 超时', async () => {
    await customerImportApi.previewImport(file, mapping, false)

    const { path, form, config } = call()
    expect(path).toBe('/api/admin/customers/import/preview')
    expect(form.get('file')).toBe(file)
    expect(form.get('mapping')).toBe(JSON.stringify(mapping))
    expect(form.get('updateExisting')).toBe('false')
    expect(config).toEqual({
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 180_000,
    })
  })

  it('commit：同文件 + mapping JSON + updateExisting=true，180s 超时', async () => {
    await customerImportApi.commitImport(file, mapping, true)

    const { path, form, config } = call()
    expect(path).toBe('/api/admin/customers/import/commit')
    expect(form.get('file')).toBe(file)
    expect(form.get('mapping')).toBe(JSON.stringify(mapping))
    expect(form.get('updateExisting')).toBe('true')
    expect(config).toEqual({
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 180_000,
    })
  })
})
