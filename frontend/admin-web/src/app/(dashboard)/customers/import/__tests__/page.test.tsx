// case_ids: MIG-009, MIG-010
//
// 客户主数据导入（issue #8295）的页面动线判据：
// ① 上传后渲染列映射表、必填列有标记、AI 建议被预选，且同一目标字段不可重复映射；
// ② 试运行展示汇总与逐行结果，全程不调用正式导入；
// ③ 正式导入在试运行前不可用，试运行并确认后才调用，结果展示新建 / 失败读数；
// ④ AI 识别降级时出提示、不预选映射，并要求人工补齐必填列。
import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'

const mockAnalyze = vi.fn()
const mockPreview = vi.fn()
const mockCommit = vi.fn()

vi.mock('@/lib/customer-import-api', () => ({
  customerImportApi: {
    analyzeImport: (...args: unknown[]) => mockAnalyze(...args),
    previewImport: (...args: unknown[]) => mockPreview(...args),
    commitImport: (...args: unknown[]) => mockCommit(...args),
  },
}))

vi.mock('next/link', () => {
  function MockLink({ href, children }: { href: string; children: React.ReactNode }) {
    return <a href={href}>{children}</a>
  }
  MockLink.displayName = 'MockLink'
  return { default: MockLink }
})

import CustomerImportPage from '@/app/(dashboard)/customers/import/page'

const analyzeResult = {
  headers: ['客户编号', '客户名称', '手机号'],
  samples: [['OLD-001', '张三', '13800138000']],
  totalRows: 2,
  fields: [
    {
      key: 'externalId',
      label: '旧系统客户ID',
      required: true,
      type: 'string',
      aliases: ['客户编号'],
    },
    { key: 'displayName', label: '客户名称', required: true, type: 'string', aliases: [] },
    { key: 'phone', label: '手机号', required: false, type: 'string', aliases: [] },
  ],
  suggestions: [
    {
      sourceIndex: 0,
      sourceHeader: '客户编号',
      targetField: 'externalId',
      confidence: 0.96,
      reason: '列名与旧系统客户ID 高度匹配',
    },
    {
      sourceIndex: 1,
      sourceHeader: '客户名称',
      targetField: 'displayName',
      confidence: 0.88,
      reason: '列名匹配',
    },
  ],
  aiDegraded: false,
  aiMessage: '',
}

const previewResult = {
  mode: 'preview',
  total: 2,
  newCount: 1,
  updateCount: 1,
  skipCount: 0,
  errorCount: 0,
  warnCount: 0,
  rows: [
    {
      rowNo: 2,
      externalId: 'OLD-001',
      displayName: '张三',
      phone: '13800138000',
      action: 'NEW',
      message: '新客户，将创建',
      customerId: null,
    },
    {
      rowNo: 3,
      externalId: 'OLD-002',
      displayName: '李四',
      phone: '13900139000',
      action: 'UPDATE',
      message: '已存在该客户，试运行将更新',
      customerId: 'c-2',
    },
  ],
}

const commitResult = {
  mode: 'commit',
  total: 2,
  createdCount: 1,
  updatedCount: 1,
  skippedCount: 0,
  failedCount: 0,
  rows: [
    {
      rowNo: 2,
      externalId: 'OLD-001',
      displayName: '张三',
      phone: '13800138000',
      action: 'CREATED',
      message: '客户档案已写入',
      customerId: 'c-1',
    },
    {
      rowNo: 3,
      externalId: 'OLD-002',
      displayName: '李四',
      phone: '13900139000',
      action: 'UPDATED',
      message: '客户档案已更新',
      customerId: 'c-2',
    },
  ],
}

function makeFile(): File {
  return new File(['x'], 'customers.xlsx', {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  })
}

/** 选文件 → 等分析结果落到映射表（三个接口都被 mock，此函数只驱动 analyze） */
async function uploadAndWaitForAnalysis(file: File): Promise<void> {
  fireEvent.change(screen.getByLabelText('选择旧系统客户 Excel'), {
    target: { files: [file] },
  })
  await screen.findByTestId('import-mapping')
}

describe('客户主数据导入', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockAnalyze.mockResolvedValue({ data: { data: analyzeResult } })
    mockPreview.mockResolvedValue({ data: { data: previewResult } })
    mockCommit.mockResolvedValue({ data: { data: commitResult } })
  })

  it('上传后渲染列映射表：必填列有标记、AI 建议已预选，同一字段不可重复映射', async () => {
    render(<CustomerImportPage />)
    const file = makeFile()
    await uploadAndWaitForAnalysis(file)

    await waitFor(() => expect(mockAnalyze).toHaveBeenCalledWith(file))
    const mappingCard = screen.getByTestId('import-mapping')
    expect(
      within(mappingCard).getByRole('heading', { name: '2. 确认列映射' }),
    ).toBeInTheDocument()

    // AI 建议预选：第 1/2 列命中，第 3 列未建议 ⇒ 保持「不导入」
    expect((screen.getByTestId('import-map-0') as HTMLSelectElement).value).toBe('externalId')
    expect((screen.getByTestId('import-map-1') as HTMLSelectElement).value).toBe('displayName')
    expect((screen.getByTestId('import-map-2') as HTMLSelectElement).value).toBe('')

    // 必填标记：选项文案带「（必填）」
    const select0 = screen.getByTestId('import-map-0') as HTMLSelectElement
    expect(
      within(select0).getByRole('option', { name: '旧系统客户ID（必填）' }),
    ).toBeInTheDocument()

    // AI 建议的置信度 / 理由 / 源列示例值 / 唯一识别号提示都上屏
    expect(screen.getByText('置信度 96%')).toBeInTheDocument()
    expect(screen.getByText('列名与旧系统客户ID 高度匹配')).toBeInTheDocument()
    expect(screen.getByText('OLD-001')).toBeInTheDocument()
    expect(screen.getByText(/缺这一列的行会报错/)).toBeInTheDocument()

    // 目标字段已被第 1 行占用 ⇒ 第 2 行的同名选项必须禁用
    const select1 = screen.getByTestId('import-map-1') as HTMLSelectElement
    expect(
      within(select1).getByRole('option', { name: '旧系统客户ID（必填）' }),
    ).toBeDisabled()
  })

  it('试运行展示汇总与逐行结果，且不调用正式导入', async () => {
    render(<CustomerImportPage />)
    const file = makeFile()
    await uploadAndWaitForAnalysis(file)

    fireEvent.click(screen.getByRole('button', { name: '试运行' }))

    const summary = await screen.findByTestId('import-preview-summary')
    expect(summary).toHaveTextContent('新建 1')
    expect(summary).toHaveTextContent('更新 1')
    expect(summary).toHaveTextContent('错误 0')
    expect(mockPreview).toHaveBeenCalledTimes(1)
    expect(mockPreview.mock.calls[0][0]).toBe(file)
    expect(mockPreview.mock.calls[0][1]).toEqual({ externalId: 0, displayName: 1 })
    expect(mockPreview.mock.calls[0][2]).toBe(false)
    expect(screen.getByText('已存在该客户，试运行将更新')).toBeInTheDocument()
    expect(mockCommit).not.toHaveBeenCalled()
  })

  it('正式导入在试运行前不可用；确认后才调用导入并展示新建 / 失败读数', async () => {
    render(<CustomerImportPage />)
    const file = makeFile()
    await uploadAndWaitForAnalysis(file)

    expect(screen.getByRole('button', { name: '正式导入' })).toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: '试运行' }))
    await screen.findByTestId('import-preview-summary')
    const importButton = screen.getByRole('button', { name: '正式导入' })
    await waitFor(() => expect(importButton).not.toBeDisabled())

    fireEvent.click(importButton)
    const dialog = await screen.findByRole('dialog', { name: '确认正式导入客户？' })
    expect(within(dialog).getByText(/将处理/)).toBeInTheDocument()
    fireEvent.click(within(dialog).getByTestId('import-confirm-commit'))

    await waitFor(() => expect(mockCommit).toHaveBeenCalledTimes(1))
    expect(mockCommit.mock.calls[0][0]).toBe(file)
    expect(mockCommit.mock.calls[0][1]).toEqual({ externalId: 0, displayName: 1 })
    expect(mockCommit.mock.calls[0][2]).toBe(false)

    const summary = await screen.findByTestId('import-commit-summary')
    expect(summary).toHaveTextContent('新建 1 位')
    expect(summary).toHaveTextContent('失败 0 行')
    expect(screen.getByText('已创建')).toBeInTheDocument()
  })

  it('AI 识别降级：出提示、不预选映射，并提示补齐必填列', async () => {
    mockAnalyze.mockResolvedValue({
      data: {
        data: {
          ...analyzeResult,
          suggestions: [],
          aiDegraded: true,
          aiMessage: 'AI 列识别服务暂时不可用',
        },
      },
    })

    render(<CustomerImportPage />)
    await uploadAndWaitForAnalysis(makeFile())

    const banner = await screen.findByTestId('import-ai-degraded')
    expect(banner).toHaveTextContent('AI 列识别暂不可用')
    expect(banner).toHaveTextContent('AI 列识别服务暂时不可用')
    expect((screen.getByTestId('import-map-0') as HTMLSelectElement).value).toBe('')
    expect(screen.getByTestId('import-missing-required')).toHaveTextContent('旧系统客户ID')
    expect(screen.getByRole('button', { name: '试运行' })).toBeDisabled()
  })

  it('「更新已存在的客户」默认关闭；改动后需重新试运行，再按新选择提交', async () => {
    render(<CustomerImportPage />)
    await uploadAndWaitForAnalysis(makeFile())

    const checkbox = screen.getByRole('checkbox', { name: /更新已存在的客户/ })
    expect(checkbox).not.toBeChecked()

    fireEvent.click(screen.getByRole('button', { name: '试运行' }))
    await screen.findByTestId('import-preview-summary')
    expect(screen.getByRole('button', { name: '正式导入' })).not.toBeDisabled()

    // 改开关 ⇒ 上一次试运行作废（确认弹窗里的读数必须与真正要写入的内容同源）
    fireEvent.click(checkbox)
    expect(screen.getByRole('button', { name: '正式导入' })).toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: '试运行' }))
    await waitFor(() => expect(mockPreview).toHaveBeenCalledTimes(2))
    expect(mockPreview.mock.calls[1][2]).toBe(true)
  })
})
