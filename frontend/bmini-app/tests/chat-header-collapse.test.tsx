// case_ids: BM-028
/**
 * 手机端顶部品牌渐变层可折叠（issue #7265）
 *
 * 用户逐字：「黄金策上面的顶层渐变层那块区域，应该允许向上折叠，增大对话文字显示空间」。
 */
import '@testing-library/jest-dom'
import { render, screen, fireEvent } from '@testing-library/react'
import ChatHeader, { nextHeaderCollapsed } from '../src/components/chat/ChatHeader'

function renderHeader(collapsed = false) {
  const onToggle = jest.fn()
  const onNewChat = jest.fn()
  const utils = render(
    <ChatHeader
      botName='黄金策'
      subtitle='商家经营助手'
      collapsed={collapsed}
      onToggle={onToggle}
      onNewChat={onNewChat}
    />,
  )
  return { ...utils, onToggle, onNewChat }
}

describe('ChatHeader — 顶部品牌层折叠（issue #7265）', () => {
  it('默认展开：身份 + 副标题 + 新对话都在，且没有收起态 class', () => {
    const { container } = renderHeader()
    expect(screen.getByText('黄金策')).toBeInTheDocument()
    expect(screen.getByText('商家经营助手')).toBeInTheDocument()
    expect(screen.getByText(/新对话/)).toBeInTheDocument()
    expect(container.querySelector('.chat-page__navbar--collapsed')).toBeNull()
  })

  it('收起态：class 在位，折叠键变为「展开顶部品牌栏」', () => {
    const { container } = renderHeader(true)
    expect(container.querySelector('.chat-page__navbar--collapsed')).toBeInTheDocument()
    expect(screen.getByLabelText('展开顶部品牌栏')).toBeInTheDocument()
  })

  it('点折叠键 ⇒ onToggle 被调用（手动可折叠）', () => {
    const { onToggle } = renderHeader()
    fireEvent.click(screen.getByLabelText('收起顶部品牌栏'))
    expect(onToggle).toHaveBeenCalledTimes(1)
  })

  it('滚动滞回：>24 收起；<8 展开；中间维持原状', () => {
    expect(nextHeaderCollapsed(false, 25)).toBe(true)
    expect(nextHeaderCollapsed(true, 7)).toBe(false)
    expect(nextHeaderCollapsed(true, 12)).toBe(true)
    expect(nextHeaderCollapsed(false, 12)).toBe(false)
  })
})
