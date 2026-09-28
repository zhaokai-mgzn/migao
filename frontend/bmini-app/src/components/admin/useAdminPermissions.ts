/**
 * 当前登录员工的**权限集合**（issue #5654）
 *
 * 真值 = 服务端 `GET /api/auth/me` 的 `permissions`（admin-api `UserInfoResponse`）。
 * 端侧**不发明权限码**，也不缓存到 store（权限改了要重新拉；本 hook 每次进页面拉一次）。
 *
 * 🔴 三态语义（交给 `canOpenAdminSurface` / `canWriteAdminSurface` 消费）：
 * - `null` = **未知**（还没回来 / 拉失败）⇒ 一律按「可能有」（fail-open），
 *   判定权威留给服务端 403 + 显式文案 —— 把「未知」当「无权」就是静默隐藏入口；
 * - `[]` / `['x']` = 已知集合（`'*'` 通配由 `hasPermissionCode` 判真）。
 */
import { useEffect, useState } from 'react'
import { fetchMyPermissions } from '../../services/adminOpsService'

export function useAdminPermissions(): string[] | null {
  const [permissions, setPermissions] = useState<string[] | null>(null)

  useEffect(() => {
    let alive = true
    fetchMyPermissions().then((next) => {
      // 页面已卸载 ⇒ 不再 setState（避免卸载后更新的告警与无意义重渲染）
      if (alive) setPermissions(next)
    })
    return () => {
      alive = false
    }
  }, [])

  return permissions
}

export default useAdminPermissions
