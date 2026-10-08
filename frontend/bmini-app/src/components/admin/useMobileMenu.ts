/**
 * 手机端菜单（**服务端按岗位投影**）—— issue #6570（用户 2026-10-08 裁定「走 B」）
 *
 * 真值 = `GET /api/auth/me` 的 `mobileSurfaces`（服务端 `MobileSurfaces.visibleFor` 按生效权限集合过滤）。
 * 端侧**不再自己拿 permissions 判菜单**（旧口径见 `src/utils/adminPermission.ts` 的注释：
 * 「未知 ⇒ 照显」= fail-open，员工会看到自己没有的入口，点进去逐项 403）。
 *
 * 三态（交给消费方决定怎么渲染，**不在这里吞掉**）：
 * - `loading` —— 还没回来；
 * - `ok` —— 服务端答复（`surfaces` 可能是**空数组**：本岗位一个面都没有，这是**正常的答复**，不是失败）；
 * - `error` —— 没拿到（网络 / 未登录 / 服务端失败）。消费方**必须显式说**，不许静默隐藏
 *   （「菜单没加载出来 + 重试」，见「我的」页的 `profile-menu-error`）。
 */
import { useCallback, useEffect, useState } from 'react'
import { fetchMyMobileMenu, type MobileSurface } from '../../services/adminOpsService'

export interface MobileMenuState {
  state: 'loading' | 'ok' | 'error'
  surfaces: MobileSurface[]
  /** 重拉一次（error 态给用户的可行动出口） */
  reload: () => void
}

export function useMobileMenu(): MobileMenuState {
  const [state, setState] = useState<'loading' | 'ok' | 'error'>('loading')
  const [surfaces, setSurfaces] = useState<MobileSurface[]>([])
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    let alive = true
    fetchMyMobileMenu().then((menu) => {
      // 页面已卸载 ⇒ 不再 setState（避免卸载后更新的告警与无意义重渲染）
      if (!alive) return
      setSurfaces(menu.surfaces)
      setState(menu.state)
    })
    return () => {
      alive = false
    }
  }, [nonce])

  const reload = useCallback(() => setNonce((n) => n + 1), [])

  return { state, surfaces, reload }
}

export default useMobileMenu
