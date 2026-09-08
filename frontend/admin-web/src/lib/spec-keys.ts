/**
 * 规格属性（specifications）key 中英双向映射（issue #3044）
 *
 * 背景：同一套「规格属性」存在两种 key 风格——ai-agent 建品/更新用中文 key
 * （克重/材质/功能/工艺/风格/图案）落库 product_attributes；admin-web 手动表单
 * （ProductAttributes 组件）内部用英文 key（weight/material/function/craft/style/
 * pattern）。详情页对未识别 key 原样展示（中文 key 天然可读），但编辑页只读英文
 * key → agent 建的商品编辑时不反显。
 *
 * 约定（单一事实源）：
 * - 存储统一为中文 key（与 agent 一致，详情页中文展示）；
 * - 编辑表单内部沿用英文 key（组件既有约定）；
 * - 本模块是唯一的边界转换层：反显 中文→英文，提交 英文→中文。
 * - 未知 key 一律原样保留，绝不丢数据。
 */

/** 中文 key → 英文 key（agent 落库风格 → 编辑表单内部约定） */
export const SPEC_CN_TO_EN: Record<string, string> = {
  克重: 'weight',
  材质: 'material',
  功能: 'function',
  工艺: 'craft',
  风格: 'style',
  图案: 'pattern',
}

/** 英文 key → 中文 key（编辑表单内部约定 → agent 落库风格） */
export const SPEC_EN_TO_CN: Record<string, string> = {
  weight: '克重',
  material: '材质',
  function: '功能',
  craft: '工艺',
  style: '风格',
  pattern: '图案',
}

function mapSpecKeys(
  specs: Record<string, string> | undefined,
  mapping: Record<string, string>,
): Record<string, string> {
  if (!specs || typeof specs !== 'object') return {}
  const out: Record<string, string> = {}
  for (const [key, value] of Object.entries(specs)) {
    const mapped = mapping[key] || key
    out[mapped] = value
  }
  return out
}

/** 反显：中文 key（存储）→ 英文 key（编辑表单读取） */
export function toEnglishSpecKeys(
  specs: Record<string, string> | undefined,
): Record<string, string> {
  return mapSpecKeys(specs, SPEC_CN_TO_EN)
}

/** 提交：英文 key（编辑表单）→ 中文 key（落库统一，与 ai-agent 一致） */
export function toChineseSpecKeys(
  specs: Record<string, string> | undefined,
): Record<string, string> {
  return mapSpecKeys(specs, SPEC_EN_TO_CN)
}
