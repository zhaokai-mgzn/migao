'use client'

import MessageList from './MessageList'
import MessageInput from './MessageInput'
import QuickActions from './QuickActions'

export default function ChatArea() {
  return (
    <div className="flex-1 flex flex-col min-w-0 bg-gray-50">
      <MessageList />
      <QuickActions />
      <MessageInput />
    </div>
  )
}
