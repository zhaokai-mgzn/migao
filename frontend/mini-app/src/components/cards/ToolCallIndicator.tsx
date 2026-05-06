import { View, Text } from '@tarojs/components'
import './ToolCallIndicator.scss'

interface ToolCallIndicatorProps {
  toolName: string
  status: 'running' | 'completed' | 'error'
}

/** 工具名称 → 文案映射 */
const TOOL_CONFIG: Record<string, { running: string; completed: string; icon: string }> = {
  product_search: {
    icon: '🔍',
    running: '正在搜索商品...',
    completed: '商品搜索完成',
  },
  search_products: {
    icon: '🔍',
    running: '正在搜索商品...',
    completed: '商品搜索完成',
  },
  product_detail: {
    icon: '📋',
    running: '正在查询商品详情...',
    completed: '商品详情获取完成',
  },
  get_product_detail: {
    icon: '📋',
    running: '正在查询商品详情...',
    completed: '商品详情获取完成',
  },
  logistics_track: {
    icon: '📦',
    running: '正在查询物流...',
    completed: '物流查询完成',
  },
  get_logistics: {
    icon: '📦',
    running: '正在查询物流...',
    completed: '物流查询完成',
  },
  knowledge_search: {
    icon: '📖',
    running: '正在检索知识库...',
    completed: '知识库检索完成',
  },
  search_orders: {
    icon: '📦',
    running: '正在查询订单...',
    completed: '订单查询完成',
  },
  create_after_sale: {
    icon: '🔄',
    running: '正在创建售后单...',
    completed: '售后单创建完成',
  },
  transfer_human: {
    icon: '👤',
    running: '正在转接人工客服...',
    completed: '已转接人工客服',
  },
}

const DEFAULT_CONFIG = {
  icon: '⚙️',
  running: '正在处理...',
  completed: '处理完成',
}

export default function ToolCallIndicator({ toolName, status }: ToolCallIndicatorProps) {
  const config = TOOL_CONFIG[toolName] || DEFAULT_CONFIG
  const isRunning = status === 'running'
  const isError = status === 'error'

  const statusIcon = isError ? '❌' : isRunning ? config.icon : '✅'
  const statusText = isError
    ? `${config.completed.replace('完成', '')}失败`
    : isRunning
      ? config.running
      : config.completed

  return (
    <View className={`tool-indicator tool-indicator--${status}`}>
      <Text className='tool-indicator__icon'>{statusIcon}</Text>
      <Text className='tool-indicator__text'>{statusText}</Text>
      {isRunning && (
        <View className='tool-indicator__spinner' />
      )}
    </View>
  )
}
