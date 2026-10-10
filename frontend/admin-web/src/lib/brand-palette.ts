/**
 * 品牌色单一真值源（issue #6665 第 6 条：金色四处硬编码，无单一源）。
 *
 * 为什么需要它：金色此前散在**五种写法**里 ——
 * `frontend/admin-web/src/app/(corporate)/page.tsx`、`services/page.tsx`、
 * `src/components/corporate/CorporateSection.tsx`、`src/components/corporate/CorporateNav.tsx`
 * 各写一份 Tailwind 任意值（`[#f6d27a]` / `[#e8b04b]` / `[#d48806]`），
 * `src/components/ui/Logo.tsx` 在 SVG 里又写死 `#FFC53D` → `#D48806`，改一处必然漂移。
 *
 * 用法（两条路，真值只有这一份）：
 *   · **Tailwind 类**（页面 / 组件）：`frontend/admin-web/tailwind.config.ts` 的 `gold` 调色板
 *     `import { gold } from './src/lib/brand-palette'` ⇒ 类名 `bg-gold-600` / `text-gold-500` / `from-gold-300`；
 *   · **SVG 属性**（Logo 这类不能吃类名的地方）：`import { gold } from '@/lib/brand-palette'` 直接取色值。
 *
 * ⚠️ 数值 = 被替换掉的那几个字面量**逐字**（只收敛来源，不改观感）。
 */
export const gold = {
  /** 首页 Hero 金色渐变的起点（原 `#f6d27a`） */
  300: '#f6d27a',
  /** Logo 渐变起点 / 金色主色（原 `#FFC53D`） */
  400: '#ffc53d',
  /** 金色星标与图标（原 `#e8b04b`） */
  500: '#e8b04b',
  /** 默认金色：柔光与导航细线（原 `#d48806`） */
  600: '#d48806',
} as const
