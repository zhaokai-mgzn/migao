import request from './request'
import type { ApiResponse } from '@/types'

/**
 * 决策采纳记录（issue #8260）——「AI 建议了什么 → 人做了什么」的后半句。
 *
 * **为什么单独一个文件**：`lib/api.ts` 是**冻结文件**（行数上限 2362，
 * 判据 = `tests/unit_ci_workflows` 的「真语料基线必须绿」）。新增接口一律拆到这里，
 * 不要往 api.ts 里继续堆 —— 那条判据会红，而抬高冻结值需要单独裁定。
 *
 * **fire-and-forget**：调用方 `.catch(() => {})`。用户点的是「问黄金策」，
 * 不该因为一条内部埋点失败而失败。
 */
export const briefingActionApi = {
  /** 点开某条简报条目（`opened_agent`）。**记录 ≠ 采纳**：只表示「点开问了」。 */
  record: (data: {
    bizDate: string
    itemKind: 'todo' | 'risk' | 'suggestion'
    title: string
    action: 'opened_agent'
  }) => request.post<ApiResponse<{ recorded: boolean }>>('/api/admin/briefing/actions', data),
}
