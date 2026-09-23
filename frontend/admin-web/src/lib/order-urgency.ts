/**
 * 订单级「加急 / 要求到货日」（issue #5177）的**前端唯一取值口径**。
 *
 * ## 为什么要有这个文件（不是为一个三元表达式开新文件）
 *
 * 「加急」这个事实在界面上有**三处**消费点：订单列表角标
 * （`frontend/admin-web/src/components/orders/OrderTable.tsx`）、订单详情徽标
 * （`frontend/admin-web/src/components/orders/OrderUrgencyPanel.tsx`）、池看板插队区行
 * （`frontend/admin-web/src/app/(dashboard)/production/pool/page.tsx`）。
 * 三处各写一份 `x.isUrgent ? '加急' : '不加急'` = **三份会漂的口径**
 * （同 `frontend/admin-web/src/lib/saving-board.ts` 头注释的纪律：口径只留一处）。
 *
 * ## 口径（与后端列缺省逐字同源）
 *
 * `orders.is_urgent` 是 `NOT NULL DEFAULT FALSE` ⇒ 前端把**缺省 / 字段缺席 / `null`
 * 一律读成「不加急」**（只有 `=== true` 才算真值）—— 不得默认勾上、不得猜测。
 * 「总是加急」这类缺省错法（写死 `true`、或把 `!== false` 当加急）会**立刻**在这两个
 * 纯函数上显形，而它们正是界面上三处角标的唯一来源。
 */
import type { Order } from '@/types'

/** 加急取值的最小入参（`Order` 与池看板的 `PoolLine` 都带 `isUrgent`） */
export interface UrgencySource {
  isUrgent?: boolean | null
}

/**
 * 加急**真值**：只有服务端明确给 `true` 才算加急。
 *
 * 缺省 / 字段缺席（老响应）/ `null` ⇒ `false` = 不加急 —— 这就是「缺省不变」的机械判据
 * （PR-079 判据 2 的读面；后端列缺省即 `FALSE`）。
 */
export function isUrgentFlag(src: UrgencySource | null | undefined): boolean {
  return src?.isUrgent === true
}

/**
 * 角标文案：**唯一来源**（三处消费点共用）。
 *
 * 红证 = 把它改成「总是加急」（`() => '加急'`）⇒ 三处的角标断言**全部**当场红
 * （`frontend/admin-web/tests/unit/components/OrderTableUrgency.test.tsx` 的注入式正控）。
 */
export function urgentBadgeText(src: UrgencySource | null | undefined): '加急' | '不加急' {
  return isUrgentFlag(src) ? '加急' : '不加急'
}

/**
 * 建单 / 改单请求体里的两个键（PR-079 判据 2 的**写面**）。
 *
 * 🔴 **未勾 / 未填 ⇒ 键不出现**（不是 `false` / `''`）——「没填」与「显式不加急 / 未指定」
 * 在请求体上必须能区分（后端库列 `NOT NULL DEFAULT FALSE` / `NULL`）。
 *
 * 红证 = 改成**无条件带键**（`{ isUrgent, requiredDeliveryDate }`）⇒
 * `frontend/admin-web/tests/unit/pages/orders-urgency.test.tsx` 的「键不存在」断言当场红。
 */
export function urgencyRequestFields(
  isUrgent: boolean,
  requiredDeliveryDate: string,
): { isUrgent?: true; requiredDeliveryDate?: string } {
  return {
    ...(isUrgent ? { isUrgent: true as const } : {}),
    ...(requiredDeliveryDate ? { requiredDeliveryDate } : {}),
  }
}

/** 订单是否带加急标记（可读性别名；`Order` 入参的调用点用它，避免到处写 `isUrgentFlag`） */
export function orderIsUrgent(order: Order | null | undefined): boolean {
  return isUrgentFlag(order)
}
