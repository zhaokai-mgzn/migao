'use client'

import { Fragment, Suspense, useCallback, useEffect, useMemo, useState } from 'react'
import { AlertCircle, ChevronDown, FolderTree, Plus, RefreshCw, Trash2 } from 'lucide-react'
import { useSearchParams } from 'next/navigation'
import { toast } from 'sonner'
import { Button, Modal } from '@/components/ui'
import { processingCategoryApi, processingItemApi, productionApi } from '@/lib/api'
import { feeGuardReasons } from '@/lib/production-guard-reasons'
import { cn } from '@/lib/utils'
import type {
  FeeCombinationsResponse,
  FeeGaps,
  ProcessingCategory,
  ProcessingItem,
} from '@/types'

/**
 * 加工项管理 /production/processing（issue #4490）
 *
 * **用户裁定（2026-09-19）**：「**加工项**和**加工项费用**这两个我建议**合并成一个菜单**，
 * 也**放到生产管理菜单下**」。
 *
 * 为什么合并：两者是**同一业务域**（加工项及其定价）且共用**同一菜单入口**（节点码自 issue #5291 起 = 读码
 * `production:view`；页内写动作仍是 `processing:manage`），
 * 却被拆在两个菜单组里 —— 「加工项管理」在**商品管理**组、「加工费管理」在**生产管理**组。
 * 加工费组合的定价对象就是加工项本身（`POST /processing-fee-combinations` 的 `items[]` 必须
 * 是加工项目录里活跃的**加工项名**，后端护栏逐条校验），拆开意味着「建组合发现缺加工项要跳到
 * 另一个菜单组去建」——与 #4416（工序库 + 工艺路线）合并的动因同型。
 *
 * 页面形态（**用户总要求**：「别把功能直接平铺到一个页面上，还是需要保证 UI 设计质量的」）：
 * - **两个 tab**（沿用 #4482 在 `/production/routings` 确立的 tab 范式与类名）：
 *   `加工项`（列表 + CRUD + 分类）与 `加工费组合`（选配组合 → 单价 元/米 + 未定价缺口）。
 *   合并仍是**一个菜单入口、一个页面**，只改**内部组织** —— 不是把两个域依次堆进一屏。
 * - **每个 tab 只回答一个问题**：①「我有哪些加工项？」②「哪几个加工项一起用时收多少？」
 * - **一屏一件事**：单 tab 内分主次 —— 主区是列表与主操作（新增加工项 / 新建组合），
 *   次区是只读/低频面（加工分类走**抽屉**、未定价缺口是**辅助告警条**），不做「三块大卡片平铺」。
 * - **空态即引导**（列表空态直接给下一步）、**危险操作二次确认**（删加工项走确认弹窗、
 *   停用组合走 `window.confirm`）、**护栏理由就地展示**（后端 `error.details[].message` 逐条）。
 * - **切 tab 不丢状态**：两栏的 state 都挂在**同一个组件**上，条件渲染不重置它们
 *   （形态同 #4482：编辑中的表单 / 勾选中的组合在切走再切回后仍在）。
 *
 * 契约（冻结，**不得自行发明端点/字段名**）：
 *   GET|POST /api/admin/processing-items            PUT|DELETE /processing-items/{id}
 *   GET|POST /api/admin/processing-categories
 *   GET|POST /api/admin/production/processing-fee-combinations
 *   PUT|DELETE /api/admin/production/processing-fee-combinations/{id}
 *   GET  /api/admin/production/processing-fee-gaps
 *   —— 写端点权限统一 `processing:manage`（以拦截器/后端为准，本页不做显隐分叉）。
 *
 * 两处**故意**不做（沿 #4386 的口径，本单不推翻）：
 * ① **不在前端拼 composition_key**：归一化（与书写顺序无关）是服务端的事 —— 前端自己拼会变成
 *    第二份口径，两边一旦漂移就会出现「页面显示一个组合、库里是另一个」的静默错配。
 * ② **不接线计价**：本页只管配置；下单侧取价（`OrderService.sumProcessingFee` / 下单页 /
 *    ai-agent）不在本包。
 *
 * 旧路径：`/processing` 与 `/production/processing-fees` 都改为重定向到本页
 * （照 #4357 的 `/processing-orders` → `/production`、#4416 的 `/production/operations` →
 * `/production/routings` 先例，旧书签/外部深链不 404）。其中加工费那一条带上 `?tab=fees`
 * 直达「加工费组合」—— 后端未定价提示里的链接（`ProcessingFeeCalculator`）指向的就是旧路径。
 */

import ProcessingBoard from '@/components/production-config/ProcessingBoard'
/**
 * 本页 = **薄壳**：功能体已抽成 {@link ProcessingBoard}（企业基础设置合并页共用同一份）。
 * 路由 / URL 参数 / 行为一字未改。
 */
export default function ProcessingPage() {
  return (
    <Suspense fallback={null}>
      <ProcessingBoard />
    </Suspense>
  )
}
