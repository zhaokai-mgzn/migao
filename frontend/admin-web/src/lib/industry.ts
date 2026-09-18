/**
 * 行业取值受控词表 v1（issue #4361 冻结；本单 #4363 前端半边消费）。
 *
 * 为什么必须受控：行业是**行业模板键**（开租自动套用生产种子 / 知识模板都按它匹配）。
 * 注册页此前是自由文本（placeholder「如：布艺纺织、家居建材、电子商务等」）⇒ 模板键不可靠，
 * 且匹配不到模板时**没有任何提示**（静默不套用）。
 *
 * 口径（冻结，勿在别处复制第二份）：
 * - `curtain` 布艺 / 窗帘 —— 自动套用该行业生产种子（工序库 + 工艺路线）；
 * - `other`   其他       —— **不套用**（无模板），注册页显式提示，不静默落默认模板。
 *
 * 落库/提交一律用 `code`，界面只显示 `label`；未知取值（存量自由文本）**不猜**显示名。
 */

export interface IndustryOption {
  code: string
  label: string
  /** 该行业是否有预置模板可自动套用（v1 只有 curtain 有） */
  appliesTemplate: boolean
}

export const INDUSTRY_OPTIONS: IndustryOption[] = [
  { code: 'curtain', label: '布艺 / 窗帘', appliesTemplate: true },
  { code: 'other', label: '其他', appliesTemplate: false },
]

/** code → 显示名；未知取值返回 undefined（**不**编造显示名，静默 = 未知） */
export function industryLabel(code?: string | null): string | undefined {
  return INDUSTRY_OPTIONS.find((o) => o.code === code)?.label
}

/** 该行业 code 是否套用预置模板（未知/空值一律 false —— 未知 ≠ curtain） */
export function industryAppliesTemplate(code?: string | null): boolean {
  return INDUSTRY_OPTIONS.find((o) => o.code === code)?.appliesTemplate === true
}
