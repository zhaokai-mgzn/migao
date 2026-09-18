import { View, Text, ScrollView } from '@tarojs/components'
import './RecommendChips.scss'

interface RecommendChipsProps {
  /** 点胶囊：以对话形式发起推荐/查询（与快捷入口同语义） */
  onPick: (prompt: string) => void
}

/**
 * 主页顶部横滑推荐胶囊（瑞幸 Agent 主页同款语言形态：图标 + 短句钩子）。
 *
 * **文案方向 = 能力钩子 + 场景痛点**（2026-09-18 用户裁定，issue #4236）：
 * 顾客点胶囊的动机是「这事跟我有关 / 它能帮我省事」，所以每条**指向一个不同的能力**，
 * 不重复堆「推荐商品」——旧版 5 条里有 3 条都落在商品推荐上，信息量被浪费。
 *
 * | 钩子 | 指向的能力 | 为什么吸引 |
 * |---|---|---|
 * | 报个尺寸，我算你要几米布 | `curtain_calc` 算料报价 | 小布**独有**能力（别家客服给不了），且替顾客省掉「买几米」这道最难的算术 |
 * | 客厅西晒？先看遮光率 | 知识问答 | 用**具体场景**（西晒）唤起「我家也这样」 |
 * | 卧室要暗，这几款遮光好 | 商品推荐 | 场景 → 货，给一个可直接挑的短名单 |
 * | 预算有限？我帮你搭最省的 | 商品推荐（性价比） | 价格敏感是真实顾虑，先给「省钱」承诺 |
 * | 货到哪了，一问便知 | `customer_logistics_track` | 老客户高频诉求，免去翻订单页 |
 *
 * **刻意不接商品接口**：与本仓既定裁定一致（#3978 / #4199）——
 * 空态不铺商品图/名，推荐只在对话里发生；胶囊是静态策划文案（用户 2026-09-18 复选「保持静态」，
 * 不放真实价格/热卖数据），点一下即发送对应 prompt。改文案 = 改这一处常量。
 */
const RECOMMEND_CHIPS = [
  { icon: '📐', text: '报个尺寸，我算你要几米布', prompt: '帮我算一下窗帘用料和价格' },
  { icon: '🌞', text: '客厅西晒？先看遮光率', prompt: '遮光率怎么选？客厅西晒适合哪种窗帘' },
  { icon: '🛏️', text: '卧室要暗，这几款遮光好', prompt: '推荐几款卧室用的遮光窗帘' },
  { icon: '💰', text: '预算有限？我帮你搭最省的', prompt: '预算有限，帮我推荐性价比高的窗帘' },
  { icon: '🚚', text: '货到哪了，一问便知', prompt: '帮我查一下物流' },
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
