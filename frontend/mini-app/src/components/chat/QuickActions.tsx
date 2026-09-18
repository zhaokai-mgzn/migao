import { View, Text } from '@tarojs/components'
import './QuickActions.scss'

interface QuickActionsProps {
  onAction: (prompt: string) => void
}

/**
 * 两栏分组快捷入口（瑞幸 Agent 主页「你可以这样对我说：」同款布局）。
 *
 * 六入口**全保留**（UI-010/UI-014/UI-044 的能力面不收缩），仅重排为两栏分组 +
 * 组头配色区分能力域；prompt 文案逐字沿用改版前真值（不回归）。
 */
const GROUPS = [
  {
    key: 'order',
    title: '下单小助手',
    tone: 'blue',
    actions: [
      { icon: '🧮', label: '算料报价', prompt: '帮我算一下窗帘用料和价格' },
      { icon: '🔍', label: '找产品', prompt: '推荐一下热门窗帘产品' },
      { icon: '📦', label: '查订单', prompt: '帮我查一下最近的订单' },
    ],
  },
  {
    key: 'recommend',
    title: '专属推荐师',
    tone: 'purple',
    actions: [
      { icon: '🔥', label: '推荐热门商品', prompt: '推荐一下热门商品' },
      { icon: '🤝', label: '售后咨询', prompt: '我想咨询售后问题' },
      { icon: '🚚', label: '查物流', prompt: '帮我查一下物流' },
    ],
  },
]

export default function QuickActions({ onAction }: QuickActionsProps) {
  return (
    <View className='quick-actions'>
      <Text className='quick-actions__title'>你可以这样对我说：</Text>
      <View className='quick-actions__columns'>
        {GROUPS.map((group) => (
          <View
            key={group.key}
            className={`quick-actions__group quick-actions__group--${group.tone}`}
          >
            <View className='quick-actions__group-head'>
              <Text className='quick-actions__group-title'>{group.title}</Text>
            </View>
            <View className='quick-actions__rows'>
              {group.actions.map((action) => (
                <View
                  key={action.label}
                  className='quick-actions__row'
                  hoverClass='quick-actions__row--hover'
                  onClick={() => onAction(action.prompt)}
                >
                  <Text className='quick-actions__row-icon'>{action.icon}</Text>
                  <Text className='quick-actions__row-label'>{action.label}</Text>
                  <Text className='quick-actions__row-arrow'>›</Text>
                </View>
              ))}
            </View>
          </View>
        ))}
      </View>
    </View>
  )
}
