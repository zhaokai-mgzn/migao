// case_ids: OR-070
/**
 * 「安装位置」快捷词 chips（issue #7856）。
 *
 * 判据（每条都会红）：
 * ① 词表 = 常用空间，且 chips 只由**这一份**列表渲染（不是第二处手写清单）；
 * ② 点未选中的 ⇒ `onPick(空间名)`；点**已选中**的 ⇒ `onPick('')`（再点一次 = 清空）；
 * ③ 选中态由当前值**回显**（`aria-pressed`），比较前 trim（首尾空白不算另一个空间）；
 * ④ 🔴 chips 只是录入捷径：组件**不**校验自由文本（词表外的值照旧原样回传 —— 由上游决定）。
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import InstallRoomChips, { INSTALL_ROOM_OPTIONS } from '@/components/orders/InstallRoomChips'

describe('安装位置快捷词 chips（#7856）', () => {
  it('① 词表覆盖常用空间，且 chips 数量 = 词表长度（单一源）', () => {
    render(<InstallRoomChips value="" onPick={() => {}} />)
    expect(INSTALL_ROOM_OPTIONS).toContain('主卧')
    expect(INSTALL_ROOM_OPTIONS).toContain('阳台')
    expect(INSTALL_ROOM_OPTIONS).toContain('儿童房')
    // 不止三五个：常用空间要一眼点得到（少了说明词表被砍）
    expect(INSTALL_ROOM_OPTIONS.length).toBe(14)
    expect(screen.getAllByRole('button')).toHaveLength(INSTALL_ROOM_OPTIONS.length)
    expect(screen.getByTestId('install-room-chip-主卧')).toHaveTextContent('主卧')
  })

  it('② 点未选中的 ⇒ onPick(空间名)；点已选中的 ⇒ onPick("")（再点一次清空）', () => {
    const onPick = vi.fn()
    render(<InstallRoomChips value="主卧" onPick={onPick} />)
    fireEvent.click(screen.getByTestId('install-room-chip-阳台'))
    expect(onPick).toHaveBeenLastCalledWith('阳台')
    fireEvent.click(screen.getByTestId('install-room-chip-主卧'))
    expect(onPick).toHaveBeenLastCalledWith('')
  })

  it('③ 选中态跟随当前值（trim 后比较）', () => {
    render(<InstallRoomChips value=" 阳台 " onPick={() => {}} />)
    expect(screen.getByTestId('install-room-chip-阳台')).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByTestId('install-room-chip-主卧')).toHaveAttribute('aria-pressed', 'false')
  })

  it('④ 词表外的自由输入不被「纠正」：无选中态、chip 点击照常回传', () => {
    const onPick = vi.fn()
    render(<InstallRoomChips value="我家阁楼" onPick={onPick} />)
    // 自由文本不是词表里的任何一项 ⇒ 一个都不该亮（也不该把值改写成最近的词）
    expect(
      screen.getAllByRole('button').filter((el) => el.getAttribute('aria-pressed') === 'true')
    ).toEqual([])
    fireEvent.click(screen.getByTestId('install-room-chip-书房'))
    expect(onPick).toHaveBeenLastCalledWith('书房')
  })
})
