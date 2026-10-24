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
 * - 🔴 **登录态有值 ⇒ 一次设置读面都不发**（issue #7285）：回落请求打的是
 *   `GET /api/admin/settings`，该端点要 `system:manage`；而四张纸面在**订单详情页是常驻挂载**的
 *   ⇒ 无该码的岗位（客服/销售/财务等）**一进详情页就吃一次 403**，屏上弹出
 *   「没有权限执行此操作」而页面数据照常渲染 —— 用户现场逐字「提示没有权限，但是页面又能看见」。
 *   `try/catch` 只能吞掉 Promise，吞不掉 `request.ts` 的 403 toast ⇒ 唯一干净的修法是**不发**；
 * - 登录态没有（如测试替身 / 旧会话 / `tenantName` 为空的历史会话）才回落设置读面；
 *   失败 ⇒ 空串 ⇒ 不印空行。
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

/** 测试专用：清空模块级缓存（生产代码不调用）。 */
export function __resetCompanyNameCache(): void {
  cached = null
}

export function useCompanyName(): string {
  const fromLogin = useAuthStore((state) => state.user?.tenantName?.trim() ?? '')
  const [name, setName] = useState('')
  useEffect(() => {
    // issue #7285：登录态已有企业名 ⇒ **不发**那个需要 `system:manage` 的回落请求
    //（纸面在订单详情页常驻挂载，发出去 = 无该码的岗位每进一次页面弹一条 403）
    if (fromLogin) return
    let alive = true
    void fetchCompanyName().then((value) => {
      if (alive) setName(value)
    })
    return () => {
      alive = false
    }
  }, [fromLogin])
  return fromLogin || name
}
