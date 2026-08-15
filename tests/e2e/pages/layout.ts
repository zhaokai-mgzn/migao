/**
 * Layout 断言工具 — 用 boundingBox + getComputedStyle 做确定性的几何/样式断言。
 *
 * 用途：验证「尺寸 / 长宽比 / 对齐 / 溢出」等布局真值（见 frontend-fix.layout 真值）。
 * 相比「元素存在/不存在」，能拦截纯 CSS/尺寸回归（如米宝最小化浮窗长宽比异常）。
 */
import { expect, type Locator } from '@playwright/test'

/** 断言元素宽高（默认容差 2px，可传入精确值或只断言某一维） */
export async function assertSize(
  locator: Locator,
  opts: { width?: number; height?: number; tolerance?: number },
): Promise<void> {
  const box = await locator.boundingBox()
  expect(box, `元素应有可测量的 bounding box`).not.toBeNull()
  const tol = opts.tolerance ?? 2
  if (opts.width !== undefined) {
    expect(
      Math.abs(box!.width - opts.width),
      `宽度应约为 ${opts.width}px，实际 ${Math.round(box!.width)}px`,
    ).toBeLessThanOrEqual(tol)
  }
  if (opts.height !== undefined) {
    expect(
      Math.abs(box!.height - opts.height),
      `高度应约为 ${opts.height}px，实际 ${Math.round(box!.height)}px`,
    ).toBeLessThanOrEqual(tol)
  }
}

/** 断言长宽比（width/height）接近给定值，默认容差 0.05 */
export async function assertAspectRatio(
  locator: Locator,
  ratio: number,
  tolerance = 0.05,
): Promise<void> {
  const box = await locator.boundingBox()
  expect(box, `元素应有可测量的 bounding box`).not.toBeNull()
  const actual = box!.width / box!.height
  expect(
    Math.abs(actual - ratio),
    `长宽比应约为 ${ratio.toFixed(2)}，实际 ${actual.toFixed(3)}`,
  ).toBeLessThanOrEqual(tolerance)
}

/** 断言两个元素的左边缘（或上边缘）对齐，默认容差 2px */
export async function assertAligned(
  a: Locator,
  b: Locator,
  opts: { axis?: 'x' | 'y'; tolerance?: number } = {},
): Promise<void> {
  const axis = opts.axis ?? 'x'
  const tol = opts.tolerance ?? 2
  const boxA = await a.boundingBox()
  const boxB = await b.boundingBox()
  expect(boxA, `元素 A 应有 bounding box`).not.toBeNull()
  expect(boxB, `元素 B 应有 bounding box`).not.toBeNull()
  const coordA = axis === 'x' ? boxA!.x : boxA!.y
  const coordB = axis === 'x' ? boxB!.x : boxB!.y
  expect(
    Math.abs(coordA - coordB),
    `${axis === 'x' ? '左边缘' : '上边缘'}应对齐（${axis === 'x' ? boxA!.x : boxA!.y} vs ${axis === 'x' ? boxB!.x : boxB!.y}）`,
  ).toBeLessThanOrEqual(tol)
}

/** 断言元素无内容溢出（scrollWidth/scrollHeight 不超过 client 尺寸） */
export async function assertNoOverflow(locator: Locator): Promise<void> {
  const { horizontal, vertical } = await locator.evaluate((el) => {
    return {
      horizontal: el.scrollWidth > el.clientWidth + 1,
      vertical: el.scrollHeight > el.clientHeight + 1,
    }
  })
  expect(horizontal, '元素不应横向溢出').toBe(false)
  expect(vertical, '元素不应纵向溢出').toBe(false)
}
