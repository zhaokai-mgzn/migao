'use client'

import { PAGE_FILL_SOURCE_INTERPRETED } from '@/lib/agent-page-fill'

/**
 * **Agent 解读 / 推荐**字段的来源徽标（issue #5368 包 2 · 硬约束 3）。
 *
 * 与 `RecognizedBadge`（`[图片识别]`）**必须可区分**：表单里「图上抄下来的」与
 * 「米宝推的」是两种可信度不同的东西，标注相同 ⇒ 商家无从判断该信哪一格。
 * 三处差异同时成立：文案（`[米宝解读]`）、testid 前缀（`interpreted-marker-*`）、
 * 配色（amber —— 识别徽标是 primary）。
 *
 * 徽标文案的真值在 `lib/agent-page-fill.ts`（与后端 `deep_channel.SOURCE_INTERPRETED` 同源），
 * 本组件不另写一份字符串。
 */
export function InterpretedBadge({ fieldKey }: { fieldKey: string }) {
  return (
    <span
      data-testid={`interpreted-marker-${fieldKey}`}
      className="ml-1.5 inline-block align-middle whitespace-nowrap rounded border border-amber-200 bg-amber-50 px-1 text-[10px] leading-4 text-amber-700"
    >
      {PAGE_FILL_SOURCE_INTERPRETED}
    </span>
  )
}