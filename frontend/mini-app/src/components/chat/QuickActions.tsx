import { View, Text } from '@tarojs/components'
import './QuickActions.scss'

interface QuickActionsProps {
  onAction: (prompt: string) => void
}

/** 默认快捷操作：算料报价为全宽主入口（POC 算料闭环直达，UI-014），其余 4 项 2×2 */
const DEFAULT_ACTIONS = [
  { icon: '🧮', label: '算料报价', prompt: '帮我算一下窗帘用料和价格', wide: true },
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
            className={`quick-actions__item${action.wide ? ' quick-actions__item--wide' : ''}`}
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
