import { useMemo, useCallback } from 'react'
import { View, Text, Image } from '@tarojs/components'
import Taro from '@tarojs/taro'
import type { Message, ToolCallData, CardData, InteractiveData } from '../../types'
import ProductCard from '../cards/ProductCard'
import ProductFormList from '../cards/ProductFormList'
import LogisticsCard from '../cards/LogisticsCard'
import KnowledgeCard from '../cards/KnowledgeCard'
import OrderCard from '../cards/OrderCard'
import QuotationCard from '../cards/QuotationCard'
import ConfirmCard from '../cards/ConfirmCard'
import ChoiceCard from '../cards/ChoiceCard'
import FormCard from '../cards/FormCard'
import ToolCallIndicator from '../cards/ToolCallIndicator'
import SuggestionChips from './SuggestionChips'
import './MessageBubble.scss'

interface MessageBubbleProps {
  message: Message
  /** 交互回调：点击确认/取消/追问/下单按钮时，发送对应文本作为用户消息 */
  onInteract?: (value: string) => void
}

/** 格式化时间 */
function formatTime(dateStr: string): string {
  const date = new Date(dateStr)
  if (Number.isNaN(date.getTime())) return ''

  const now = new Date()
  const isToday =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate()

  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')

  if (isToday) {
    return `${hours}:${minutes}`
  }

  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${month}-${day} ${hours}:${minutes}`
}

/** 渲染工具调用指示器 */
function renderToolCalls(toolCalls: ToolCallData[]) {
  return (
    <View className='message-bubble__tool-calls'>
      {toolCalls.map((tc, idx) => (
        <ToolCallIndicator
          key={`tool-${idx}`}
          toolName={tc.tool}
          status={tc.status}
        />
      ))}
    </View>
  )
}

/** 渲染单张卡片 */
function renderCard(card: CardData, idx: number, onInteract?: (value: string) => void) {
  const { type, data } = card

  switch (type) {
    case 'product_list':
    case 'product_recommend': {
      // data 可能是单个商品或商品列表
      const products = Array.isArray(data?.products) ? data.products : (Array.isArray(data) ? data : [data])
      // 多商品 → 瑞幸式商品表单列表（紧凑行 + 可点规格 + 去下单）
      if (products.length > 1) {
        return (
          <ProductFormList
            key={`card-${idx}`}
            products={products}
            onInteract={(value) => onInteract?.(value)}
          />
        )
      }
      return (
        <View key={`card-${idx}`} className='message-bubble__card-group'>
          {products.map((product: any, pIdx: number) => (
            <ProductCard
              key={`product-${pIdx}`}
              data={product}
              onOrder={onInteract ? (name) => onInteract(`我要下单${name}`) : undefined}
            />
          ))}
        </View>
      )
    }

    case 'product_detail': {
      const product = data?.product || data
      return (
        <ProductCard
          key={`card-${idx}`}
          data={product}
          onOrder={onInteract ? (name) => onInteract(`我要下单${name}`) : undefined}
        />
      )
    }

    case 'logistics':
    case 'logistics_track': {
      const logistics = data?.logistics || data
      return <LogisticsCard key={`card-${idx}`} data={logistics} />
    }

    case 'knowledge_result':
    case 'knowledge': {
      // data 可能包含多条知识结果
      const chunks = data?.chunks || (Array.isArray(data) ? data : [data])
      return (
        <View key={`card-${idx}`} className='message-bubble__card-group'>
          {chunks.map((chunk: any, cIdx: number) => (
            <KnowledgeCard key={`knowledge-${cIdx}`} data={chunk} />
          ))}
        </View>
      )
    }

    case 'order': {
      // 订单卡片：归一化载荷 {"order": {...}} 单订单 / {"orders": [...]} 列表
      return <OrderCard key={`card-${idx}`} data={data} />
    }

    case 'quotation': {
      // 报价单卡片（curtain_calc 结果）
      return (
        <QuotationCard
          key={`card-${idx}`}
          data={data}
          onConfirm={onInteract ? () => onInteract('我要下单') : undefined}
        />
      )
    }

    default:
      // 未知卡片类型，显示占位
      return (
        <View key={`card-${idx}`} className='message-bubble__card-placeholder'>
          <Text className='message-bubble__card-text'>📎 {type}</Text>
        </View>
      )
  }
}

/** 渲染卡片列表 */
function renderCards(cards: CardData[], onInteract?: (value: string) => void) {
  return (
    <View className='message-bubble__cards'>
      {cards.map((card, idx) => renderCard(card, idx, onInteract))}
    </View>
  )
}

/** 渲染单个 cardData（message.cardData） */
function renderSingleCard(cardData: CardData, onInteract?: (value: string) => void) {
  return (
    <View className='message-bubble__cards'>
      {renderCard(cardData, 0, onInteract)}
    </View>
  )
}

/** 渲染交互式组件（confirm/choice/form） */
function renderInteractive(interactive: InteractiveData, onInteract?: (value: string) => void) {
  switch (interactive.type) {
    case 'confirm':
      return (
        <ConfirmCard
          data={interactive}
          onAction={(value) => onInteract?.(value)}
        />
      )
    case 'choice':
      return (
        <ChoiceCard
          data={interactive}
          onAction={(value) => onInteract?.(value)}
        />
      )
    case 'form':
      return (
        <FormCard
          data={interactive}
          onAction={(value) => onInteract?.(value)}
        />
      )
    default:
      return null
  }
}

export default function MessageBubble({ message, onInteract }: MessageBubbleProps) {
  const {
    role, content, isStreaming, tool_calls, toolCall, cards, cardData,
    type, created_at, images, interactive, suggestions,
  } = message

  const timeStr = useMemo(() => formatTime(created_at), [created_at])

  const handlePreviewImage = useCallback((current: string) => {
    if (images?.length) {
      Taro.previewImage({ current, urls: images })
    }
  }, [images])

  const bubbleClass = `message-bubble message-bubble--${role}`

  // 判断是否为 tool_call 类型消息（仅显示工具指示器）
  const isToolCallMessage = type === 'tool_call'

  return (
    <View className={bubbleClass}>
      <View className='message-bubble__wrapper'>
        {/* 文本内容（tool_call 类型消息如果没有 content 则跳过） */}
        {(!isToolCallMessage || content) && (
          <View className='message-bubble__content'>
            <Text className='message-bubble__text'>
              {content}
              {isStreaming && <Text className='message-bubble__cursor'>|</Text>}
            </Text>
          </View>
        )}

        {/* 图片区域 */}
        {images && images.length > 0 && (
          <View className='message-bubble__images'>
            {images.map((url, idx) => (
              <Image
                key={`img-${idx}`}
                className='message-bubble__image'
                src={url}
                mode='aspectFill'
                onClick={() => handlePreviewImage(url)}
              />
            ))}
          </View>
        )}

        {/* 工具调用指示器 - 数组形式 */}
        {tool_calls && tool_calls.length > 0 && renderToolCalls(tool_calls)}

        {/* 工具调用指示器 - 单个 toolCall（兼容） */}
        {!tool_calls?.length && toolCall && (
          <View className='message-bubble__tool-calls'>
            <ToolCallIndicator toolName={toolCall.tool} status={toolCall.status} />
          </View>
        )}

        {/* 卡片区域 - 数组形式 */}
        {cards && cards.length > 0 && renderCards(cards, onInteract)}

        {/* 卡片区域 - 单个 cardData（兼容） */}
        {!cards?.length && cardData && renderSingleCard(cardData, onInteract)}

        {/* 交互式组件（confirm 等） */}
        {interactive && renderInteractive(interactive, onInteract)}

        {/* 建议追问 chips */}
        {suggestions && suggestions.length > 0 && onInteract && (
          <SuggestionChips questions={suggestions} onAction={onInteract} />
        )}

        {/* 时间戳 */}
        {timeStr && <Text className='message-bubble__time'>{timeStr}</Text>}
      </View>
    </View>
  )
}
