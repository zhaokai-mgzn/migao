import request from './request'
import type { ApiResponse } from '@/types'
import type { ConfigReadinessResponse } from '@/types/config-readiness'

/**
 * 配置就绪度读面（issue #6579）—— **配置主线只发这一个请求**。
 *
 * ## 为什么它单独一个模块
 *
 * `frontend/admin-web/src/lib/api.ts` 有**只许向下**的行数棘轮
 * （`tests/unit_ci_workflows/loc_freeze_ledger.json`：api.ts 已到冻结上限）⇒
 * 新接口面放新文件，**不回 `api.ts` 加行**。
 *
 * ## 为什么由服务端聚合（改前的代价，带读数）
 *
 * 改前画主线要发 **5 个**请求（工序价目 / 工艺路线 / 加工费组合 / 加工费缺口 / 算料配置）：
 * 任一失败只能落到 `unknown`，而**「网络失败」与「没权限」在客户端长得一样** ⇒ 话术给不出
 * 可行动出口；主线第 ① 步还缺「孤儿工序」（要复刻工艺配置页的逻辑名去重口径 ⇒ 第二份会漂的实现）。
 *
 * ⚠️ 本模块**只声明请求**，不判三态：`done` / `todo` / `unknown` 的判定一律走
 * `@/lib/config-readiness` 的 `judge*`（唯一真值源）。
 */
export const configReadinessApi = {
  /**
   * `GET /api/admin/config-readiness`（方法级码 `production:view`）。
   *
   * 响应 = `{steps: {<stepKey>: {facts, href}}}`：**只有事实**，没有三态；
   * 不持 `processing:manage` 的调用方拿到的载荷里**没有** `remnant-sizes` 这一步
   * （跨码步骤整个省略 —— 不返回 0、不返回 forbidden 占位）。
   */
  get: () => request.get<ApiResponse<ConfigReadinessResponse>>('/api/admin/config-readiness'),
}
