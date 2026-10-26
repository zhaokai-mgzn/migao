/**
 * **加工费组合**（`processing_fee_combinations` 的「组合键」）的展示取值口 —— 单一实现（issue #7833）。
 *
 * ## 什么是「组合键」（口径来自后端，不是本文件发明的）
 *
 * 加工费不按单个加工项定价，而是按**一起用的那几个加工项**定价：组合键 =
 * `processingItems[].name` 的集合（服务端 `ProcessingFeeQueryService.featureNames()` 只读这个数组）。
 * 该数组里既有**手选**加工项（韩褶 / 定型 / 打孔 …），也有**系统推算**的自动特征
 * （超高 / 超宽 / 倒幅 / 拼接 —— 判定在服务端，前端只展示结论）。
 *
 * ## 为什么要有这个模块
 *
 * 用户 2026-10-26 逐字：「**JG-20261026-8172 这个加工单有超高倒幅，但是在加工单的各个环节
 * 都没有体现出来**」—— 四个面（加工单 A4 纸面 / 生产明细页 / 水洗唛 / 订单详情的加工单块）
 * 都要印组合项；若各自从 `processingItems` 里各取一遍，就是「同一真值四处投影」
 * （`migao-dev-flow` §17.3：改一处另一处不会红）。
 * ⇒ 取值 / 去重 / 空值口径**只在这里**，调用方只做排版。
 *
 * ## 三条硬口径
 *
 * 1. **只读快照**：调用方传**加工单快照行**（`ProcessingOrderItem`，生成加工单那一刻固化）
 *    —— 不是订单当前值。存量单没有该键 ⇒ 空数组（**不编造**，也不回落到订单侧现值）。
 * 2. **缺值不渲染**：名字不是非空字符串 ⇒ 丢弃（纸面绝不出现 `undefined` / `null`）。
 * 3. **去重保序**：同一名字只出现一次，顺序沿用后端数组（= 组合键的顺序，不重排 ——
 *    重排会让「纸上看到的组合」与「算钱用的组合」看起来不是一件东西）。
 */

/** 组合项的**结构**读取面：加工单快照行 / 订单行的 `processingItems` 都满足它 */
export interface ProcessingComboSource {
  processingItems?: readonly { name?: string | null }[] | null
}

/**
 * 组合项名字（去空、去重、保序）。
 *
 * @param source 加工单快照行（`ProcessingOrderItem`）或订单行（两者的 `processingItems` 同形）
 */
export function processingComboNames(source?: ProcessingComboSource | null): string[] {
  const items = source?.processingItems
  if (!Array.isArray(items)) return []
  const names: string[] = []
  for (const item of items) {
    const name = typeof item?.name === 'string' ? item.name.trim() : ''
    if (name === '' || names.includes(name)) continue
    names.push(name)
  }
  return names
}

/**
 * 组合项的一行文本（`韩褶、超高、倒幅、定型`）；空 ⇒ 空串（调用方据此**整行不渲染**）。
 *
 * @param separator 分隔符：纸面上用顿号（`、`，与「特殊选项」同口径）；屏幕摘要同。
 */
export function processingComboText(source?: ProcessingComboSource | null, separator = '、'): string {
  return processingComboNames(source).join(separator)
}

/**
 * 多条快照行（一张加工单的 `items`）的**并集**（去重保序）—— 生产明细页头部摘要用。
 *
 * 为什么取并集：页头是**整单**视野，逐行明细在下面的部位/工序区；页头摆一份并集
 * 让「这张单要不要倒幅 / 有没有超高」一眼可见，而不是让人逐行去拼。
 */
export function processingComboTextOfRows(
  rows?: readonly ProcessingComboSource[] | null,
  separator = '、',
): string {
  const merged: string[] = []
  for (const row of rows ?? []) {
    for (const name of processingComboNames(row)) {
      if (!merged.includes(name)) merged.push(name)
    }
  }
  return merged.join(separator)
}
