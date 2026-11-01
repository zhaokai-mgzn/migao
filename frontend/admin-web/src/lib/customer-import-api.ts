import request from './request'
import type { ApiResponse } from '@/types'
import type {
  CustomerImportAnalyzeResult,
  CustomerImportCommitResult,
  CustomerImportMapping,
  CustomerImportPreviewResult,
} from '@/types/customer-import'

// 客户主数据迁移（issue #8295）：三步都上传同一份文件（页面保留 File 对象并重复发送）。
// multipart 头与既有上传入口（productApi.importProducts / uploadApi）同形；
// analyze 等 AI 映射建议 120s，preview/commit 最多 2000 行 180s。
export const customerImportApi = {
  // —— 客户主数据迁移（issue #8295）：识别列 → 试运行 → 正式导入 ——
  // 三步都上传**同一份**文件（页面保留 File 对象并重复发送，后端不缓存临时文件）。
  // multipart 头与既有上传入口（productApi.importProducts / uploadApi）同形；
  // 解析 / 试运行 / 逐行写入都可能跑得久，显式放宽 30s 的全局超时：
  // - analyze 要等 AI 映射建议（120s）；
  // - preview 要解析整本 Excel + 逐行查重，commit 最多 2000 行（180s）。
  analyzeImport: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request.post<ApiResponse<CustomerImportAnalyzeResult>>(
      '/api/admin/customers/import/analyze',
      form,
      { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 120_000 },
    )
  },

  previewImport: (file: File, mapping: CustomerImportMapping, updateExisting: boolean) => {
    const form = new FormData()
    form.append('file', file)
    form.append('mapping', JSON.stringify(mapping))
    form.append('updateExisting', updateExisting ? 'true' : 'false')
    return request.post<ApiResponse<CustomerImportPreviewResult>>(
      '/api/admin/customers/import/preview',
      form,
      { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 180_000 },
    )
  },

  commitImport: (file: File, mapping: CustomerImportMapping, updateExisting: boolean) => {
    const form = new FormData()
    form.append('file', file)
    form.append('mapping', JSON.stringify(mapping))
    form.append('updateExisting', updateExisting ? 'true' : 'false')
    return request.post<ApiResponse<CustomerImportCommitResult>>(
      '/api/admin/customers/import/commit',
      form,
      { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 180_000 },
    )
  },
}
