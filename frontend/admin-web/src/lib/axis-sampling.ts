// 织物质感改版：类目轴（x 轴）刻度降采样纯函数。
//
// 看板「订单趋势」在 1280 宽度下 30 天数据点密集，需要按可用像素宽度
// 对刻度做降采样，保证标签不密集重叠。抽成纯函数便于单测与复用。

export interface TickSamplingOptions {
  /** 轴可用像素宽度（<= 0 表示未知，仅按 maxTicks 降采样）。 */
  width?: number
  /** 最多展示的刻度数（默认 7）。 */
  maxTicks?: number
  /** 相邻刻度标签的最小像素间距（默认 60，低于即视为密集重叠）。 */
  minGap?: number
}

/**
 * 计算需要标注的数据点索引（升序）。
 *
 * 规则：同时满足「标签数 ≤ maxTicks」与「相邻标签像素间距 ≥ minGap」，
 * 取两个约束中更大的步长，保证既不重叠也不超量。
 */
export function sampleTickIndices(count: number, options: TickSamplingOptions = {}): number[] {
  const maxTicks = options.maxTicks ?? 7
  const minGap = options.minGap ?? 60

  if (count <= 0) return []
  if (count === 1) return [0]

  const width = options.width ?? 0
  // 每个数据点占用的像素宽（点均匀分布）。
  const pointGap = width > 0 ? width / Math.max(count - 1, 1) : 0

  // 满足最小间距的最小步长；宽度未知时退化为仅按 maxTicks 约束。
  const minGapStride = pointGap > 0 ? Math.ceil(minGap / pointGap) : 1
  const maxTickStride = Math.ceil(count / Math.max(maxTicks, 1))
  const stride = Math.max(1, minGapStride, maxTickStride)

  const indices: number[] = []
  for (let i = 0; i < count; i += stride) indices.push(i)
  return indices
}
