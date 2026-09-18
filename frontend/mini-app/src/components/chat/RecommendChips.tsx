import { View, Text } from '@tarojs/components'
import './RecommendChips.scss'

interface RecommendChipsProps {
  /** 点胶囊：以对话形式发起咨询/查询（与快捷入口同语义） */
  onPick: (prompt: string) => void
}

/**
 * 主页顶部推荐胶囊（**3 条 × 3 行，水平居中，与六格同宽对齐**）。
 *
 * 2026-09-18 用户裁定（issue #4236）分三轮收敛，别再按中间态改回去：
 *  ① 形态 = 胶囊（保留，不是商品卡）；
 *  ② 文案 = **专业服务句** —— 「不要太口语化，我们得专业」⇒ 去聊天语气，
 *     改用行业术语 + 服务项（用布量、遮光率等级、物流轨迹）；图标保留（视觉锚点）；
 *  ③ 布局 = **每条独占一行、水平居中**，与下方六格左右边界对齐（不做横滑 ——
 *     横滑必然左对齐 + 右端截断，与「居中」相斥；且 3 条也挤不进一行）。
 *
 * 「最多 3 条最有价值」的取舍：覆盖**买前（测算报价）→ 买中（遮光率选型依据）→
 * 买后（物流轨迹）**三段，各指向**不同能力**、不重复堆推荐商品。
 * 以后要加回第 4/5 条，只需改这一处常量（会自然变成 4/5 行）。
 *
 * **刻意不接商品接口**：与本仓既定裁定一致（#3978 / #4199）——
 * 空态不铺商品图/名，推荐只在对话里发生；胶囊是静态策划文案（用户复选「保持静态」，
 * 不放真实价格/热卖数据），点一下即发送对应 prompt。
 *
 * 注：`prompt`（点击后发送的那句话）**保持中性用户语气**，因为那模拟的是**顾客自己**会怎么说，
 * 不是服务方的话术 —— 两处刻意不同调。
 */
const RECOMMEND_CHIPS = [
  { icon: '📐', text: '按窗尺寸测算用布量与报价', prompt: '帮我算一下窗帘用料和价格' },
  { icon: '☀️', text: '遮光率等级与适用场景', prompt: '遮光率怎么选？客厅西晒适合哪种窗帘' },
  { icon: '🚚', text: '查询订单物流轨迹', prompt: '帮我查一下物流' },
]

export default function RecommendChips({ onPick }: RecommendChipsProps) {
  return (
    <View className='recommend-chips'>
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
  )
}
