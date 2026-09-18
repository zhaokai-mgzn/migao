import { View, Text, ScrollView } from '@tarojs/components'
import './RecommendChips.scss'

interface RecommendChipsProps {
  /** 点胶囊：以对话形式发起推荐/查询（与快捷入口同语义） */
  onPick: (prompt: string) => void
}

/**
 * 主页顶部横滑推荐胶囊（瑞幸 Agent 主页同款语言形态：图标 + 短句卖点）。
 *
 * **刻意不接商品接口**：与本仓既定裁定一致（#3978 / issue #4199）——
 * 空态不铺商品图/名，推荐只在对话里发生；胶囊是静态策划文案，
 * 点一下即发送对应 prompt。改文案 = 改这一处常量。
 */
const RECOMMEND_CHIPS = [
  { icon: '🪟', text: '遮光窗帘，一拉就黑', prompt: '推荐一下遮光窗帘' },
  { icon: '🧮', text: '算料报价，一分钟出', prompt: '帮我算一下窗帘用料和价格' },
  { icon: '🔥', text: '热门花色，大家都在买', prompt: '推荐一下热门商品' },
  { icon: '🚚', text: '货到哪了，一查便知', prompt: '帮我查一下物流' },
  { icon: '🧵', text: '想换窗帘，先挑布料', prompt: '推荐一下热门窗帘产品' },
]

export default function RecommendChips({ onPick }: RecommendChipsProps) {
  return (
    <View className='recommend-chips'>
      <ScrollView className='recommend-chips__scroll' scrollX enhanced showScrollbar={false}>
        <View className='recommend-chips__row'>
          {RECOMMEND_CHIPS.map((chip) => (
            <View
              key={chip.text}
              className='recommend-chips__chip'
              hoverClass='recommend-chips__chip--hover'
              onClick={() => onPick(chip.prompt)}
            >
              <Text className='recommend-chips__icon'>{chip.icon}</Text>
              <Text className='recommend-chips__text'>{chip.text}</Text>
            </View>
          ))}
        </View>
      </ScrollView>
    </View>
  )
}
