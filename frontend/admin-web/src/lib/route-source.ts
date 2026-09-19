/**
 * 路线来源提示（issue #4307 交付物 2）
 *
 * 背景（issue #4308 P1「静默回落」）：加工单生成时若订单**没填**部位/做法，服务端取默认
 * 「布帘×韩褶」路线，而成功路径此前零可观测 —— 罗马帘订单会拿到布帘的 11 道工序，
 * 工人按布帘工序报工、按布帘单价计件（直接错工资）。本模块把 `route_source` 翻成
 * 用户可读、**必须去处置**的提示，是 P1 在用户侧的可观测面。
 *
 * 口径（契约见 #4308 的冻结清单 + 末尾「冻结补遗」，前端不发明字段）——**四态**：
 * - `derived`        两维都命中且库里有这条路线 ⇒ **不提示**（避免噪音：多数正常单都是它）；
 * - `partial`        只命中一维、另一维取默认 ⇒ 请把缺的那一项填进订单；
 * - `missing_route`  两维都命中、但工序库里**没有**这条路线 ⇒ 去「工艺配置」页建这条路线；
 * - `default`        两维全不命中 ⇒ 请把部位/做法填进订单（或确认本单确实没有这些信息）；
 * - 其它/缺失 ⇒ 不提示（可能来自未升级的实例：静默 = 「未知」，**不得**显示成「已派生」）。
 *
 * 两个键的分工（别混用）：
 * - `route_key`           实际使用的路线键（missing_route 时 = 回落后的默认路线）；
 * - `route_requested_key` 派生出的键（可能库里没有；两维全不命中时为 null）。
 *   ⇒ 只有 `missing_route` 的提示要报「本单识别的是 X」，X 只能取 `route_requested_key`。
 */

export type RouteSourceTone = 'warning' | 'notice'

export interface RouteSourceNotice {
  /** 稳定 testid 后缀：default / partial / missing_route */
  key: 'default' | 'partial' | 'missing_route'
  tone: RouteSourceTone
  title: string
  /** 具体路线键 + 补救动作；键缺失时不编造 */
  detail: string
}

export function routeSourceNotice(
  routeSource?: string | null,
  routeKey?: string | null,
  routeRequestedKey?: string | null,
): RouteSourceNotice | null {
  const used = routeKey ? `本单实际使用：${routeKey}。` : ''
  if (routeSource === 'default') {
    return {
      key: 'default',
      tone: 'warning',
      title: '本单没有填部位/做法，已按默认路线生成，请核对工序与计件单价',
      detail: `本单的部位与做法没有填进订单，工序与单价可能与本单实际做法不符 —— 错了会直接算错工人计件工资。${used}补救：把本单的部位与做法填进订单（下单时选对部位与做法）。`,
    }
  }
  if (routeSource === 'partial') {
    return {
      key: 'partial',
      tone: 'notice',
      title: '部位与做法只填了一半，另一半取默认值',
      detail: `本单只填了部位或做法其中之一，另一项按默认值取。${used}补救：把缺的那一项填进订单。`,
    }
  }
  if (routeSource === 'missing_route') {
    const requested = routeRequestedKey ? `本单识别的是 ${routeRequestedKey}，` : ''
    return {
      key: 'missing_route',
      tone: 'warning',
      title: '本单的做法在工序库里没有对应路线，已按默认路线生成',
      detail: `${requested}但工序库里没有这条路线，工序与单价可能与本单实际做法不符 —— 错了会直接算错工人计件工资。${used}补救：到「工艺配置」页新建这条路线（工序库里没有的工序先在「新增工序」里建）。`,
    }
  }
  return null
}
