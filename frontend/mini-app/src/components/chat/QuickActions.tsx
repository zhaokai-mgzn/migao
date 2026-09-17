import { View, Text } from '@tarojs/components'
import './QuickActions.scss'

interface QuickActionsProps {
  onAction: (prompt: string) => void
}

/** 默认快捷操作：六格等权快捷对话（UI-010/UI-014/UI-044），点任一入口即发送 prompt 触发对话 */
const DEFAULT_ACTIONS = [
  { icon: '🧮', label: '算料报价', prompt: '帮我算一下窗帘用料和价格' },
  { icon: '🔥', label: '推荐热门商品', prompt: '推荐一下热门商品' },
  { icon: '📦', label: '查订单', prompt: '帮我查一下最近的订单' },
  { icon: '🔍', label: '找产品', prompt: '推荐一下热门窗帘产品' },
  { icon: '🤝', label: '售后咨询', prompt: '我想咨询售后问题' },
  { icon: '🚚', label: '查物流', prompt: '帮我查一下物流' },
]

export default function QuickActions({ onAction }: QuickActionsProps) {
  return (
    <View className='quick-actions'>
      <Text className='quick-actions__title'>您可以试试以下问题</Text>
      <View className='quick-actions__grid'>
        {DEFAULT_ACTIONS.map((action) => (
          <View
            key={action.label}
            className='quick-actions__item'
            onClick={() => onAction(action.prompt)}
          >
            <Text className='quick-actions__icon'>{action.icon}</Text>
            <Text className='quick-actions__label'>{action.label}</Text>
          </View>
        ))}
      </View>
    </View>
  )
}
