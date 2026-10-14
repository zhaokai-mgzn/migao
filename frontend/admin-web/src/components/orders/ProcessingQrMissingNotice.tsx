'use client'

import { useState } from 'react'
import { AlertTriangle, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui'
import { processingOrderApi, productionApi } from '@/lib/api'

/**
 * 加工单「还没有可扫二维码」提示 + 一键补码（issue #6867 / B5）。
 *
 * ## 治的是什么
 *
 * 纸面右上角那个码已换成**加工单级稳定短链** `{base}/o/{短码}`（B4 已合并），而**存量加工单
 * 没有 `short_code`**（迁移 V155 明确不回填）：补码只发生在「实例化工序」/「重新生成二维码」
 * 那条路径上。⇒ 商家对旧单直接点打印，纸面**静默**印出「无码」+ 短码位 `—`：
 * 看起来打好了，纸却扫不了，而页面上**没有任何东西**提示他先补码（issue #6867 的原始缺陷）。
 *
 * 本组件把这一步变成「**可见 + 一键可修**」——**不新增后端端点**：
 * 复用时既有的 `POST /api/admin/production/orders/{orderId}/qr-token/regenerate`（issue #4287）。
 * 该端点**只补缺、不换码**（已有码的行复用；已撤销的行必然产出新码），且**不碰**工序实例 /
 * `done_qty` / 单价 / 计件列 —— 所以对一个码**仍然有效**的单点它不会静默作废已打印的纸。
 *
 * ## 三条口径
 *
 * 1. **事实给所有人、动作只给有权的人**：「这张纸扫不了」是**读**面的事实（谁打印谁受影响，
 *    不给看等于让他继续印废纸）；「生成二维码」是**写**面动作 —— 端点方法级 `processing:manage`
 *    （与 revoke / 既有 regenerate 入口同码）⇒ 无码时**只渲染事实、不渲染按钮**，避免
 *    「按钮可见却 403」（#4287 既有口径）。有码则两者都不渲染。
 * 2. **失败必须可见**：端点失败显示错误文案且**保留入口**（商家要有重试的出口），不许静默 /
 *    假装成功。
 * 3. **成功以「读面真的有了码」为准**：补码后由调用方 `onRegenerated` 重新拉读面 —— 提示退场
 *    发生在 `scan_url` / `short_code` 非空之后，不是发生在「请求回来了」之后（后者是假绿）。
 */
interface ProcessingQrMissingNoticeProps {
  /** 加工单所属订单 id（端点入参是 orderId，不是加工单 id —— 避免取错对象） */
  orderId: string
  /** 当前是否**确实缺码**（`scan_url` / `short_code` 均为空）；有码时本组件不该被渲染 */
  missing: boolean
  /** 补码成功后的刷新（重新拉加工单读面 ⇒ 纸面出短链与短码） */
  onRegenerated: () => void | Promise<void>
  /** 是否持有 `processing:manage`（false ⇒ 只显示事实、**不显示补码按钮**，与端点权限同码） */
  canManage: boolean
}

/** 提示文案（一条说清「后果 + 该做什么」；不带内部键名 / 不带研发腔） */
const MISSING_HINT = '这张加工单还没有可扫二维码 —— 现在打出来的纸扫不了'

export default function ProcessingQrMissingNotice({
  orderId,
  missing,
  onRegenerated,
  canManage,
}: ProcessingQrMissingNoticeProps) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)

  if (!missing) return null

  const generate = async () => {
    setBusy(true)
    setError('')
    try {
      await productionApi.regenerateQrToken(orderId)
      setDone(true)
      await onRegenerated()
    } catch (e) {
      console.error(e)
      setError('生成二维码失败，请稍后重试')
    } finally {
      setBusy(false)
    }
  }

  // 补码成功、读面尚未刷新回来的那一帧：给一句可见的「已生成」而不是留一个还在等按钮的框
  if (done) {
    return (
      <div
        className="flex items-center gap-2 rounded border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-700"
        data-testid="processing-qr-missing-notice"
      >
        <RefreshCw className="w-4 h-4 shrink-0" />
        已生成二维码，请重新打印
      </div>
    )
  }

  return (
    <div
      className="flex flex-wrap items-center gap-2 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800"
      data-testid="processing-qr-missing-notice"
      role="alert"
    >
      <AlertTriangle className="w-4 h-4 shrink-0" />
      <span>
        {MISSING_HINT}
        {error ? `（${error}）` : ''}
      </span>
      {/* 写入口只给有 `processing:manage` 的人（与端点同码）—— 事实上面照旧给所有人看 */}
      {canManage && (
        <Button
          variant="secondary"
          size="sm"
          className="ml-auto"
          loading={busy}
          disabled={busy}
          data-testid="processing-qr-regenerate"
          onClick={generate}
        >
          生成二维码
        </Button>
      )}
    </div>
  )
}
