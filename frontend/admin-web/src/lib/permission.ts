'use client'

import { useAuthStore } from '@/store/auth'

/**
 * 权限判断 Hook — 与后端 RBAC 口径对齐：
 * - admin / super_admin 角色或 permissions 含 "*" 视为拥有全部权限；
 * - 其余用户按 permissions 中的细粒度权限码判断（如 employee:list / employee:create）。
 *
 * 后端对应：RoleService.getUserPermissions + PermissionInterceptor。
 */
export function usePermission() {
  const user = useAuthStore((s) => s.user)
  const permissions = user?.permissions || []
  const roles = user?.roles || []
  const isAdmin = permissions.includes('*') || roles.includes('admin') || roles.includes('super_admin')

  const has = (code?: string): boolean => {
    if (!code) return true
    if (isAdmin) return true
    return permissions.includes(code)
  }

  return { has, permissions, isAdmin }
}
