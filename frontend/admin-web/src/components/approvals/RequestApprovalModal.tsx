'use client'

import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Button, Input, Modal } from '@/components/ui'
import { loadErrorMessage } from '@/lib/api-error'
import { approvalApi } from '@/lib/api'
import type { ApprovalDraft } from '@/lib/approval-request'

/**
 * 「申请审批」弹窗（issue #7374 段 3）—— 业务页就地提交，不再手抄对象编号去审批中心。
 *
 * ## 🔴 它解决的坑
 *
 * 闸门是按 `objectType + objectRef + 金额门槛` 三件套找审批的（`ApprovalService.consume`）：
 * ref 写错、金额低于门槛，都会变成「批了但用不上」，而**审批中心那边看起来完全正常**。
 * 所以：
 * 1. `objectRef` 由调用方从**当前业务行**带进来（不许人肉输入）；
 * 2. 金额默认取**门槛本身**（能取到就预填），并在提示里写明门槛是什么；
 * 3. 申请人只写「为什么」，产品不问第二遍。
 *
 * ## 边界
 *
 * - 一个对象同时只能有一条**待审**申请（服务端拒，这里把原话显示出来）；
 * - 提交后不等于放行：还要有人在审批中心通过，且业务侧「用一次就失效」。
 */
export default function RequestApprovalModal({
  open,
  onClose,
  draft,
  onSubmitted,
}: {
  open: boolean
  onClose: () => void
  /** 由各业务页用 `lib/approval-request.ts` 的 `*Draft()` 生成（ref 与门槛都在里面）。 */
  draft: ApprovalDraft | null
  onSubmitted?: () => void
}) {
  const [amount, setAmount] = useState('')
  const [reason, setReason] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  // 每次打开都按 draft 重置（不把上一次的对象带过来）
  useEffect(() => {
    if (!open) return
    setAmount(draft?.defaultAmount === null || draft?.defaultAmount === undefined ? '' : String(draft.defaultAmount))
    setReason('')
    setError('')
  }, [open, draft])

  async function submit() {
    if (!draft) return
    setError('')
    const why = reason.trim()
    if (!why) {
      setError('写一句为什么 —— 审批的人要知道这笔为什么该放行')
      return
    }
    let parsedAmount: number | null = null
    if (amount.trim() !== '') {
      const value = Number(amount)
      if (!Number.isFinite(value) || value < 0) {
        setError('审批金额要填一个不小于 0 的数（拿不准就先留空，填错了批了也用不上）')
        return
      }
      parsedAmount = value
    }
    setBusy(true)
    try {
      await approvalApi.submit({
        objectType: draft.objectType,
        objectRef: draft.objectRef,
        ...(draft.objectLabel ? { objectLabel: draft.objectLabel } : {}),
        ...(parsedAmount === null ? {} : { amount: parsedAmount }),
        reason: why,
      })
      toast.success('申请已提交，等待审批')
      onSubmitted?.()
      onClose()
    } catch (e) {
      // 🔴 「这个对象已经有一条待审申请」等是服务端判定 —— 原话上屏
      setError(loadErrorMessage(e, '提交审批申请'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="申请审批"
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            取消
          </Button>
          <Button loading={busy} onClick={() => void submit()} data-testid="approval-request-submit">
            提交申请
          </Button>
        </div>
      }
    >
      <div className="space-y-3">
        <p className="text-sm text-neutral-600">
          提交后要有人在「审批中心」通过才会放行；同一对象同时只能有一条待审申请。
        </p>
        <div className="rounded bg-neutral-50 px-3 py-2 text-xs text-neutral-600" data-testid="approval-request-target">
          申请对象：<span className="font-mono">{draft?.objectLabel || draft?.objectRef || '—'}</span>
        </div>
        <Input
          label="审批金额"
          data-testid="approval-request-amount"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          placeholder="留空也可提交"
          type="number"
        />
        <p className="text-xs text-neutral-500" data-testid="approval-request-amount-hint">
          {draft?.amountHint}
        </p>
        <Input
          label="为什么"
          data-testid="approval-request-reason"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder={draft?.reasonHint}
        />
        {error && (
          <p className="text-sm text-red-600" data-testid="approval-request-error">
            {error}
          </p>
        )}
      </div>
    </Modal>
  )
}
