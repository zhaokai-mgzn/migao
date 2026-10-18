'use client'

/**
 * 企业名称读取口（issue #7219）—— 纸面单据表头用（加工单 / 报价单 / 销售单 / 发货单）。
 *
 * ## 为什么是一个 hook 而不是各单据各读一次
 *
 * 四张纸面常常**同页并存**（订单详情页一次挂四份，打印时按 `data-print-target` 只上纸一份）。
 * 各写一份 `settingsApi.getSettings()` ⇒ 一次渲染发 4 个请求，且四处的「读失败怎么显示」
 * 会各长一套。这里模块级缓存 Promise ⇒ **一次读、四处共用**。
 *
 * ## 口径
 *
 * - 成功 ⇒ `companyName`（trim 后）；缺值 / 读失败 ⇒ 空串 ⇒ 调用方**整行不渲染**
 *   （不印空行、不印「未设置」——纸面是给客户看的）；
 * - **登录态优先**：`/api/auth/me` 的 `user.tenantName` 已随登录下发（右上角/侧边栏用的同一份）
 *   ⇒ 普通员工（无 `system:manage`）也能印企业名；
 * - 登录态没有（如测试替身 / 旧会话）才回落 `GET /api/admin/settings`；该端点需 `system:manage`，
 *   失败 ⇒ 空串 ⇒ 不印空行（属预期，不弹 toast、不写 console）。
 */
import { useEffect, useState } from 'react'
import { settingsApi } from '@/lib/api'
import { useAuthStore } from '@/store/auth'

let cached: Promise<string> | null = null

function fetchCompanyName(): Promise<string> {
  if (!cached) {
    cached = (async () => {
      try {
        const res = await settingsApi.getSettings()
        const name = res?.data?.data?.companyName
        return typeof name === 'string' ? name.trim() : ''
      } catch {
        return ''
      }
    })()
  }
  return cached
}

export function useCompanyName(): string {
  const fromLogin = useAuthStore((state) => state.user?.tenantName?.trim() ?? '')
  const [name, setName] = useState('')
  useEffect(() => {
    let alive = true
    void fetchCompanyName().then((value) => {
      if (alive) setName(value)
    })
    return () => {
      alive = false
    }
  }, [])
  return fromLogin || name
}
