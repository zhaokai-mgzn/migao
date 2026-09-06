import { View, Text } from '@tarojs/components'
import './KnowledgeCard.scss'

interface KnowledgeCardProps {
  data: {
    title?: string
    summary?: string
    content?: string
    source?: string
    relevance_score?: number
    score?: number
    doc_type?: string
  }
}

export default function KnowledgeCard({ data }: KnowledgeCardProps) {
  const title = data.title || '知识库结果'
  const summary = data.summary || data.content || ''
  const source = data.source || data.doc_type || ''
  const score = data.relevance_score ?? data.score
  const scoreText = score !== undefined && score !== null
    ? `${Math.round(score * 100)}%`
    : ''

  return (
    <View className='knowledge-card'>
      <View className='knowledge-card__header'>
        <Text className='knowledge-card__header-icon'>📖</Text>
        <Text className='knowledge-card__header-title'>知识库结果</Text>
      </View>

      <View className='knowledge-card__body'>
        {title && (
          <Text className='knowledge-card__title'>{title}</Text>
        )}
        {summary && (
          <Text className='knowledge-card__summary'>{summary}</Text>
        )}
      </View>

      {(source || scoreText) && (
        <View className='knowledge-card__footer'>
          {source && (
            <Text className='knowledge-card__source'>来源: {source}</Text>
          )}
          {scoreText && (
            <Text className='knowledge-card__score'>相关度: {scoreText}</Text>
          )}
        </View>
      )}
    </View>
  )
}
