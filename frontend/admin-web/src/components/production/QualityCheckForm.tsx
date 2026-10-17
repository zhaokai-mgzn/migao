'use client'

import { useState } from 'react'
import { Button, Modal } from '@/components/ui'
import { qualityInspectionApi } from '@/lib/api'
import type { QualityInspectionResult } from '@/types'

/**
 * 质检判定录入表单（**成品帘级**；issue #7140 = #5652 的商家面）。
 *
 * ## 口径（用户 2026-10-16 逐字裁定，本组件不得偏离）
 *
 * - **一条记录 = 一件成品帘**（`orderItemId`）：不逐工序、不逐工序完工检；
 * - 判定 = **合格 / 返工 / 报废**三态；判定 ≠ 合格 ⇒ **原因必填**；
 * - 检验人与检验时刻**由服务端定**（不在这里收，也不显示输入框）—— 前端可被改，责任凭证不能信前端。
 *
 * ## 为什么是**弹窗**而不是行内展开（issue #7160）
 *
 * 旧形态把表单渲染在整张列表卡片**最底部**（分页之后）：点「录入判定」后视口内毫无变化，
 * 用户读成「点了没反应」（用户 2026-10-17 逐字：「交互在下面显示了，这个体验不太好，不如弹窗」）。
 * 弹窗让「点哪一行 ⇒ 给哪一件录入」这一对应关系当场可见，也避免撑着列表高度。
 * 本组件同时被「质检记录」页与作业单质检区复用 ⇒ 两处**一次**改成弹窗。
 *
 * ## 为什么「原因必填」在前端也判一次
 *
 * 服务端缺原因 ⇒ 422 具名报错（**它才是判据**）。这里判一次只是为了不白跑一趟网络、
 * 并且把「哪一格没填」当场说清；**两处文案不同源也没关系** —— 真正的拒绝权在服务端。
 *
 * ## 边界（如实登记）
 *
 * - 不做「同一件成品帘已有合格记录时禁止再录」的门禁：**返工后复检是正常业务**
 *   （服务端读面就是按多条设计的，`quality_inspections` 无唯一约束）；
 * - 不显示历史判定（那是列表的事），只负责这一次录入。
 */
interface QualityCheckFormProps {
  /** 一件成品帘（订单行 id）—— 调用方从读面拿到，本组件不自己再查 */
  orderItemId: string
  /** 上屏用的成品帘名；缺省 = 不拼名字（**不编占位名**） */
  subject?: string | null
  /** 提交成功（调用方负责重新拉读面并收起表单） */
  onDone: () => void
  onCancel: () => void
}

const RESULT_OPTIONS: { value: QualityInspectionResult; label: string; hint: string }[] = [
  { value: 'pass', label: '合格', hint: '这件成品帘可以直接进入下一环节' },
  { value: 'rework', label: '返工', hint: '需要返工后重新检验，必须写明原因' },
  { value: 'scrap', label: '报废', hint: '这件不投入使用，必须写明原因' },
]

/** 服务端下发的业务文案优先（缺它才用兜底句）；不把 HTTP 状态码当商家文案。 */
function submitErrorMessage(err: unknown): string {
  const shaped = err as { response?: { data?: { error?: { message?: string } } } }
  const message = shaped?.response?.data?.error?.message
  return message || '没提交上 —— 请稍后重试；若一直失败，请联系管理员。'
}

export default function QualityCheckForm({
  orderItemId,
  subject,
  onDone,
  onCancel,
}: QualityCheckFormProps) {
  const [result, setResult] = useState<QualityInspectionResult>('pass')
  const [reason, setReason] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const submit = async () => {
    if (result !== 'pass' && !reason.trim()) {
      setError('判定为「返工」或「报废」时，必须填写不合格原因。')
      return
    }
    setSubmitting(true)
    setError('')
    try {
      await qualityInspectionApi.create({
        order_item_id: orderItemId,
        result,
        ...(result === 'pass' ? {} : { reason: reason.trim() }),
      })
      onDone()
    } catch (err) {
      setError(submitErrorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      open
      onClose={onCancel}
      title={subject ? `为「${subject}」录入质检判定` : '录入质检判定'}
      footer={
        <>
          <Button variant="secondary" onClick={onCancel} disabled={submitting}>
            取消
          </Button>
          <Button onClick={() => void submit()} disabled={submitting}>
            {submitting ? '提交中…' : '提交判定'}
          </Button>
        </>
      }
    >
      <div data-testid="quality-inspection-form" className="space-y-3">
        <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="质检判定">
          {RESULT_OPTIONS.map((option) => {
            const active = result === option.value
            return (
              <label
                key={option.value}
                className={
                  'inline-flex cursor-pointer items-center gap-2 rounded-md border px-3 py-1.5 text-sm ' +
                  (active
                    ? 'border-primary-300 bg-primary-50 text-primary-700'
                    : 'border-neutral-300 bg-white text-neutral-600')
                }
              >
                <input
                  type="radio"
                  name={`inspection-result-${orderItemId}`}
                  value={option.value}
                  checked={active}
                  data-testid={`quality-result-${option.value}`}
                  onChange={() => setResult(option.value)}
                />
                {option.label}
              </label>
            )
          })}
        </div>

        <p className="text-xs text-neutral-500">
          {RESULT_OPTIONS.find((option) => option.value === result)?.hint}
        </p>

        <div>
          <label htmlFor="inspection-reason" className="mb-1 block text-xs text-neutral-500">
            不合格原因（判定为返工 / 报废时必填）
          </label>
          <textarea
            id="inspection-reason"
            data-testid="quality-inspection-reason"
            rows={2}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="例如：布面污渍 / 尺寸偏差 / 缝线开裂"
            className="w-full rounded border border-neutral-300 bg-white px-3 py-2 text-sm text-neutral-900 placeholder:text-neutral-400 focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-500/15"
          />
        </div>

        {error && (
          <p role="alert" data-testid="quality-inspection-form-error" className="text-sm text-red-600">
            {error}
          </p>
        )}

        <p className="text-xs text-neutral-400">
          提交后记下的是这次检验的人与时刻；同一件成品帘可以多次检验（返工后复检）。
        </p>
      </div>
    </Modal>
  )
}
