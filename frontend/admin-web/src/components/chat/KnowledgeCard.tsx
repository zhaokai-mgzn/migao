'use client'

import { FileText, ExternalLink } from 'lucide-react'

interface KnowledgeCardProps {
  data: Record<string, unknown>
}

export default function KnowledgeCard({ data }: KnowledgeCardProps) {
  const results = (data.results as Array<Record<string, unknown>>) || []
  
  // Single result mode
  if (results.length === 0) {
    const title = (data.title as string) || ''
    const content = (data.content as string) || ''
    const source = (data.source as string) || ''
    const score = data.score as number | undefined

    if (!title && !content) return null

    return (
      <KnowledgeItem title={title} content={content} source={source} score={score} />
    )
  }

  return (
    <div className="space-y-2">
      {results.slice(0, 3).map((result, index) => (
        <KnowledgeItem
          key={index}
          title={(result.title as string) || `结果 ${index + 1}`}
          content={(result.content as string) || ''}
          source={((result.source as Record<string, unknown>)?.title as string) || (result.source as string) || ''}
          score={result.score as number | undefined}
        />
      ))}
    </div>
  )
}

function KnowledgeItem({
  title,
  content,
  source,
  score,
}: {
  title: string
  content: string
  source: string
  score?: number
}) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl overflow-hidden shadow-sm">
      <div className="px-3 py-2.5">
        <div className="flex items-start gap-2">
          <FileText className="w-4 h-4 text-emerald-500 flex-shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <h4 className="text-xs font-medium text-gray-800 truncate">
              {title}
            </h4>
            {content && (
              <p className="text-[11px] text-gray-500 mt-1 line-clamp-3 leading-relaxed">
                {content}
              </p>
            )}
            <div className="flex items-center gap-2 mt-1.5">
              {source && (
                <span className="text-[10px] text-gray-400 flex items-center gap-0.5">
                  <ExternalLink className="w-2.5 h-2.5" />
                  {source}
                </span>
              )}
              {score !== undefined && (
                <span className="text-[10px] text-emerald-500 font-medium">
                  匹配度 {(score * 100).toFixed(0)}%
                </span>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
