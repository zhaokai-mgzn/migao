/**
 * **打印必留痕**的唯一通道（issue #5052 P3/P4；设计 §7.3 / N2）
 *
 * ## 本模块存在的理由
 *
 * 「设备侧打印**前**必须先调 `POST /api/worker/inbound/labels/{短码}/print`」这条纪律，
 * 靠「记得调」是不成立的：只要页面上还存在**第二条**能送数据给打印机的路径，它迟早会被走到
 * （重打 / 补打 / 某个"顺手"的按钮）。⇒ 本单把送打印做成**只有一个函数**：
 *
 * ```
 * printInboundLabel() = ① 能力探测 → ② 服务端留痕（计数原子自增 + 审计） → ③ 渲染 → ④ 送打印机
 * ```
 *
 * 顺序是硬的：**②失败 ⇒ 不打印**（留不下痕就不许打）；跳过②直接进④的路径**在本模块里不存在**
 * （守卫 `frontend/bmini-app/tests/inbound-print-channel.test.ts` 用调用序断言 + 源码面判据钉住）。
 *
 * ## 前端**不自行计数**（验收判据 5）
 *
 * `printCount` 的唯一写方 = 服务端（`inbound_labels.print_count` 原子自增）。
 * 本模块**原样转发**服务端回执里的数字，**不做任何本地 +1 / 累加**：本地数一份的后果是
 * 「纸上写第 3 次、服务端记第 4 次」，而两份数**都不会报错**。
 */
import { printFailureHint, type PrintCapability, type PrintFailureReason } from './printCapability'
import type { RenderedLabel } from './labelCanvas'

/** 传输层错误（带**分类**：分类决定给工人看哪一条文案） */
export class LabelTransportError extends Error {
  readonly reason: PrintFailureReason

  constructor(reason: PrintFailureReason, message?: string) {
    super(message || reason)
    this.name = 'LabelTransportError'
    this.reason = reason
  }
}

/** 打印通道（**可注入**：真实实现 = `./lpapiTransport`；测试替身 = 记录调用序） */
export interface LabelTransport {
  /** 通道标识（显示用；也用于判据断言「用的是哪条通道」） */
  readonly id: string
  /** 人读名称（如「德佟 DP30S（浏览器蓝牙）」） */
  readonly label: string
  /**
   * 真正把位图送给打印机。
   * @param printCount 服务端回执里的**第几次**（通道可把它打到纸面/日志上，**不得自己算**）
   * @throws LabelTransportError（分类失败）
   */
  print(label: RenderedLabel, context: { printCount: number }): Promise<void>
}

export interface InboundPrintDeps {
  shortCode: string
  /** 服务端留痕（`POST /api/worker/inbound/labels/{短码}/print`）—— **必须最先成功** */
  recordPrint: (shortCode: string) => Promise<{ shortCode: string; printCount: number }>
  transport: LabelTransport
  /** 渲染（延迟到留痕成功之后才画：画不出来的图不该先占一次留痕？—— 反了，见下） */
  render: () => RenderedLabel | Promise<RenderedLabel>
  /** 能力探测结果（`ok: false` ⇒ 直接给文案，**不调用任何服务端端点**） */
  capability: PrintCapability
  /** 失败分类器（默认 `classifyPrintError`；测试可注入） */
  classify?: (error: unknown) => PrintFailureReason
}

export type InboundPrintResult =
  | { ok: true; printCount: number; transportId: string; transportLabel: string }
  | {
      ok: false
      reason: PrintFailureReason
      hint: string
      /** 服务端**是否已留痕**（true ⇒ 纸上没打出来但计数 +1，重打会再记一次；页面必须说清） */
      printRecorded: boolean
    }

/** 异常 → 原因分类（未知一律 `print-failed`：**不吞**、也不假装是别的原因） */
export function classifyPrintError(error: unknown): PrintFailureReason {
  if (error instanceof LabelTransportError) return error.reason
  const text = String((error as any)?.message ?? error ?? '')
  if (/cancel|abort|用户取消|取消选择/i.test(text)) return 'user-cancelled'
  if (/not.*(found|support)|不支持|型号/i.test(text)) return 'device-unsupported'
  if (/connect|timeout|gatt|disconnect|连/i.test(text)) return 'connect-failed'
  return 'print-failed'
}

/**
 * 打印一张入库标签（**唯一入口**）。
 *
 * 执行序（每一步失败都**不进入下一步**）：
 * ① `capability.ok === false` ⇒ 直接返回文案（**不调服务端、不连蓝牙**）；
 * ② `render()` ⇒ 拿不到位图 ⇒ `render-failed`（**此时还没有留痕**，服务端计数不动）；
 * ③ `recordPrint()` ⇒ 失败 ⇒ 中止（**留不下痕就不打印**，`printRecorded: false`）；
 * ④ `transport.print()` ⇒ 唯一真正送数据的一步。
 */
export async function printInboundLabel(deps: InboundPrintDeps): Promise<InboundPrintResult> {
  const classify = deps.classify ?? classifyPrintError

  if (!deps.capability.ok) {
    const reason = deps.capability.reason || 'print-failed'
    return { ok: false, reason, hint: deps.capability.hint || printFailureHint(reason), printRecorded: false }
  }

  let label: RenderedLabel
  try {
    label = await deps.render()
  } catch (error) {
    return {
      ok: false,
      reason: 'render-failed',
      hint: printFailureHint('render-failed'),
      printRecorded: false,
    }
  }

  let receipt: { shortCode: string; printCount: number }
  try {
    receipt = await deps.recordPrint(deps.shortCode)
  } catch (error) {
    // 🔴 留不下痕 ⇒ 不打印（"打印必留痕"的红线；宁可让工人重试，也不产生无痕打印）
    return {
      ok: false,
      reason: 'print-failed',
      hint: '打印留痕没上报成功，已中止打印（不产生无痕打印）。请检查网络后重试。',
      printRecorded: false,
    }
  }

  try {
    await deps.transport.print(label, { printCount: receipt.printCount })
  } catch (error) {
    const reason = classify(error)
    return { ok: false, reason, hint: printFailureHint(reason), printRecorded: true }
  }

  // 计数**原样转发**服务端回执（前端不 +1、不累加、不缓存）
  return {
    ok: true,
    printCount: receipt.printCount,
    transportId: deps.transport.id,
    transportLabel: deps.transport.label,
  }
}
