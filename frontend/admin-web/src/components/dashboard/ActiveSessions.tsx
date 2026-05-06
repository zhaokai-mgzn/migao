'use client'

import Link from 'next/link'
import { ArrowRight, Bot, User } from 'lucide-react'
import Badge from '@/components/ui/Badge'
import type { ActiveSession } from '@/types'

interface ActiveSessionsProps {
  sessions: ActiveSession[]
  loading?: boolean
}

const channelLabels: Record<string, string> = {
  wechat_mini: '小程序',
  h5: 'H5',
  web: '网页',
  app: 'APP',
}

export default function ActiveSessions({ sessions, loading }: ActiveSessionsProps) {
  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-gray-900">
          活跃会话
          {sessions.length > 0 && (
            <span className="ml-2 text-xs font-normal text-gray-400">({sessions.length})</span>
          )}
        </h3>
        <Link
          href="/chat"
          className="flex items-center gap-1 text-xs text-primary-600 hover:text-primary-700 font-medium"
        >
          查看全部
          <ArrowRight className="w-3.5 h-3.5" />
        </Link>
      </div>

      {loading ? (
        <div className="h-40 flex items-center justify-center">
          <div className="animate-spin w-6 h-6 border-2 border-primary-500 border-t-transparent rounded-full" />
        </div>
      ) : sessions.length === 0 ? (
        <div className="h-40 flex items-center justify-center text-sm text-gray-400">
          暂无活跃会话
        </div>
      ) : (
        <div className="space-y-3">
          {sessions.map((session) => (
            <div
              key={session.id}
              className="flex items-center gap-3 p-3 rounded-lg border border-gray-100 hover:bg-gray-50/50 transition-colors"
            >
              <div className="flex-shrink-0">
                {session.isAI ? (
                  <div className="w-8 h-8 rounded-full bg-primary-50 flex items-center justify-center">
                    <Bot className="w-4 h-4 text-primary-600" />
                  </div>
                ) : (
                  <div className="w-8 h-8 rounded-full bg-orange-50 flex items-center justify-center">
                    <User className="w-4 h-4 text-orange-600" />
                  </div>
                )}
              </div>

              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-gray-900 truncate">
                    {session.customerName}
                  </span>
                  <Badge variant={session.isAI ? 'info' : 'warning'}>
                    {session.isAI ? 'AI' : '人工'}
                  </Badge>
                </div>
                <p className="text-xs text-gray-500 mt-0.5 truncate">{session.lastMessage}</p>
              </div>

              <div className="flex-shrink-0 text-right">
                <div className="text-xs text-gray-400">
                  {channelLabels[session.channel] || session.channel}
                </div>
                <div className="text-xs text-gray-400 mt-0.5">{session.duration}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
