import { useEffect, useMemo, useCallback, useRef } from 'react'
import { View, Text, Image, ScrollView } from '@tarojs/components'
import Taro from '@tarojs/taro'
import type { Message, CardData, InteractiveData } from '../../types'
import {
  parseRichContent,
  type RichSegment,
  type RichTable,
  type TableAlign,
} from '../../utils/richText'
// 时间口径单一真值（issue #6666 判据 8）：本文件原有私有 formatTime 已并入共享实现
import { formatMessageTime } from '../../utils/datetime'
// 客户端打字机（issue #7235；与 PC #5952 / #7086 同口径）
import { useTypewriter } from '../../hooks/use-typewriter'
import ProductCard from '../cards/ProductCard'
import ProductFormList from '../cards/ProductFormList'
import LogisticsCard from '../cards/LogisticsCard'
import OrderCard from '../cards/OrderCard'
import QuotationCard from '../cards/QuotationCard'
import ProductionProgressCard from '../cards/ProductionProgressCard'
import BatchStockCard from '../cards/BatchStockCard'
import PosterCard from '../cards/PosterCard'
import ConfirmCard from '../cards/ConfirmCard'
import ChoiceCard from '../cards/ChoiceCard'
import FormCard from '../cards/FormCard'
import './MessageBubble.scss'

interface MessageBubbleProps {
  message: Message
  /** 交互回调：点击确认/取消/追问/下单按钮时，发送对应文本作为用户消息 */
  onInteract?: (value: string) => void
  /** 打字机逐字揭示追加了内容（issue #7263）：父级据此贴底跟随滚动 */
  onContentGrow?: () => void
}

/** 渲染单张卡片 */
function renderCard(card: CardData, idx: number, onInteract?: (value: string) => void) {
  const { type, data } = card

  switch (type) {
    case 'product_list': {
      // data 可能是单个商品或商品列表（后端 `_detect_card_type` 只下发 product_list；
      // 旧别名 `product_recommend` 于 #4016 P14 裁剪 —— 后端从无该卡型的发射点）
      const products = Array.isArray(data?.products) ? data.products : (Array.isArray(data) ? data : [data])
      // 多商品 → 瑞幸式商品表单列表（紧凑行 + 可点规格 + 查看；issue #7264 商家端不下单）
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
              onView={onInteract ? (name) => onInteract(`查看${name}`) : undefined}
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
          onView={onInteract ? (name) => onInteract(`查看${name}`) : undefined}
        />
      )
    }

    case 'logistics': {
      const logistics = data?.logistics || data
      return <LogisticsCard key={`card-${idx}`} data={logistics} />
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

    case 'production_progress': {
      // 生产进度卡（#4016 P14，用户 2026-09-18 裁定补发射点；与 C 端同族组件）
      return <ProductionProgressCard key={`card-${idx}`} data={data} />
    }

    case 'batch_stock': {
      // 批次账 / 省料度量卡（issue #5188）。该工具只绑黄金策 Skill（`product:list` 门禁 ⇒
      // C 端恒不可达）⇒ 按 persona 推导只需 B 端两端渲染（本端 + admin-web 桌面）。
      return <BatchStockCard key={`card-${idx}`} data={data} />
    }

    case 'marketing_poster': {
      // 营销海报卡（issue #7351）：商品事实 + 商家确认的文案 → 750×1000 PNG。
      // 只绑黄金策（`product:list`）⇒ C 端不可达，B 端两端都要能渲染
      // （判据 = backend/ai-agent-service/tests/test_card_type_cross_end_contract.py）。
      return <PosterCard key={`card-${idx}`} data={data} />
    }

    default:
      // 未知卡片类型：对客户隐藏内部 type（issue #2857），展示通用占位
      return (
        <View key={`card-${idx}`} className='message-bubble__card-placeholder'>
          <Text className='message-bubble__card-text'>📎 消息内容暂不支持预览</Text>
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

/** 渲染交互式组件（confirm/choice/form）—— disabled（已答复/历史回放）时只读锁卡（issue #3038 CH-030） */
function renderInteractive(
  interactive: InteractiveData,
  onInteract?: (value: string) => void,
  disabled?: boolean,
) {
  switch (interactive.type) {
    case 'confirm':
      return (
        <ConfirmCard
          data={interactive}
          onAction={(value) => onInteract?.(value)}
          disabled={disabled}
        />
      )
    case 'choice':
      return (
        <ChoiceCard
          data={interactive}
          onAction={(value) => onInteract?.(value)}
          disabled={disabled}
        />
      )
    case 'form':
      return (
        <FormCard
          data={interactive}
          onAction={(value) => onInteract?.(value)}
          disabled={disabled}
        />
      )
    default:
      return null
  }
}

/**
 * 揭示过程中**不要闪半张表**（issue #7235）。
 *
 * 打字机逐字揭示时，表格会先露出「表头一行」再露出分隔行 —— 这一两百毫秒里，解析器只能把它
 * 当普通文本 ⇒ 用户先看到一排裸 `|` 再变成表格（正是用户报的形态，只是短暂版）。
 * ⇒ 揭示期间，**末尾连续以 `|` 开头、且还成不了表**的那几行先不画；分隔行一到，表格直接出现。
 *
 * 只在**揭示期间**调用（完整文本 / 历史回放不受影响），且只处理**尾部**（揭示是前缀增长）。
 */
function holdIncompleteTableTail(text: string): string {
  const lines = text.split('\n')
  let i = lines.length - 1
  while (i >= 0 && lines[i].trimStart().startsWith('|')) i -= 1
  const tailStart = i + 1
  if (tailStart >= lines.length) return text
  const tail = lines.slice(tailStart)
  // 尾巴已经成表（表头 + 分隔行齐全）⇒ 原样返回，让表格直接出现
  const complete = parseRichContent(tail.join('\n')).some((block) => block.kind === 'table')
  return complete ? text : lines.slice(0, tailStart).join('\n')
}

/** 行内片段渲染（普通段落与表格单元格共用；表格单元格不要 `pre-wrap`） */
function renderSegments(segments: RichSegment[], textClass = 'message-bubble__text') {
  return segments.map((seg, si) =>
    seg.bold ? (
      <Text key={si} className={`${textClass} message-bubble__text-strong`}>
        {seg.text}
      </Text>
    ) : (
      <Text key={si} className={textClass}>
        {seg.text}
      </Text>
    ),
  )
}

/**
 * GFM 表格渲染（issue #7235）。
 *
 * - 横向滚动：手机屏幕放不下 3~6 列 ⇒ `scrollX` 容器 + 单元格最小宽度，宁滑不挤；
 * - 单元格内沿用行内粗体（表格不吞富文本），但不继承 `pre-wrap`（会撑出奇怪空格）。
 */
function RichTableBlock({ table }: { table: RichTable }) {
  const cellStyle = (align: TableAlign) => (align ? { textAlign: align } : undefined)
  return (
    <ScrollView className='message-bubble__table-scroll' scrollX>
      <View className='message-bubble__table'>
        <View className='message-bubble__table-row message-bubble__table-row--header'>
          {table.header.map((cell, ci) => (
            <View
              key={ci}
              className='message-bubble__table-cell message-bubble__table-cell--header'
              style={cellStyle(table.align[ci])}
            >
              {renderSegments(cell, 'message-bubble__table-text')}
            </View>
          ))}
        </View>
        {table.rows.map((row, ri) => (
          <View key={ri} className='message-bubble__table-row'>
            {row.map((cell, ci) => (
              <View
                key={ci}
                className='message-bubble__table-cell'
                style={cellStyle(table.align[ci])}
              >
                {renderSegments(cell, 'message-bubble__table-text')}
              </View>
            ))}
          </View>
        ))}
      </View>
    </ScrollView>
  )
}

export default function MessageBubble({ message, onInteract, onContentGrow }: MessageBubbleProps) {
  const {
    role, content, isStreaming, cards, cardData,
    type, created_at, images, interactive,
    interactiveAnswered,
  } = message

  const timeStr = useMemo(() => formatMessageTime(created_at), [created_at])

  // 兜底剥离 LLM 幻觉伪代码块（issue #3038 / CH-032）：后端已实时剥离，
  // 此处兜底历史残留 —— <interact>…</interact> XML 与 ```tool_call 代码块
  const cleanContent = useMemo(
    () => (content || '')
      .replace(/<interact>[\s\S]*?<\/interact>/g, '')
      .replace(/```tool_call[\s\S]*?```/g, ''),
    [content],
  )

  // issue #7235：客户端打字机（与 PC #5952 / #7086 同口径）。后端仍整段下发（节点级 astream +
  // finalize_turn 收口 + C 端跨片脱敏 ⇒ 服务端不做真逐字），揭示只发生在客户端；
  // **揭示不绑流式生命周期**：挂载即完整（历史回放/重挂载）⇒ 首帧全文；用户中断 ⇒ 立刻全文；
  // 正文整段到达 + 紧随 done ⇒ 继续把尾巴打完（旧口径「流结束就立刻全文」会让揭示窗口 ≈ 0）。
  const visibleContent = useTypewriter(cleanContent, { instant: !!message.wasAborted })
  const revealing = !!isStreaming || visibleContent.length < cleanContent.length

  // issue #7263：逐字揭示每追加一帧就通知父级「内容长高了」，由父级决定是否贴底跟随
  //（用 ref 转发回调：父级每次渲染换新函数不该把揭示节奏重置成每个字符一次）
  const onContentGrowRef = useRef(onContentGrow)
  onContentGrowRef.current = onContentGrow
  useEffect(() => {
    if (visibleContent.length > 0) onContentGrowRef.current?.()
  }, [visibleContent.length])

  // issue #6346 / #7235：富文本按**块**解析（**粗体** / - 列表 / GFM 表格），流式安全
  // （未闭合 ** 与「分隔行还没到的表格」都原样保留，不闪出解析产物）。
  const blocks = useMemo(
    () => parseRichContent(revealing ? holdIncompleteTableTail(visibleContent) : visibleContent),
    [revealing, visibleContent],
  )
  // 气泡宽度按**全文**判定（不是按已揭示的块）：否则揭示到表格那一行时气泡会 78% → 94% 跳一下
  const hasTable = useMemo(
    () => parseRichContent(cleanContent).some((block) => block.kind === 'table'),
    [cleanContent],
  )
  // 揭示进度（可见字符数）：给判据读「t 时刻可见 < 全长」（tests/chat-typewriter.test.tsx）
  const revealAttrs = { 'data-revealed': String(visibleContent.length) }

  const handlePreviewImage = useCallback((current: string) => {
    if (images?.length) {
      Taro.previewImage({ current, urls: images })
    }
  }, [images])

  const bubbleClass = `message-bubble message-bubble--${role}`

  return (
    <View className={bubbleClass}>
      {/* 有表格的气泡放宽到 94%（78% 下 3 列必然挤成一列）；纯文本气泡维持原宽 */}
      <View className={`message-bubble__wrapper${hasTable ? ' message-bubble__wrapper--wide' : ''}`}>
        {/* GB-02（GB/T 47746-2026, issue #2780）：消息来源标识——AI 助手 / 人工客服
            AI 标识仅在文本回复上显示（纯卡片/纯工具消息不显示，避免干扰卡片语义）；
            人工客服消息显式打标（转人工后由 chatStore 轮询映射写入 source='human'） */}
        {(() => {
          const isHuman = message.source === 'human'
          return role === 'assistant' && (isHuman || !!content) ? (
            <View className='message-bubble__source'>
              <Text
                className={
                  isHuman
                    ? 'message-bubble__source-text message-bubble__source-text--human'
                    : 'message-bubble__source-text'
                }
              >
                {isHuman ? '👩‍💼 人工客服' : '🤖 AI 助手'}
              </Text>
            </View>
          ) : null
        })()}

        {/* 文本内容（纯图消息 content 为空时不渲染空文本区；tool_call 有 content 时也显示） */}
        {content && (
          <View className='message-bubble__content' {...revealAttrs}>
            {blocks.map((block, bi) =>
              block.kind === 'table' ? (
                <RichTableBlock key={`table-${bi}`} table={block.table} />
              ) : (
                block.lines.map((line, li) => (
                  <View
                    key={`line-${bi}-${li}`}
                    className={`message-bubble__line${line.bullet ? ' message-bubble__line--bullet' : ''}${line.segments.length === 1 && line.segments[0].text === '' ? ' message-bubble__line--empty' : ''}`}
                  >
                    {renderSegments(line.segments)}
                  </View>
                ))
              ),
            )}
            {revealing && <Text className='message-bubble__cursor'>|</Text>}
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

        {/* 工具调用过程对客户隐藏（issue #2857）：不渲染 tool_calls / toolCall 指示器，
            仅保留数据在消息对象中（供转人工等逻辑判定） */}

        {/* 卡片区域 - 数组形式 */}
        {cards && cards.length > 0 && renderCards(cards, onInteract)}

        {/* 卡片区域 - 单个 cardData（兼容） */}
        {!cards?.length && cardData && renderSingleCard(cardData, onInteract)}

        {/* 交互式组件（confirm 等）—— 流式进行中不渲染（防闪烁/防误点，CH-032）；
            已答复（interactiveAnswered/历史回放）→ 只读锁卡（CH-030） */}
        {interactive && !isStreaming && renderInteractive(
          interactive,
          onInteract,
          interactiveAnswered,
        )}

        {/* 时间戳 */}
        {timeStr && <Text className='message-bubble__time'>{timeStr}</Text>}
      </View>
    </View>
  )
}
