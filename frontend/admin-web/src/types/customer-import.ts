// ========== 客户主数据迁移（issue #8295）==========
// 后端三个端点（analyze / preview / commit）的响应形状，字段与契约逐字对齐。
// 页面只负责展示与把用户确认后的映射回传，不在前端重算任何校验结论。

/** 可映射的客户字段（后端下发；`required` = 这一列不映射就不许试运行） */
export interface CustomerImportField {
  key: string
  label: string
  required: boolean
  type: string
  aliases: string[]
}

/** AI 对某个源列的建议（`sourceIndex` 是 headers / samples 的下标） */
export interface CustomerImportSuggestion {
  sourceIndex: number
  sourceHeader: string
  targetField: string
  confidence: number
  reason: string
}

/** 上传后识别结果：表头、示例值、总行数、可映射字段与 AI 建议 */
export interface CustomerImportAnalyzeResult {
  headers: string[]
  samples: string[][]
  totalRows: number
  fields: CustomerImportField[]
  suggestions: CustomerImportSuggestion[]
  /** AI 列识别不可用（降级）—— 页面必须提示人工确认映射 */
  aiDegraded: boolean
  aiMessage: string
}

/** 提交给后端的映射：`{ [目标字段 key]: 源列下标 }` */
export type CustomerImportMapping = Record<string, number>

export type CustomerImportPreviewAction = 'NEW' | 'UPDATE' | 'SKIP' | 'ERROR'
export type CustomerImportCommitAction = 'CREATED' | 'UPDATED' | 'SKIPPED' | 'FAILED'

/** 试运行 / 正式导入共用的逐行结果（action 的取值域不同） */
export interface CustomerImportRow {
  rowNo: number
  externalId: string
  displayName: string
  phone: string
  action: CustomerImportPreviewAction | CustomerImportCommitAction
  message: string
  customerId: string | null
}

export interface CustomerImportPreviewResult {
  mode: 'preview'
  total: number
  newCount: number
  updateCount: number
  skipCount: number
  errorCount: number
  warnCount: number
  rows: CustomerImportRow[]
}

export interface CustomerImportCommitResult {
  mode: 'commit'
  total: number
  createdCount: number
  updatedCount: number
  skippedCount: number
  failedCount: number
  rows: CustomerImportRow[]
}
