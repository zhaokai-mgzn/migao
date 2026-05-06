import { View, Text } from '@tarojs/components'
import './QuickActions.scss'

interface QuickActionsProps {
  onAction: (prompt: string) => void
}

/** 默认快捷操作 */
const DEFAULT_ACTIONS = [
  { icon: '📦', label: '查订单', prompt: '帮我查一下最近的订单' },
  { icon: '🔍', label: '找产品', prompt: '推荐一下热门窗帘产品' },
  { icon: '🔄', label: '退换货', prompt: '我想申请退换货' },
  { icon: '👤', label: '转人工', prompt: '我想联系人工客服' },
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
