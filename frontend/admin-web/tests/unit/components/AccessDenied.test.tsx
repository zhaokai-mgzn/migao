// case_ids: UI-085, UI-046
// 403 终态面说人话、不上内部权限码（issue #6669 第 6 条）。
/**
 * 「无权访问该页面」终态面（issue #6669 第 6 条）。
 *
 * 修前逐字：`当前账号缺少权限 production:view，如需开通请联系管理员在「员工管理」中调整权限。`
 * —— 把**内部权限码**摆给商家（§31 P3「不摆内部标识」）：看不懂、也无从行动。
 *
 * 判据（判别力）：
 * ① 说人话：出现「你的岗位没有这个功能的权限」+ 去哪改（「员工管理」）；
 * ② **域内任何权限码形态都不许上屏**：`<域>:<动作>` 形态（本例 `production:view`）零命中；
 * ③ 负控：标题「无权访问该页面」仍在（防「整块 403 面被删」也判绿）。
 */
import React from 'react'
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import AccessDenied from '@/components/common/AccessDenied'

/** 权限码形态 = 小写域 + 冒号 + 小写动作（与后端 `@RequirePermission` 同形） */
const PERMISSION_CODE = /\b[a-z][a-z_]*:[a-z][a-z_]*\b/

describe('403 终态面（issue #6669 第 6 条）', () => {
  it('说人话：讲清「谁的权限」+「去哪开通」，且**不含任何权限码**', () => {
    const { container } = render(<AccessDenied />)
    const text = container.textContent ?? ''

    // ③ 负控：面本身在
    expect(screen.getByText('无权访问该页面')).toBeInTheDocument()
    // ① 说人话
    expect(text).toContain('你的岗位没有这个功能的权限')
    expect(text).toContain('员工管理')
    // ② 内部标识不上屏（修前形态逐字含 `production:view` ⇒ 本条红）
    expect(text).not.toMatch(PERMISSION_CODE)
    expect(text).not.toContain('production:view')
  })

  it('组件结构上没有回显标识的入口（纯展示、不吃 props）', () => {
    // 空 props 调用不报错 = 没有必需入参；这比「记得别渲染它」可靠（结构面判据）
    render(<AccessDenied />)
    expect(screen.getByText(/联系管理员/)).toBeInTheDocument()
  })
})
