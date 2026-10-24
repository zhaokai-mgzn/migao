import { View, Text } from '@tarojs/components'

/**
 * 手机端「问黄金策」顶部品牌渐变层（issue #7265）
 *
 * 用户逐字：「黄金策上面的顶层渐变层那块区域，应该允许向上折叠，增大对话文字显示空间」。
 * 收起态 = 保留 logo + 名称 + 折叠键的细品牌条；展开态 = 原样（副标题 + 新对话）。
 * 滚动联动由页面把 `onScrollOffset` 接到 `nextHeaderCollapsed`（带滞回）。
 */

/** 向下滚过 24px ⇒ 收起；回到 8px 以内 ⇒ 展开（滞回区避免贴边抖动） */
export const HEADER_COLLAPSE_AT = 24
export const HEADER_EXPAND_AT = 8

/** 纯函数：当前状态 + 滚动位置 ⇒ 下一个折叠态（判据见 tests/chat-header-collapse.test.tsx） */
export function nextHeaderCollapsed(current: boolean, scrollTop: number): boolean {
  if (scrollTop > HEADER_COLLAPSE_AT) return true
  if (scrollTop < HEADER_EXPAND_AT) return false
  return current
}

interface ChatHeaderProps {
  botName: string
  subtitle: string
  collapsed: boolean
  onToggle: () => void
  onNewChat: () => void
}

export default function ChatHeader({ botName, subtitle, collapsed, onToggle, onNewChat }: ChatHeaderProps) {
  return (
    <View className={`chat-page__navbar${collapsed ? ' chat-page__navbar--collapsed' : ''}`}>
      <View className='chat-page__navbar-title'>
        <View className='chat-page__navbar-logo' />
        <Text className='chat-page__navbar-name'>{botName}</Text>
        <View className='chat-page__navbar-badge'>
          <Text className='chat-page__navbar-badge-text'>AI</Text>
        </View>
        <View
          className='chat-page__navbar-toggle'
          aria-label={collapsed ? '展开顶部品牌栏' : '收起顶部品牌栏'}
          onClick={onToggle}
        >
          <Text className='chat-page__navbar-toggle-icon'>{collapsed ? '⌄' : '⌃'}</Text>
        </View>
      </View>
      <View className='chat-page__navbar-right'>
        <Text className='chat-page__navbar-sub'>{subtitle}</Text>
        {/* 新对话（清空工作状态，不展示会话列表） */}
        <View className='chat-page__new-chat' onClick={onNewChat} hoverClass='chat-page__new-chat--hover'>
          <Text className='chat-page__new-chat-text'>🔄 新对话</Text>
        </View>
      </View>
    </View>
  )
}
