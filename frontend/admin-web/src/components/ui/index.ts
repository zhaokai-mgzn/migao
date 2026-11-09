export { default as Button } from './Button'
export { default as Input } from './Input'
export { default as Select } from './Select'
// issue #7397：下拉控件的唯一控件铬（业务面原生 <select> 必须用它）
export { SELECT_CONTROL, SELECT_CONTROL_FIELD, SELECT_BASE } from './Select'
export { default as Badge } from './Badge'
export { default as StatusBadge } from './StatusBadge'
export { default as Table } from './Table'
export { default as Pagination } from './Pagination'
export { default as Modal } from './Modal'
export { default as SearchBar } from './SearchBar'
export { default as EmptyState } from './EmptyState'
export { default as Card } from './Card'
export { default as Loading } from './Loading'
// issue #8036：列表页**加载态**的唯一形态（灰底 + 脉冲占位，纯布局、无文案）
export { default as TableSkeleton } from './TableSkeleton'
export { default as FileUpload } from './FileUpload'
export { default as NumberInput } from './NumberInput'
// issue #8004：涉钱 / 带小数数量面**唯一**的数字输入原语（`type="number"` 会吞中间态与千分位）
export { default as DecimalInput, useDecimalValidity } from './DecimalInput'
export type { DecimalInputProps } from './DecimalInput'
// issue #7007：页内版式原语（页面头 / 页内一级容器 / 无状态筛选卡片）
export { default as PageHeader } from './PageHeader'
export { default as PageCard } from './PageCard'
export { default as SearchPanel } from './SearchPanel'
// 2026-10-17：单据列表**行内动作**的唯一形态（销售订单 / 作业看板共用一份定义）。
// 2026-11-09 用户裁定：观星台所有列表页的操作列**逐条平铺**、不再收进「⋯」⇒
// 旧的「主行动 + ⋯ 菜单」原语 `RowActions` 已退役（判据 = `scripts/row-action-flat-scan.mjs`）。
export { default as RowActionLink } from './RowActionLink'

export type { TableColumn } from './Table'
export type { SearchField } from './SearchBar'
export type { SearchFieldSpec } from './SearchPanel'
export type { NumberInputProps } from './NumberInput'
