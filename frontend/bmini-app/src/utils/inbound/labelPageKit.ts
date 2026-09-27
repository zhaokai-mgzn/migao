/**
 * 标签页**共用件**（issue #5640；来源 = P3 `pages/worker/inbound/index.tsx` 里被复制风险最高的两小块）
 *
 * ## 为什么要把它们从页面里搬出来
 *
 * 「同族页面各写一套流程，第二套必然与第一套分叉」是本单固化的一类缺陷（见
 * `tests/inbound-reprint-code-space.test.ts` 的 G3）。P3 的入库页与 P4 的补打页是**同族**：
 * 都要「把服务端详情渲染成 50×30mm 位图 + 送打印」。其中**画布工厂**与**组件缺失文案**这两块
 * 一旦各写一份，就会出现「一边修了、另一边没修」——而两边**都不会报错**。
 *
 * ⇒ 共用件放这里，两个页面都从这里取（守卫 G3 判：渲染标签的页面必须引用它们，
 * 且全仓 `function createH5CanvasFactory` 恰好只有一处 = 本文件）。
 *
 * ## 预览与送打印**同一份**绘制计划
 *
 * `renderLabelPreview` 与 `printInboundLabel` 的 `render()` 调的是**同一个** `renderInboundLabel`
 * ⇒ 屏上看到的版心就是送到打印机的位图（1:1，不缩放不裁切）。画不出来时**明说**
 * （`notice` 非空），不静默给一张白图。
 */
import { renderInboundLabel, type LabelCanvasElementLike, type RenderedLabel } from './labelCanvas'
import { layoutInboundLabel, type InboundLabelView } from './labelLayout'
import { printFailureHint } from './printCapability'

/**
 * `lpapi-ble` 加载不出来时给工人的话（取能力台账里 `sdk-unavailable` 那一条 —— 页面不另写一句，
 * 否则「五种失败各有各的文案」这条口径会在第二个页面上破功）。
 */
export const SDK_UNAVAILABLE_HINT = printFailureHint('sdk-unavailable')

/** 画不出来时的说明（屏上必须出现：空白预览会被当成"打出来是白的"） */
export const PREVIEW_UNAVAILABLE_NOTICE = '标签已生成，但本机画不出预览（打印仍会按同一份版式送图）。'

/**
 * 画布工厂：h5 用真 DOM canvas；无 DOM（weapp）⇒ 返回时显式抛错由渲染器报出来
 * （**不静默返回白图**：白图会被当成「打出来了」）。
 */
export function createH5CanvasFactory(): (widthPx: number, heightPx: number) => LabelCanvasElementLike {
  return (widthPx: number, heightPx: number) => {
    const doc: any = typeof document === 'undefined' ? null : document
    if (!doc) throw new Error('当前平台没有 DOM canvas（标签预览仅 h5 可用）')
    const canvas = doc.createElement('canvas')
    canvas.width = widthPx
    canvas.height = heightPx
    return canvas as LabelCanvasElementLike
  }
}

export interface LabelPreview {
  /** 预览图（`''` = 本机画不出来 —— 此时 `notice` 非空，页面必须上屏） */
  url: string
  widthPx: number
  heightPx: number
  notice: string
}

/**
 * 渲染一张标签的**屏上预览**（与送打印同一份计划）。
 *
 * @param view 服务端详情（字段真值只从服务端来，端侧不拼第二份）
 */
export function renderLabelPreview(view: InboundLabelView): LabelPreview {
  try {
    const rendered: RenderedLabel = renderInboundLabel(view, createH5CanvasFactory())
    const url = String((rendered.canvas as any)?.toDataURL?.('image/png') || '')
    return {
      url,
      widthPx: rendered.widthPx,
      heightPx: rendered.heightPx,
      notice: url ? '' : PREVIEW_UNAVAILABLE_NOTICE,
    }
  } catch {
    // 画不出来也要能显示版心（版心是**版面**的事实，不依赖本机有没有 canvas）
    const plan = layoutInboundLabel(view)
    return { url: '', widthPx: plan.widthPx, heightPx: plan.heightPx, notice: PREVIEW_UNAVAILABLE_NOTICE }
  }
}
