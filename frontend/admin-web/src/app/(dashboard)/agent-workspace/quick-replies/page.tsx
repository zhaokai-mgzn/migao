'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'

/**
 * 快捷回复 — 历史占位页（2026-08 前为「开发中」预告页）。
 *
 * 真实功能已实现在「机器人设置 /chat/config」的「快捷回复」tab
 * （quickReplyApi 全 CRUD + 后端 /api/admin/quick-replies），本页为
 * 冗余入口，重定向到唯一真实入口，避免功能双处、占位误导（RBAC 页面验收 P1-B）。
 */
export default function QuickRepliesRedirect() {
  const router = useRouter()
  useEffect(() => {
    router.replace('/chat/config?tab=quick-replies')
  }, [router])
  return null
}
