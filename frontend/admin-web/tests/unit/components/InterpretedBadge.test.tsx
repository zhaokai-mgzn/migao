// case_ids: PR-008
/**
 * `InterpretedBadge` —— **Agent 解读/推荐**字段的来源徽标（issue #5368 包 2 · 硬约束 3）。
 *
 * 为什么必须与 `RecognizedBadge`（`[图片识别]`）**长得不一样**：
 * 同一个表单里，「图上抄下来的」与「米宝推的」是两种可信度完全不同的东西 ——
 * 标注相同 ⇒ 商家无从判断该信哪一格（issue 原文）。
 * 故本组件：文案不同（`[米宝解读]`）、testid 前缀不同（`interpreted-marker-*`）、配色不同（amber）。
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import { InterpretedBadge } from '@/components/image-recognize/InterpretedBadge'
import { RecognizedBadge } from '@/components/image-recognize/ImageRecognizeButton'
import { PAGE_FILL_SOURCE_INTERPRETED } from '@/lib/agent-page-fill'
import { RECOGNIZE_SOURCE_TAG } from '@/lib/image-recognize'

describe('InterpretedBadge（Agent 解读来源标注）', () => {
  it('渲染 [米宝解读] 文案，并带可定位的 interpreted-marker-* testid', () => {
    render(<InterpretedBadge fieldKey="material" />)
    const badge = screen.getByTestId('interpreted-marker-material')
    expect(badge.textContent).toBe(PAGE_FILL_SOURCE_INTERPRETED)
  })

  it('与识别徽标**可区分**：文案不同、testid 前缀不同（两枚同时在场也不混）', () => {
    render(
      <>
        <RecognizedBadge fieldKey="craft" />
        <InterpretedBadge fieldKey="craft" />
      </>,
    )
    const recognized = screen.getByTestId('recognized-marker-craft')
    const interpreted = screen.getByTestId('interpreted-marker-craft')
    expect(recognized.textContent).toBe(RECOGNIZE_SOURCE_TAG)
    expect(interpreted.textContent).toBe(PAGE_FILL_SOURCE_INTERPRETED)
    expect(recognized.textContent).not.toBe(interpreted.textContent)
    expect(recognized.className).not.toBe(interpreted.className)
  })
})