'use client'

import { useMemo, useState, type ChangeEvent } from 'react'
import Link from 'next/link'
import { AlertTriangle, ArrowLeft, Check, ChevronRight, PlayCircle, Upload } from 'lucide-react'
import { toast } from 'sonner'
import { customerImportApi } from '@/lib/customer-import-api'
import { cn } from '@/lib/utils'
import { Badge, Button, Modal, PageCard, PageHeader, SELECT_CONTROL } from '@/components/ui'
import type {
  CustomerImportAnalyzeResult,
  CustomerImportCommitAction,
  CustomerImportCommitResult,
  CustomerImportField,
  CustomerImportMapping,
  CustomerImportPreviewAction,
  CustomerImportPreviewResult,
  CustomerImportSuggestion,
} from '@/types/customer-import'

/**
 * 客户主数据导入（issue #8295）—— 旧系统 Excel 的迁移工作台。
 *
 * 动线固定为四步：上传 → 确认列映射 → 试运行 → 正式导入。
 * 关键约束（都在本文件里，别只靠后端兜）：
 * - 试运行**不写**任何数据；正式导入只在**已经试运行**之后才可点；
 * - 「旧系统客户ID」是唯一识别号：缺这一列的行由后端逐行报错，页面负责在映射阶段就把必填列补齐；
 * - 文件 `File` 对象全程保留：preview / commit 都重新上传同一份文件（后端不缓存临时文件）；
 * - 改列映射或「更新已存在客户」开关 ⇒ 之前那次试运行**作废**，必须重新试运行（否则确认弹窗里
 *   的读数与真正要写入的内容不一致）。
 */

const STEPS = ['上传', '确认列映射', '试运行', '正式导入'] as const
const ACCEPTED_EXTENSIONS = ['.xlsx', '.xls']
const EMPTY_FIELDS: CustomerImportField[] = []

type ImportRow = CustomerImportPreviewResult['rows'][number] | CustomerImportCommitResult['rows'][number]

const ACTION_META: Record<
  CustomerImportPreviewAction | CustomerImportCommitAction,
  { label: string; variant: 'success' | 'info' | 'default' | 'error' }
> = {
  NEW: { label: '新建', variant: 'success' },
  UPDATE: { label: '更新', variant: 'info' },
  SKIP: { label: '跳过', variant: 'default' },
  ERROR: { label: '错误', variant: 'error' },
  CREATED: { label: '已创建', variant: 'success' },
  UPDATED: { label: '已更新', variant: 'info' },
  SKIPPED: { label: '已跳过', variant: 'default' },
  FAILED: { label: '失败', variant: 'error' },
}

function extensionOf(fileName: string): string {
  const dot = fileName.lastIndexOf('.')
  return dot >= 0 ? fileName.slice(dot).toLowerCase() : ''
}

/** 后端 `confidence` 约定为 0~1；容错接收 0~100 的旧读数，统一显示成百分比 */
function confidencePercent(confidence: number): number {
  const raw = confidence > 1 ? confidence : confidence * 100
  return Math.max(0, Math.min(100, Math.round(raw)))
}

function confidenceVariant(confidence: number): 'success' | 'warning' | 'default' {
  const percent = confidencePercent(confidence)
  if (percent >= 80) return 'success'
  if (percent >= 50) return 'warning'
  return 'default'
}

/** 页面 state（源列下标 → 目标字段）转后端契约（目标字段 → 源列下标） */
function buildMappingPayload(mapping: Record<number, string>): CustomerImportMapping {
  const payload: CustomerImportMapping = {}
  for (const [sourceIndex, targetField] of Object.entries(mapping)) {
    if (targetField) payload[targetField] = Number(sourceIndex)
  }
  return payload
}

/** 试运行 / 正式导入的逐行结果表（行数最多 2000，纵向滚动、不分页） */
function ImportRowsTable({ rows, mode }: { rows: ImportRow[]; mode: 'preview' | 'commit' }) {
  return (
    <div
      data-testid={`import-${mode}-rows`}
      className="max-h-96 overflow-auto rounded border border-neutral-200"
    >
      <table className="w-full min-w-[760px] text-sm">
        <thead className="sticky top-0 z-10 bg-neutral-50 text-neutral-600">
          <tr>
            <th className="px-3 py-2 text-left font-medium whitespace-nowrap">行号</th>
            <th className="px-3 py-2 text-left font-medium whitespace-nowrap">旧系统客户ID</th>
            <th className="px-3 py-2 text-left font-medium whitespace-nowrap">客户名称</th>
            <th className="px-3 py-2 text-left font-medium whitespace-nowrap">手机号</th>
            <th className="px-3 py-2 text-left font-medium whitespace-nowrap">处理结果</th>
            <th className="px-3 py-2 text-left font-medium whitespace-nowrap">说明</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const meta = ACTION_META[row.action]
            const isFailure = row.action === 'ERROR' || row.action === 'FAILED'
            return (
              <tr key={row.rowNo} className="border-t border-neutral-100">
                <td className="px-3 py-2 text-neutral-500 whitespace-nowrap">{row.rowNo}</td>
                <td className="px-3 py-2 font-mono text-neutral-700 whitespace-nowrap">
                  {row.externalId || '-'}
                </td>
                <td className="px-3 py-2 text-neutral-900 whitespace-nowrap">
                  {row.displayName || '-'}
                </td>
                <td className="px-3 py-2 text-neutral-600 whitespace-nowrap">{row.phone || '-'}</td>
                <td className="px-3 py-2 whitespace-nowrap">
                  <Badge variant={meta.variant}>{meta.label}</Badge>
                </td>
                <td
                  className={cn(
                    'min-w-[220px] px-3 py-2 break-words',
                    isFailure ? 'text-red-600' : 'text-neutral-600',
                  )}
                >
                  {row.message || '-'}
                </td>
              </tr>
            )
          })}
          {rows.length === 0 && (
            <tr>
              <td colSpan={6} className="px-3 py-8 text-center text-neutral-400">
                没有需要展示的行
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

export default function CustomerImportPage() {
  const [file, setFile] = useState<File | null>(null)
  const [analyzing, setAnalyzing] = useState(false)
  const [analyzeResult, setAnalyzeResult] = useState<CustomerImportAnalyzeResult | null>(null)
  const [analyzeError, setAnalyzeError] = useState('')

  /** 源列下标 → 目标字段 key；空串 / 缺省 = 不导入 */
  const [mapping, setMapping] = useState<Record<number, string>>({})
  const [updateExisting, setUpdateExisting] = useState(false)

  const [previewing, setPreviewing] = useState(false)
  const [preview, setPreview] = useState<CustomerImportPreviewResult | null>(null)
  const [previewError, setPreviewError] = useState('')

  const [confirmOpen, setConfirmOpen] = useState(false)
  const [committing, setCommitting] = useState(false)
  const [commitError, setCommitError] = useState('')
  const [commitResult, setCommitResult] = useState<CustomerImportCommitResult | null>(null)

  const fields = analyzeResult?.fields ?? EMPTY_FIELDS
  const usedTargets = useMemo(() => new Set(Object.values(mapping).filter(Boolean)), [mapping])
  const missingRequired = useMemo(
    () => fields.filter((field) => field.required && !usedTargets.has(field.key)),
    [fields, usedTargets],
  )
  const suggestionsByIndex = useMemo(() => {
    const byIndex = new Map<number, CustomerImportSuggestion>()
    for (const suggestion of analyzeResult?.suggestions ?? []) {
      byIndex.set(suggestion.sourceIndex, suggestion)
    }
    return byIndex
  }, [analyzeResult])
  const mappingPayload = useMemo(() => buildMappingPayload(mapping), [mapping])

  /** 当前进行到第几步（只用于页头的步骤提示，不参与任何校验） */
  const currentStep = commitResult ? 4 : preview ? 3 : analyzeResult ? 2 : 1

  /** 换文件 / 重试识别都会重置整条动线（旧文件的试运行结果绝不能留在屏幕上） */
  const analyzeFile = async (selected: File) => {
    setAnalyzing(true)
    setAnalyzeError('')
    setAnalyzeResult(null)
    setMapping({})
    setPreview(null)
    setPreviewError('')
    setCommitResult(null)
    setCommitError('')
    setConfirmOpen(false)
    try {
      const res = await customerImportApi.analyzeImport(selected)
      const data = res.data.data
      const headers = data.headers ?? []
      const fields = data.fields ?? []
      const suggestions = data.suggestions ?? []

      // 预选 AI 建议：只接受「字段存在 / 下标在表头范围内 / 同一目标字段只认第一条」的建议。
      // 后端降级时 suggestions 可能为空 ⇒ 这里自然落到全部「不导入」，由用户手动选。
      const knownFields = new Set(fields.map((field) => field.key))
      const suggested: Record<number, string> = {}
      const used = new Set<string>()
      for (const suggestion of suggestions) {
        if (!Number.isInteger(suggestion.sourceIndex)) continue
        if (suggestion.sourceIndex < 0 || suggestion.sourceIndex >= headers.length) continue
        if (!knownFields.has(suggestion.targetField) || used.has(suggestion.targetField)) continue
        if (suggested[suggestion.sourceIndex]) continue
        suggested[suggestion.sourceIndex] = suggestion.targetField
        used.add(suggestion.targetField)
      }

      setAnalyzeResult({
        ...data,
        headers,
        fields,
        suggestions,
        samples: data.samples ?? [],
      })
      setMapping(suggested)
    } catch {
      // 请求拦截器已 toast；这里只标失败态，文件仍保留以便「重新识别」
      setAnalyzeError('文件识别失败 —— 请确认是有效的 Excel 文件后重试。')
    } finally {
      setAnalyzing(false)
    }
  }

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const selected = event.target.files?.[0]
    if (!selected) return
    if (!ACCEPTED_EXTENSIONS.includes(extensionOf(selected.name))) {
      toast.error('请选择 .xlsx 或 .xls 文件')
      event.target.value = ''
      return
    }
    setFile(selected)
    void analyzeFile(selected)
  }

  const handleMappingChange = (sourceIndex: number, targetField: string) => {
    setMapping((prev) => {
      const next = { ...prev }
      if (targetField) next[sourceIndex] = targetField
      else delete next[sourceIndex]
      return next
    })
    // 映射变了 ⇒ 上一次试运行的读数作废；不重新试运行不许正式导入
    setPreview(null)
    setPreviewError('')
    setCommitResult(null)
  }

  const handleUpdateExistingChange = (checked: boolean) => {
    setUpdateExisting(checked)
    setPreview(null)
    setPreviewError('')
    setCommitResult(null)
  }

  const handlePreview = async () => {
    if (!file || !analyzeResult) return
    if (missingRequired.length > 0) {
      toast.error(`请先完成必填列的映射：${missingRequired.map((field) => field.label).join('、')}`)
      return
    }
    setPreviewing(true)
    setPreviewError('')
    setPreview(null)
    setCommitResult(null)
    try {
      const res = await customerImportApi.previewImport(file, mappingPayload, updateExisting)
      setPreview(res.data.data)
      toast.success('试运行完成 —— 没有写入任何数据')
    } catch {
      setPreviewError('试运行失败 —— 没有写入任何数据。请检查文件和列映射后重试。')
    } finally {
      setPreviewing(false)
    }
  }

  const handleCommit = async () => {
    if (!file || !preview) return
    setCommitting(true)
    setCommitError('')
    try {
      const res = await customerImportApi.commitImport(file, mappingPayload, updateExisting)
      const result = res.data.data
      setCommitResult(result)
      setConfirmOpen(false)
      // 这份试运行已经消费掉：正式导入按钮回到不可用，避免同一批数据被重复提交
      setPreview(null)
      const written = result.createdCount + result.updatedCount
      if (result.failedCount > 0) {
        toast.error(`导入完成：成功 ${written} 行，失败 ${result.failedCount} 行 —— 请查看明细后重试失败行`)
      } else {
        toast.success(`导入完成：新建 ${result.createdCount} 位、更新 ${result.updatedCount} 位客户`)
      }
    } catch {
      // 关掉确认弹窗，否则失败原因被弹窗盖住（用户只会看到「确认导入」又弹回来）
      setConfirmOpen(false)
      setCommitError('正式导入失败 —— 请保留原文件后重试；同一客户重复导入不会重复创建。')
    } finally {
      setCommitting(false)
    }
  }

  const busy = analyzing || previewing || committing

  return (
    <div className="p-6 space-y-4">
      <Link
        href="/customers"
        className="inline-flex items-center gap-1.5 text-sm text-neutral-500 transition-colors hover:text-primary-600"
      >
        <ArrowLeft className="w-4 h-4" />
        返回客户列表
      </Link>

      <PageHeader
        title="客户主数据导入"
        subtitle="把旧系统客户档案批量迁进来：先确认列对应关系、试运行看清结果，再正式导入"
      />

      <ol data-testid="import-steps" className="flex flex-wrap items-center gap-x-3 gap-y-2">
        {STEPS.map((step, index) => {
          const stepNo = index + 1
          const done = stepNo < currentStep
          const active = stepNo === currentStep
          return (
            <li key={step} className="flex items-center gap-2">
              <span
                className={cn(
                  'flex h-6 w-6 items-center justify-center rounded-full border text-xs font-medium',
                  done && 'border-primary-600 bg-primary-600 text-white',
                  active && !done && 'border-primary-300 bg-primary-50 text-primary-700',
                  !done && !active && 'border-neutral-200 bg-white text-neutral-400',
                )}
              >
                {done ? <Check className="w-3.5 h-3.5" /> : stepNo}
              </span>
              <span
                className={cn(
                  'text-sm',
                  active ? 'font-medium text-neutral-900' : 'text-neutral-500',
                )}
              >
                {step}
              </span>
              {index < STEPS.length - 1 && <ChevronRight className="w-4 h-4 text-neutral-300" />}
            </li>
          )
        })}
      </ol>

      <PageCard>
        <h2 className="text-base font-semibold text-neutral-900">1. 上传文件</h2>
        <p className="mt-1 text-sm text-neutral-500">
          支持 .xlsx / .xls。上传后只读取表头与少量示例，不会写入客户数据。
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <input
            id="customer-import-file"
            data-testid="customer-import-file"
            type="file"
            accept=".xlsx,.xls"
            aria-label="选择旧系统客户 Excel"
            disabled={busy}
            onClick={(event) => {
              // 允许再次选择同一个文件（否则 change 不触发，换不了文件）
              event.currentTarget.value = ''
            }}
            onChange={handleFileChange}
            className="block text-sm text-neutral-600 file:mr-3 file:rounded file:border file:border-neutral-300 file:bg-white file:px-3 file:py-1.5 file:text-sm"
          />
          {analyzing && <span className="text-sm text-neutral-500">正在识别表头…</span>}
        </div>

        {file && !analyzing && (
          <p className="mt-2 text-xs text-neutral-500">
            已选择 {file.name}
            {analyzeResult
              ? ` · ${analyzeResult.headers.length} 列 · ${analyzeResult.totalRows} 行`
              : ''}
          </p>
        )}

        {analyzeError && (
          <div
            data-testid="import-analyze-error"
            role="alert"
            className="mt-3 flex flex-wrap items-center gap-3 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700"
          >
            <AlertTriangle className="w-4 h-4 shrink-0" />
            <span>{analyzeError}</span>
            {file && (
              <Button variant="secondary" size="sm" onClick={() => void analyzeFile(file)}>
                重新识别
              </Button>
            )}
          </div>
        )}

        <div className="mt-4 rounded border border-neutral-200 bg-neutral-50 p-3 text-sm text-neutral-600">
          <strong className="text-neutral-800">旧系统客户ID 是唯一识别号</strong>
          ：同一份文件重复导入不会重复创建客户；缺这一列的行会报错。请先在旧系统导出时确认这一列存在。
        </div>
      </PageCard>

      {analyzeResult && (
        <PageCard testId="import-mapping">
          <h2 className="text-base font-semibold text-neutral-900">2. 确认列映射</h2>
          <p className="mt-1 text-sm text-neutral-500">
            左边是旧系统表头，右边选择对应的客户信息；标着「必填」的列必须选上。
          </p>

          {analyzeResult.aiDegraded && (
            <div
              data-testid="import-ai-degraded"
              role="status"
              className="mt-4 rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800"
            >
              <strong>AI 列识别暂不可用</strong>
              {analyzeResult.aiMessage ? `：${analyzeResult.aiMessage}` : ''}
              。请手动确认下表每一列对应的客户信息。
            </div>
          )}

          {missingRequired.length > 0 && (
            <p data-testid="import-missing-required" className="mt-3 text-sm text-amber-700">
              还缺必填列：{missingRequired.map((field) => field.label).join('、')} ——
              选好之后才能试运行。
            </p>
          )}

          <div className="mt-4 overflow-x-auto rounded border border-neutral-200">
            <table className="w-full text-sm">
              <thead className="bg-neutral-50 text-neutral-600">
                <tr>
                  <th className="px-3 py-2 text-left font-medium whitespace-nowrap">旧系统表头</th>
                  <th className="px-3 py-2 text-left font-medium whitespace-nowrap">示例值</th>
                  <th className="px-3 py-2 text-left font-medium whitespace-nowrap">对应客户信息</th>
                  <th className="px-3 py-2 text-left font-medium whitespace-nowrap">AI 建议</th>
                </tr>
              </thead>
              <tbody>
                {analyzeResult.headers.map((header, index) => {
                  const suggestion = suggestionsByIndex.get(index)
                  return (
                    <tr key={`${header}-${index}`} className="border-t border-neutral-100">
                      <td className="px-3 py-2 text-neutral-900 whitespace-nowrap">
                        {header || `第 ${index + 1} 列`}
                      </td>
                      <td className="px-3 py-2 text-neutral-500 whitespace-nowrap">
                        {analyzeResult.samples?.[0]?.[index] || '-'}
                      </td>
                      <td className="px-3 py-2">
                        <select
                          data-testid={`import-map-${index}`}
                          aria-label={`源列「${header || index + 1}」对应的客户信息`}
                          className={SELECT_CONTROL}
                          value={mapping[index] ?? ''}
                          onChange={(event) => handleMappingChange(index, event.target.value)}
                        >
                          <option value="">不导入</option>
                          {fields.map((field) => (
                            <option
                              key={field.key}
                              value={field.key}
                              disabled={
                                usedTargets.has(field.key) && mapping[index] !== field.key
                              }
                            >
                              {field.label}
                              {field.required ? '（必填）' : ''}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="px-3 py-2">
                        {suggestion ? (
                          <div className="flex items-center gap-2">
                            <Badge variant={confidenceVariant(suggestion.confidence)}>
                              置信度 {confidencePercent(suggestion.confidence)}%
                            </Badge>
                            <span className="text-xs text-neutral-500">
                              {suggestion.reason || '列名匹配'}
                            </span>
                          </div>
                        ) : (
                          <span className="text-xs text-neutral-400">未识别，请手动选择</span>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </PageCard>
      )}

      {analyzeResult && (
        <PageCard>
          <h2 className="text-base font-semibold text-neutral-900">3. 试运行与正式导入</h2>
          <p className="mt-1 text-sm text-neutral-500">
            试运行只检查文件，不会写入任何数据；确认结果无误后再正式导入。
          </p>

          <label className="mt-4 flex items-start gap-2 text-sm text-neutral-700">
            <input
              type="checkbox"
              data-testid="import-update-existing"
              className="mt-0.5 h-4 w-4 rounded border-neutral-300"
              checked={updateExisting}
              onChange={(event) => handleUpdateExistingChange(event.target.checked)}
            />
            <span>
              更新已存在的客户（按旧系统客户ID）
              <span className="block text-xs text-neutral-500">
                关闭时，已存在的客户会跳过；打开后会用本次文件更新这些客户的资料。
              </span>
            </span>
          </label>

          <div className="mt-4 flex flex-wrap items-center gap-2">
            <Button
              variant="secondary"
              onClick={() => void handlePreview()}
              loading={previewing}
              disabled={!file || analyzing || committing || missingRequired.length > 0}
              icon={<PlayCircle className="w-4 h-4" />}
            >
              试运行
            </Button>
            <Button
              onClick={() => {
                setCommitError('')
                setConfirmOpen(true)
              }}
              disabled={!preview || previewing || committing}
              icon={<Upload className="w-4 h-4" />}
            >
              正式导入
            </Button>
            {preview && <span className="text-xs text-neutral-500">已试运行，可正式导入</span>}
          </div>

          {previewError && (
            <div
              data-testid="import-preview-error"
              role="alert"
              className="mt-3 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700"
            >
              {previewError}
            </div>
          )}

          {preview && (
            <div className="mt-5 space-y-3">
              <div
                data-testid="import-preview-summary"
                className="flex flex-wrap items-center gap-2 text-sm text-neutral-700"
              >
                <span>
                  共 <strong>{preview.total}</strong> 行
                </span>
                <Badge variant="success">新建 {preview.newCount}</Badge>
                <Badge variant="info">更新 {preview.updateCount}</Badge>
                <Badge>跳过 {preview.skipCount}</Badge>
                <Badge variant="error">错误 {preview.errorCount}</Badge>
                <Badge variant="warning">警告 {preview.warnCount}</Badge>
              </div>
              <ImportRowsTable rows={preview.rows} mode="preview" />
            </div>
          )}

          {commitError && (
            <div
              data-testid="import-commit-error"
              role="alert"
              className="mt-3 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700"
            >
              {commitError}
            </div>
          )}

          {commitResult && (
            <div className="mt-5 space-y-3">
              <div
                data-testid="import-commit-summary"
                className={cn(
                  'rounded border p-3 text-sm',
                  commitResult.failedCount > 0
                    ? 'border-amber-200 bg-amber-50 text-amber-800'
                    : 'border-green-200 bg-green-50 text-green-700',
                )}
              >
                <div className="font-medium">正式导入完成</div>
                <div className="mt-1">
                  新建 <strong>{commitResult.createdCount}</strong> 位 · 更新{' '}
                  <strong>{commitResult.updatedCount}</strong> 位 · 跳过{' '}
                  <strong>{commitResult.skippedCount}</strong> 行 · 失败{' '}
                  <strong>{commitResult.failedCount}</strong> 行
                </div>
              </div>
              <ImportRowsTable rows={commitResult.rows} mode="commit" />
              <p className="text-xs text-neutral-500">
                失败的行可以修正后用同一份文件重新导入；已成功的客户不会重复创建。
              </p>
            </div>
          )}
        </PageCard>
      )}

      <Modal
        open={confirmOpen}
        onClose={() => {
          if (!committing) setConfirmOpen(false)
        }}
        title="确认正式导入客户？"
        width={560}
        footer={
          <>
            <Button
              variant="secondary"
              disabled={committing}
              onClick={() => setConfirmOpen(false)}
            >
              取消
            </Button>
            <Button
              data-testid="import-confirm-commit"
              loading={committing}
              onClick={() => void handleCommit()}
            >
              确认导入
            </Button>
          </>
        }
      >
        {preview && (
          <div className="space-y-2 text-sm text-neutral-700">
            <p>
              将处理 <strong>{preview.total}</strong> 行：新建 {preview.newCount} 位，更新{' '}
              {preview.updateCount} 位，跳过 {preview.skipCount} 行。
            </p>
            <p>
              {updateExisting
                ? '已存在的客户会按旧系统客户ID 匹配后更新资料。'
                : '已存在的客户会按旧系统客户ID 匹配后跳过，现有资料不变。'}
            </p>
            <p className="text-neutral-500">
              正式导入会写入客户主数据，请确认文件和列映射无误。
            </p>
          </div>
        )}
      </Modal>
    </div>
  )
}
