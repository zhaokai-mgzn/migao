'use client'

/**
 * **裁高配置面板**（issue #6585 P1：配置指挥台 v2 的「⑦ 裁高配置」域）。
 *
 * ## 它是什么
 *
 * 板子（`ProcessConfigBoard`）里原 tab「裁高配置」的那一块，**零逻辑搬运**成一个可独立挂载的面板：
 * 外层容器带 `data-testid="cutting-height-panel"`（就绪度第 ⑤ 步的「去处理」要滚到它），
 * 里面是自足的 `CuttingHeightConfigPanel`（它**自带**读面与写面 —— 本面板**不复刻**它的配置状态）。
 *
 * ## 这一层为什么还要自己发一次读面
 *
 * 裁高面板只有一个 `source` 是本层需要的（「配没配 / 存的是商家配置还是系统默认」），
 * 板子用它算**就绪度第 ⑤ 步**。就绪度卡留在板子上、数据在面板里 ⇒ 面板必须**自包含**地读一次
 * （`cuttingHeightApi.get()`）并把 `source` 留在自己这里；`CuttingHeightConfigPanel` **自己**
 * 还会再读一次（它的写面状态由它自己管）—— 与搬运前的板子**逐字相同**（板子当时也发这一次）。
 *
 * ## `embedded`
 *
 * `embedded=true` ⇒ **不渲染本层区块标题**（域面板由指挥台的域标题回答「这是什么」）；
 * 其余（容器 testid、内部面板、读面）一律相同 —— 面板的行为不随挂载形态变。
 *
 * 真值源：`frontend/admin-web/src/components/production/CuttingHeightConfigPanel.tsx`（读/写/预览全在它那里）。
 */
import { CuttingHeightConfigPanel } from '@/components/production/CuttingHeightConfigPanel'
import { useCutFeature, type CutFeature } from '@/components/production-config/features'

export function CuttingHeightPanel({
  store,
  embedded = false,
}: {
  /** 共享同一份**就绪信号**（板子传入；issue #6585 ⇒ 首屏只发一次读面）；不传 ⇒ 本组件自包含取数 */
  store?: CutFeature
  embedded?: boolean
} = {}) {
  // hook 必须无条件调用；板子传入 `store` 时 `enabled=false`（同源 hook 已取过 ⇒ 不重复发请求）
  const own = useCutFeature({ enabled: !store })
  const cut = store ?? own

  // `cut.source` 是就绪度第 ⑤ 步的输入（板子读它算卡）；本面板只保证「读面在这里发起」这一半，
  // 展示（「系统默认值 / 已保存」）由内部 `CuttingHeightConfigPanel` 按自己的读数回答。
  void cut.source

  return (
    <section className="space-y-3" data-testid="cutting-height-panel">
      {!embedded && (
        <div className="mb-1">
          <h2 className="text-base font-medium text-neutral-900">裁高配置</h2>
          <p className="mt-0.5 text-sm text-neutral-500">
            这一刀该多高：<strong>裁剪高度 = 成品高 + 命中的增量项</strong>。命中口径由服务端判。
          </p>
        </div>
      )}
      <CuttingHeightConfigPanel />
    </section>
  )
}

export default CuttingHeightPanel
