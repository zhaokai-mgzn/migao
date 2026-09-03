'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'

/**
 * 客服工作台首页 — 历史占位页。
 *
 * 工作台的真实子页为「人工客服 /agent-workspace/human-sessions」
 * （已在侧边栏「智能客服 → 人工客服」），本首页重定向避免「开发中」占位
 * （RBAC 页面验收 P1-B）。
 */
export default function AgentWorkspaceRedirect() {
  const router = useRouter()
  useEffect(() => {
    router.replace('/agent-workspace/human-sessions')
  }, [router])
  return null
}
