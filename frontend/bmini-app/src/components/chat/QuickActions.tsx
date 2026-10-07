import { View, Text } from '@tarojs/components'
import type { QuickAction } from '../../types'
import './QuickActions.scss'

interface QuickActionsProps {
  /** 服务端下发的快捷入口（**内容唯一真值** —— 本组件不定义任何入口文案） */
  actions: QuickAction[]
  onAction: (prompt: string) => void
}

/**
 * B 端「问米宝」空态快捷入口：**六格等权**（2 列 × 3 行），点任一格即发送 prompt 触发对话。
 *
 * 🔴 内容**不在这里定义**（issue #6468）：单一真值 = 服务端
 * `GET /api/chat/quick-actions`（`backend/ai-agent-service/app/api/chat.py` 的 `QUICK_ACTIONS`）。
 * 本组件只负责渲染，admin-web 消费同一份。
 *
 * 为什么改成这样：此前这里**硬编码**六条，而且是 C 端顾客口吻
 * （「推荐一下热门窗帘产品」「帮我查一下物流」「我想咨询售后问题」）—— B 端 H5 抄了 C 端主页；
 * 而服务端那份 B 端清单（更早的形态是「订单管理 / 商品管理 / 经营看板…」模块名）**从没被消费**
 * （`frontend/bmini-app/src/store/chatStore.ts` 的 `loadQuickActions` 是死代码）。
 * ⇒ 同一个 B 端产品两套各自维护的入口，抄的那套必然漂移。
 *
 * 布局沿革（勿按中间态改回来）：#5747 与 C 端现行形态对齐（`--wide` 全宽主入口已删、无分组结构），
 * 这条**视觉**判据不变；本单只换**内容**与**来源**。
 */
export default function QuickActions({ actions, onAction }: QuickActionsProps) {
  // 内容拿不到（接口失败 / 尚未加载）⇒ **不渲染**，而不是退回到一份本地兜底清单
  // —— 兜底清单就是 #6468 的病灶本身（又抄一份，且无人知道它过期了）。
  if (actions.length === 0) return null

  return (
    <View className='quick-actions'>
      <Text className='quick-actions__title'>您可以试试以下问题</Text>
      <View className='quick-actions__grid'>
        {actions.map((action) => (
          <View
            key={action.id}
            className='quick-actions__item'
            onClick={() => onAction(action.prompt)}
          >
            <Text className='quick-actions__icon'>{action.emoji}</Text>
            <Text className='quick-actions__label'>{action.name}</Text>
          </View>
        ))}
      </View>
    </View>
  )
}
