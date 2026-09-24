/**
 * Agent 深通道的**同页填充通道**（issue #5368 包 2）。
 *
 * ## 它解决什么
 *
 * 米宝是**浮动面板**（`components/ai-assistant/FloatingAssistant.tsx` 挂载
 * `components/business/MibaoChatPanel.tsx`，挂在 `(dashboard)/layout.tsx`）⇒
 * 商家可以站在建品页 / 建单页上直接跟米宝说话，**表单就在屏幕下方**。
 * 米宝识别完要把字段推给当前页面表单 —— 本模块就是那条通道。
 *
 * ## 🔴 为什么是内存事件（硬约束 1：零 PII 落盘）
 *
 * 订单侧的字段里有**客户名 / 电话 / 地址**。任何「方便」的通道都会把它们写进会落盘的地方：
 * - `?prefill=<base64>` ⇒ 进 nginx access log 与 Referer（本仓已为同类形态吃过一次账：
 *   `interact` form 卡预填手机号把完整号码带进了 `final_text`）；
 * - `localStorage` / `sessionStorage` ⇒ 留在磁盘上；
 * - `console.log(plan)` ⇒ 进浏览器日志采集。
 *
 * ⇒ 只用 `window.dispatchEvent(new CustomEvent(...))`：载荷活在**当前页面内存**里，
 * 刷新即消失（刷新后表单本来也是空的）。机械判据见
 * `frontend/admin-web/tests/unit/lib/agent-page-fill.test.ts`（静态扫描 + 判别力红证）。
 *
 * ## 与页面快通道的关系（硬约束：**两个入口不许耦合成一条**）
 *
 * 依赖方向是**单向**的：本模块可以复用快通道的映射函数与标记常量；
 * 快通道（`lib/image-recognize.ts` / `components/image-recognize/ImageRecognizeButton.tsx`）
 * **零引用**本模块 —— 「图 → 字段 → 填表」这条路不依赖 LLM 也能走
 * （判据 5：防止后人把纯技术能力变成「必须有 Agent 才能用」）。
 */
import type { RecognizedField } from './api'
import { RECOGNIZE_SOURCE_TAG } from './image-recognize'

/** SSE 事件名 / 计划组件名（与后端 `app/api/sse.py::SSEEvent.page_fill` 同源） */
export const PAGE_FILL_COMPONENT = 'page_fill'

/** **Agent 解读/推荐**的来源标记（与 `[图片识别]` 必须不同：否则商家无从判断该信哪一格） */
export const PAGE_FILL_SOURCE_INTERPRETED = '[米宝解读]'

/** **浏览器内存**事件名（不是 URL、不是存储键：它不落盘） */
export const PAGE_FILL_EVENT = 'mibao:page-fill'

/** 计划的目标页面（同一份计划只喂给它自己那页，别页收到即忽略） */
export type PageFillTarget = 'product' | 'order'

export interface PageFillCandidate {
  value: string
  /** 为什么它最接近（内核给的解释，UI 直接转述 —— 前端不另写一份文案） */
  reason: string
}

/** 一格（与后端 `app/vision/deep_channel.py::build_page_fill` 的字段条目一一对应） */
export interface PageFillField {
  key: string
  label: string
  value: string | null
  source: string | null
  reason: string | null
  candidates: PageFillCandidate[]
  note: string | null
  note_source: string | null
}

export interface PageFillPlan {
  component: typeof PAGE_FILL_COMPONENT
  target_type: PageFillTarget
  fields: PageFillField[]
}

function isTarget(value: unknown): value is PageFillTarget {
  return value === 'product' || value === 'order'
}

/** 形状校验：**只认** `page_fill` 计划（别的事件一律不填表，防止把别的载荷当计划执行） */
export function isPageFillPlan(value: unknown): value is PageFillPlan {
  if (!value || typeof value !== 'object') return false
  const plan = value as Partial<PageFillPlan>
  return plan.component === PAGE_FILL_COMPONENT && isTarget(plan.target_type) && Array.isArray(plan.fields)
}

/**
 * 取「**值非空** + 来源匹配」的格子（可直接喂给既有映射函数 `buildProductPrefill` /
 * `buildOrderPrefill` —— 两个入口共用同一份映射，不另写第二份表）。
 *
 * 🔴 两条口径（与后端一致）：
 * - `value` 为空 ⇒ **不收**（内核有意留空：不确定的宁可不填）；
 * - **歧义格**（有 `candidates`、`value` 为空）⇒ 同样不收 —— 它是给商家挑的候选，
 *   不是可以替他拍板的值（判据 3）。
 */
export function fieldsOfSource(
  plan: PageFillPlan | null | undefined,
  source: string,
): RecognizedField[] {
  if (!plan || !Array.isArray(plan.fields)) return []
  return plan.fields.filter(
    (field) =>
      typeof field.value === 'string' &&
      field.value.trim() !== '' &&
      field.source === source,
  )
}

/** 已填格子里的**解读来源**键（驱动 `interpreted-marker-*` 徽标；与识别徽标清单互斥） */
export function interpretedKeysOf(plan: PageFillPlan | null | undefined): string[] {
  return fieldsOfSource(plan, PAGE_FILL_SOURCE_INTERPRETED).map((field) => field.key)
}

/** 快通道标记常量（转发一次，避免调用方 import 两个模块——**不是**第二份实现） */
export const PAGE_FILL_SOURCE_RECOGNIZED = RECOGNIZE_SOURCE_TAG

/**
 * 把计划推给**当前页面**（内存事件，不落盘）。
 *
 * SSR/无 window 环境下静默返回（同 `MibaoChatPanel` 里对 `window` 的处置）。
 */
export function emitPageFill(plan: PageFillPlan): void {
  if (typeof window === 'undefined') return
  if (!isPageFillPlan(plan)) return
  window.dispatchEvent(new CustomEvent(PAGE_FILL_EVENT, { detail: plan }))
}

/**
 * 订阅**本页**的同页填充（返回退订函数）。只接收 `target` 与自身一致的计划 ——
 * 同一浏览器里两个页面组件不共存，但这条比对让「张冠李戴」在类型/行为上都不可发生。
 */
export function subscribePageFill(
  target: PageFillTarget,
  handler: (plan: PageFillPlan) => void,
): () => void {
  if (typeof window === 'undefined') return () => {}
  const listener = (event: Event) => {
    const plan = (event as CustomEvent).detail
    if (isPageFillPlan(plan) && plan.target_type === target) handler(plan)
  }
  window.addEventListener(PAGE_FILL_EVENT, listener)
  return () => window.removeEventListener(PAGE_FILL_EVENT, listener)
}