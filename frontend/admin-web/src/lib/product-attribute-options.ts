/**
 * 商品规格属性（`specifications`）的**下拉选项单一真值源**（issue #7528）。
 *
 * 为什么要单独一个模块：这些选项原先只写在
 * `frontend/admin-web/src/components/products/ProductAttributes.tsx` 里，而
 * 「从商家写的那句话里认出材质 / 功能 / 工艺 / 风格 / 花型」
 * （`frontend/admin-web/src/lib/declared-facts.ts`）是**第二个消费点** —— 它不能 import 组件
 * （那会把 React 拉进纯函数库）。两处各写一份 = 本仓反复复发的「同一真值两处口径」：
 * 组件里新增一个选项、匹配器认不出来，**没有任何东西会变红**。
 *
 * 🔴 中文名（材质 / 功能 / …）**不在本文件再写一遍**：真值在
 * `frontend/admin-web/src/lib/attribute-keys.ts` 的 `SPEC_EN_TO_CN`，本文件只放「值 → 显示」。
 */
/** 一个下拉选项（`value` 是落库/匹配用的规范值，`label` 是商家看到的文案） */
export interface AttrOption {
  value: string
  label: string
}

/** 「其他（自定义输入）」哨兵值 —— 与 `ProductAttributes.tsx` 的 Select 语义一致，**不是**可真落库的属性值 */
export const CUSTOM_OPTION_VALUE = '__custom__'

export const WEIGHT_OPTIONS: AttrOption[] = [
  { value: '', label: '请选择' },
  { value: '100g以下', label: '100g以下' },
  { value: '100-200g', label: '100-200g' },
  { value: '200-300g', label: '200-300g' },
  { value: '300-400g', label: '300-400g' },
  { value: '400g以上', label: '400g以上' },
  { value: CUSTOM_OPTION_VALUE, label: '其他' },
]

export const MATERIAL_OPTIONS: AttrOption[] = [
  { value: '', label: '请选择' },
  { value: '涤纶', label: '涤纶' },
  { value: '棉', label: '棉' },
  { value: '麻', label: '麻' },
  { value: '丝绸', label: '丝绸' },
  { value: '混纺', label: '混纺' },
  { value: '绒布', label: '绒布' },
  { value: '雪尼尔', label: '雪尼尔' },
  { value: CUSTOM_OPTION_VALUE, label: '其他' },
]

export const FUNCTION_OPTIONS: AttrOption[] = [
  { value: '', label: '请选择' },
  { value: '遮光', label: '遮光' },
  { value: '隔热', label: '隔热' },
  { value: '防紫外线', label: '防紫外线' },
  { value: '防水', label: '防水' },
  { value: '防霉', label: '防霉' },
  { value: '隔音', label: '隔音' },
  { value: CUSTOM_OPTION_VALUE, label: '其他' },
]

export const CRAFT_OPTIONS: AttrOption[] = [
  { value: '', label: '请选择' },
  { value: '提花', label: '提花' },
  { value: '印花', label: '印花' },
  { value: '绣花', label: '绣花' },
  { value: '烫金', label: '烫金' },
  { value: '植绒', label: '植绒' },
  { value: '色织', label: '色织' },
  { value: CUSTOM_OPTION_VALUE, label: '其他' },
]

export const STYLE_OPTIONS: AttrOption[] = [
  { value: '', label: '请选择' },
  { value: '现代简约', label: '现代简约' },
  { value: '北欧', label: '北欧' },
  { value: '中式', label: '中式' },
  { value: '欧式', label: '欧式' },
  { value: '田园', label: '田园' },
  { value: '轻奢', label: '轻奢' },
  { value: CUSTOM_OPTION_VALUE, label: '其他' },
]

export const PATTERN_OPTIONS: AttrOption[] = [
  { value: '', label: '请选择' },
  { value: '纯色', label: '纯色' },
  { value: '条纹', label: '条纹' },
  { value: '格子', label: '格子' },
  { value: '花卉', label: '花卉' },
  { value: '几何', label: '几何' },
  { value: '卡通', label: '卡通' },
  { value: CUSTOM_OPTION_VALUE, label: '其他' },
]

/**
 * 规格属性组（`key` = 表单内部英文 key，与 `SPEC_EN_TO_CN` 的键同一套）。
 *
 * 顺序即「同一段文字里先命中哪一组」的顺序；组内取**第一个**命中项（确定性，不猜）。
 */
export const SPEC_ATTRIBUTE_GROUPS: Array<{ key: string; options: AttrOption[] }> = [
  { key: 'weight', options: WEIGHT_OPTIONS },
  { key: 'material', options: MATERIAL_OPTIONS },
  { key: 'function', options: FUNCTION_OPTIONS },
  { key: 'craft', options: CRAFT_OPTIONS },
  { key: 'style', options: STYLE_OPTIONS },
  { key: 'pattern', options: PATTERN_OPTIONS },
]
