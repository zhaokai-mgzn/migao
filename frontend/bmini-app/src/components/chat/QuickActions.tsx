import { View, Text } from '@tarojs/components'
import './QuickActions.scss'

interface QuickActionsProps {
  onAction: (prompt: string) => void
}

/**
 * 默认快捷操作：**六格等权**（2 列 × 3 行），点任一格即发送 prompt 触发对话。
 *
 * issue #5747：B 端此前是 C 端**旧版**形态（「算料报价」全宽主入口 + 2×2 共 5 格，
 * `quick-actions__item--wide`）。C 端早已按用户裁定回退为六格等权
 * （`.github/cases/ui.yml` 的 UI-014 / UI-044；#3979 六格化 → #4236「上个 2 列 × 3 行更好看」），
 * 本组件与 `QuickActions.scss` 一并对齐 ⇒ `--wide` 样式同批删除（防半回退 / 死代码）。
 *
 * 第 6 格 = **查库存**：B 端专属能力（`batch_stock_query` / `stock_ledger_query` 挂
 * `product:list` 权限码，C 端 JWT 无权限码 ⇒ 不在 C 端面，见
 * `backend/ai-agent-service/app/graph/skills/product_skill.py`）。C 端第 6 格是
 * 「推荐热门商品」（顾客视角），不适用于商家端，故**不是**逐字照抄 C 端六条。
 */
const DEFAULT_ACTIONS = [
  { icon: '🧮', label: '算料报价', prompt: '帮我算一下窗帘用料和价格' },
  { icon: '📦', label: '查订单', prompt: '帮我查一下最近的订单' },
  { icon: '📊', label: '查库存', prompt: '帮我查一下库存' },
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
