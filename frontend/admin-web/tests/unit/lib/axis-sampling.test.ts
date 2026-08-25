// case_ids: UI-004
import { describe, it, expect } from 'vitest'
import { sampleTickIndices } from '@/lib/axis-sampling'

describe('sampleTickIndices — 订单趋势 x 轴刻度降采样', () => {
  it('1280 宽度 30 天数据下降采样：刻度数 ≤ 阈值且无密集重叠', () => {
    const width = 1280
    const count = 30
    const indices = sampleTickIndices(count, { width, maxTicks: 7, minGap: 60 })
    expect(indices.length).toBeGreaterThan(0)
    expect(indices.length).toBeLessThanOrEqual(7)

    // 相邻刻度像素间距 >= minGap（无密集重叠）
    const pointGap = width / Math.max(count - 1, 1)
    for (let i = 1; i < indices.length; i++) {
      const gap = (indices[i] - indices[i - 1]) * pointGap
      expect(gap).toBeGreaterThanOrEqual(60 - 1e-9)
    }
  })

  it('稀疏数据（7 天、宽屏）保留全部刻度', () => {
    const indices = sampleTickIndices(7, { width: 1280, maxTicks: 7, minGap: 60 })
    expect(indices).toEqual([0, 1, 2, 3, 4, 5, 6])
  })

  it('始终包含首个数据点', () => {
    expect(sampleTickIndices(30, { width: 1280 })[0]).toBe(0)
    expect(sampleTickIndices(7, { width: 600 })[0]).toBe(0)
  })

  it('空/单点数据不崩溃', () => {
    expect(sampleTickIndices(0, { width: 1280 })).toEqual([])
    expect(sampleTickIndices(1, { width: 1280 })).toEqual([0])
  })

  it('宽度未知（0/负）时仍按 maxTicks 降采样，不产生 NaN/Infinity', () => {
    for (const width of [0, -1]) {
      const indices = sampleTickIndices(30, { width, maxTicks: 7, minGap: 60 })
      expect(indices.length).toBeLessThanOrEqual(7)
      for (const i of indices) {
        expect(Number.isFinite(i)).toBe(true)
      }
    }
  })

  it('刻度索引单调递增且在数据范围内', () => {
    const indices = sampleTickIndices(30, { width: 500, maxTicks: 7, minGap: 40 })
    for (let i = 1; i < indices.length; i++) {
      expect(indices[i]).toBeGreaterThan(indices[i - 1])
    }
    expect(indices[indices.length - 1]).toBeLessThan(30)
  })
})
