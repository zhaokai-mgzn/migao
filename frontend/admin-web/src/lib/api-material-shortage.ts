import request from './request'
import type { ApiResponse } from '@/types'
import type { MaterialShortageView } from '@/types/material-shortage'

/**
 * 商品级用料缺口与耗尽风险（具名跨域视图 `material_shortage`；issue #6280 后端 / #6282 页面）。
 *
 * `GET /api/admin/materials/shortage?statuses=&limit=&as_of=`，权限码 `product:list`
 * （与端点方法级 `@RequirePermission` 逐字同码）。契约真值源 = issue #6280 的「冻结契约 v1」：
 * 六档分层 `blocked/critical/soon/short/safe/unknown`，行序 = 分层降序 → 缺口降序（**页面不重排**）。
 *
 * ⚠️ `limit` 必须 ≥1（缺省 50）；非法值由服务端**显式 400** 拒绝，前端不夹取。
 */
export const materialShortageApi = {
  shortage: (params?: { statuses?: string; limit?: number; as_of?: string }) =>
    request.get<ApiResponse<MaterialShortageView>>('/api/admin/materials/shortage', { params }),
}
