/**
 * 设计基线的字号真值源（issue #6668）。
 *
 * ## 为什么要有这个文件
 *
 * 修前本仓的「规范 == 真值」是断的：`docs/design/ui-design-spec.md` 自称 v8.0、写主色
 * `#2F54EB`（AntD 蓝），而 `frontend/admin-web/tailwind.config.ts` 早已换成「织物质感」
 * （`primary-500 = #48618f`）⇒ 任何照文档做的新页面必然漂回蓝。字号这一层同理：
 * 文档给了 8 级阶梯，而代码里没有任何一处声明它是契约 ⇒ 下一个人把 `text-xs` 当 10px 用
 * 也不会有东西变红。
 *
 * ⇒ 把字号阶梯从文档搬进代码（此处 = 真值），由 `tailwind.config.ts` 的
 * `theme.extend.fontSize` 消费（页面写 `text-sm` / `text-2xl`），而文档
 * `docs/design/design-baseline.md` 只指向它、不复制它。
 *
 * ## 口径（逐条可复算）
 *
 * - `size` / `lineHeight` 用 px（与文档、与 `fontsize` 的语义一致；值本身是阶梯的真值）；
 * - 行高比固定 1.5（既有两处写法实测一致：`text-xs` 的 tailwind 默认 12/16 是唯一例外，
 *   本仓改用 12/18；`text-sm` 14/22 ⇒ 本表 14/21，差 1px 属有意收紧，见下）；
 * - 下限 12px：低于 12px 的字号不进阶梯（商家后台与 C 端最小可读档）。
 *   ⚠️ 移动端（Taro 两 app）的另一条下限（设计尺度 24 = 12.8 CSS px @390）由
 *   `tests/unit_ci_workflows/test_bmini_mobile_typography_floor.py` 独立守 —— 那条不许松，
 *   本文件不改它、也不与它合并（两套坐标系，合并即错）。
 *
 * ## 边界（照实登记，§19.1）
 *
 * - 本文件只承载字号；颜色真值源是 `tailwind.config.ts`（`gold` 的数值本体在
 *   `frontend/admin-web/src/lib/brand-palette.ts`，`tailwind.config.ts` 只把它接成调色板），
 *   阴影真值源是 `tailwind.config.ts` 的 `theme.extend.boxShadow`；
 * - 它不判业务：不决定某个标题该用哪一级（那是评审 + 读图的事），只钉「档位与像素」。
 */

export interface TypeScaleStep {
  /** Tailwind 工具类名（页面只许写它，不许写任意值 `text-[13px]`） */
  readonly className: string
  /** 用途（与 `docs/design/design-baseline.md` 的表逐字同源） */
  readonly usage: string
  /** 字号（px） */
  readonly size: number
  /** 行高（px） */
  readonly lineHeight: number
  /** 字重 */
  readonly weight: 400 | 600
}

/** 字号阶梯（真值）。顺序 = 从大到小；新增档位必须同时给出用途。 */
export const TYPE_SCALE: readonly TypeScaleStep[] = [
  { className: 'text-2xl', usage: '页面标题（h1）', size: 24, lineHeight: 36, weight: 600 },
  { className: 'text-xl', usage: '区块标题（h2）', size: 20, lineHeight: 30, weight: 600 },
  { className: 'text-lg', usage: '卡片标题 / 弹层标题（h3）', size: 18, lineHeight: 27, weight: 600 },
  { className: 'text-base', usage: '强调正文（不常用）', size: 16, lineHeight: 24, weight: 400 },
  { className: 'text-sm', usage: '默认正文、表格内容、表单文字', size: 14, lineHeight: 21, weight: 400 },
  { className: 'text-xs', usage: '辅助说明、时间戳、角标', size: 12, lineHeight: 18, weight: 400 },
]

/** 字号下限（px）：低于它的字号不进本阶梯（写 `text-[11px]` 属越界） */
export const TYPE_FLOOR_PX = 12

/** 行高比（`lineHeight / size`）；`text-xs` 的 18/12 = 1.5 也在内 ⇒ 全表一个比值 */
export const LINE_HEIGHT_RATIO = 1.5

/** Tailwind 的 `fontSize` 扩展形态：`className 后缀` → `[size, { lineHeight }]` */
export const fontSize = Object.fromEntries(
  TYPE_SCALE.map((s) => [s.className.replace(/^text-/, ''), [`${s.size}px`, { lineHeight: `${s.lineHeight}px` }]]),
) as Record<string, [string, { lineHeight: string }]>
