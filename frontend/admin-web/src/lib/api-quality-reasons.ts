import { request } from '@/lib/api'
import type { ApiResponse, QualityReasonOption } from '@/types'

/**
 * 不合格**原因字典**（issue #7197 ①）：录入界面据此摆短语按钮。
 *
 * 为什么单独一个模块而不是挂进 `qualityInspectionApi`：`src/lib/api.ts` 在
 * `tests/unit_ci_workflows/loc_freeze_ledger.json` 的**冻结面**里（只许缩短），
 * 新增接口面下沉到本文件即可，不必抬高冻结值（见该台账 note）。
 *
 * 服务端是唯一真值源（校验面读同一份），前端不另造一份会漂的表。
 */
export const qualityReasonApi = {
  list: () =>
    request.get<ApiResponse<{ items: QualityReasonOption[] }>>('/api/admin/quality-inspections/reasons'),
}
