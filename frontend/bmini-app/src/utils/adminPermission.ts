/**
 * 管理面（手机端）台账 · 权限判据 · 拒绝文案 —— issue #5654
 *
 * 背景：管理面 11 项**只有电脑端能做**，管理员离店即失能。用户 2026-09-26 逐字点名先补 4 项
 * （排产/派单 · 入库过账 · 售后处理 · 计件工资报表），载体 = bmini-app 的 **h5 产物**（#5650）。
 *
 * 🔴 本文件是「哪 4 项 + 每项要哪个权限码 + 拒绝时说什么」的**单一真值**（端侧一份）：
 * - **权限码真值在后端注解**（`@RequirePermission`），本台账是它的镜像；
 *   `tests/admin-surfaces-permission-codes.test.ts` 直接解析 4 个 Controller 的注解**逐值比对**
 *   ⇒ 台账与后端漂移必红（不是靠纪律）。
 * - **可见性判据 = 「能读这一页」的端点码**（不是菜单节点码）：手机端没有 admin-web 那套
 *   服务端下发菜单树，若拿写码判可见，只读角色会看不到页面（#5034/#5246/#5291 反复裁定的同族坑）。
 *   ⚠️ 已登记的两处「菜单节点码 ≠ 端点码」（本单**不动后端、不改 admin-web**，只登记）：
 *     ① 智能派单：`frontend/admin-web/src/config/menu.ts` 节点挂 `processing:manage`，
 *        而其读端点（`GET /api/admin/production/pool`）要 `processing:view`；
 *     ② 计件工资：菜单节点挂 `production:view`，而端点（`GET .../piecework/summary`）
 *        要 `processing:manage` ⇒ 两者取**端点码**，故「PC 上看得见、手机上可能看不见」是
 *        **有意**的（手机上宁可不出入口，也不给一个点进去只有 403 的死页；端点拒绝另有显式文案）。
 * - 🔴 端侧**只读服务端下发的权限集合**（`GET /api/auth/me` 的 `permissions`），**不自己发明码**；
 *   集合**未知**（拉取失败）⇒ 一律按「可能有」处理（fail-open），把判定交给服务端 403 + 显式文案
 *   —— 静默隐藏入口是 #5642 明令禁止的形态。
 */
/** 4 个管理面的键（顺序 = 「我的」页入口顺序） */
export type AdminSurfaceKey = 'pool' | 'inbound' | 'after-sales' | 'piecework'

/** 端点上的一次映射（与后端注解逐值比对用） */
export interface AdminEndpoint {
  method: 'GET' | 'POST' | 'PUT' | 'PATCH'
  /** 仓库相对全路径（守卫按它读注解） */
  path: string
}

export interface AdminSurface {
  key: AdminSurfaceKey
  /** 中文名（拒绝文案与菜单都用它，不另起一份） */
  label: string
  /** bmini-app 页面路由（`src/app.config.ts` 的 pages 字面量） */
  route: string
  /** 页面文件（仓库相对全路径；守卫射程） */
  pageFile: string
  /** 该面读端的 Controller 文件（权限码真值所在） */
  controllerFile: string
  /** 读码 = 「能读这一页」的判据（后端注解逐字） */
  readPermission: string
  readEndpoint: AdminEndpoint
  /** 写码（无写动作的面不填） */
  writePermission?: string
  writeEndpoint?: AdminEndpoint
  /** 写动作名（拒绝文案里的动词，如「派单」） */
  writeActionLabel?: string
}

export const ADMIN_SURFACES: AdminSurface[] = [
  {
    key: 'pool',
    label: '智能派单',
    route: '/pages/admin/pool/index',
    pageFile: 'src/pages/admin/pool/index.tsx',
    controllerFile:
      'backend/admin-api/src/main/java/com/migao/admin/controller/ProductionPoolController.java',
    readPermission: 'processing:view',
    readEndpoint: { method: 'GET', path: '/api/admin/production/pool' },
    writePermission: 'processing:update',
    writeEndpoint: { method: 'POST', path: '/api/admin/production/pool/dispatch' },
    writeActionLabel: '派单',
  },
  {
    key: 'inbound',
    label: '入库过账',
    route: '/pages/admin/inbound/index',
    pageFile: 'src/pages/admin/inbound/index.tsx',
    controllerFile:
      'backend/admin-api/src/main/java/com/migao/admin/controller/InboundOrderController.java',
    readPermission: 'inbound:view',
    readEndpoint: { method: 'GET', path: '/api/admin/inbound-orders' },
    writePermission: 'inbound:create',
    writeEndpoint: { method: 'PATCH', path: '/api/admin/inbound-orders/{id}' },
    writeActionLabel: '过账',
  },
  {
    key: 'after-sales',
    label: '售后处理',
    route: '/pages/admin/after-sales/index',
    pageFile: 'src/pages/admin/after-sales/index.tsx',
    controllerFile:
      'backend/admin-api/src/main/java/com/migao/admin/controller/AfterSalesController.java',
    readPermission: 'after_sales:view',
    readEndpoint: { method: 'GET', path: '/api/admin/after-sales' },
    writePermission: 'order:refund',
    writeEndpoint: { method: 'PUT', path: '/api/admin/after-sales/{id}/status' },
    writeActionLabel: '处理',
  },
  {
    key: 'piecework',
    label: '计件工资报表',
    route: '/pages/admin/piecework/index',
    pageFile: 'src/pages/admin/piecework/index.tsx',
    controllerFile:
      'backend/admin-api/src/main/java/com/migao/admin/controller/ProductionController.java',
    readPermission: 'processing:manage',
    readEndpoint: { method: 'GET', path: '/api/admin/production/piecework/summary' },
  },
]

export function findAdminSurface(key: AdminSurfaceKey): AdminSurface {
  const surface = ADMIN_SURFACES.find((item) => item.key === key)
  if (!surface) throw new Error(`未登记的管理面：${key}`)
  return surface
}

/**
 * 权限集合判定（**唯一入口**）。
 *
 * `'*'` = 通配（服务端给管理员的超权标记，`RoleService` 的 `["*"]` 口径）⇒ 一律判真；
 * 集合缺失/非数组 ⇒ 判假（调用方据「未知」另作处置，见 `canOpenAdminSurface`）。
 */
export function hasPermissionCode(
  permissions: string[] | null | undefined,
  code: string,
): boolean {
  if (!Array.isArray(permissions)) return false
  return permissions.includes('*') || permissions.includes(code)
}

/**
 * 能否打开该管理面。
 *
 * 🔴 集合**未知**（`null`，`/api/auth/me` 还没回来或失败）⇒ **判真**（fail-open）：
 * 端侧集合只用于「确定无权时不出入口」，判定权威在服务端（403 + 显式文案），
 * 拿「未知」当「无权」就是 #5642 点名的静默隐藏。
 */
export function canOpenAdminSurface(
  permissions: string[] | null | undefined,
  key: AdminSurfaceKey,
): boolean {
  if (permissions === null || permissions === undefined) return true
  return hasPermissionCode(permissions, findAdminSurface(key).readPermission)
}

/** 能否执行该面的写动作（无写动作的面恒真；集合未知 ⇒ 判真，同上） */
export function canWriteAdminSurface(
  permissions: string[] | null | undefined,
  key: AdminSurfaceKey,
): boolean {
  const surface = findAdminSurface(key)
  if (!surface.writePermission) return true
  if (permissions === null || permissions === undefined) return true
  return hasPermissionCode(permissions, surface.writePermission)
}

/**
 * 「无 XX 权限」的**逐字文案**（唯一生成处）。
 *
 * 🔴 必须是**可行动**的：说清缺哪一项、缺哪个码 —— 只写「无权限」等于让管理员回电脑端问人。
 * 形态：`无「入库过账」过账权限（需要权限码 inbound:create）`
 */
export function missingPermissionText(
  key: AdminSurfaceKey,
  kind: 'read' | 'write' = 'read',
): string {
  const surface = findAdminSurface(key)
  if (kind === 'write') {
    return `无「${surface.label}」${surface.writeActionLabel || '操作'}权限（需要权限码 ${surface.writePermission}）`
  }
  return `无「${surface.label}」查看权限（需要权限码 ${surface.readPermission}）`
}

/** 「我的」页要显示的入口（集合未知 ⇒ 全部显示，见 `canOpenAdminSurface`） */
export function visibleAdminSurfaces(
  permissions: string[] | null | undefined,
): AdminSurface[] {
  return ADMIN_SURFACES.filter((surface) => canOpenAdminSurface(permissions, surface.key))
}

// ══════════════════════════════════════════════════════════════════════════
// 平台能力面（issue #5654 验收判据 4）
//
// 4 个管理面**全部只用 h5 可用的 Taro API**（HTTP + `Taro.showModal` 确认框）
// ⇒ 本单**无平台缺口**。但它必须是**可核验的声明**，不是一句注释：
// `tests/admin-surfaces-platform-guard.test.ts` 把「声明集」与「射程内实测集」**双向比对**，
// 并在命中 #5650 的两张清单（h5 未实现 / 只走微信 JS-SDK）时要求登记缺口文案 +
// 该文案被页面渲染 —— 缺任一项即红。
// ══════════════════════════════════════════════════════════════════════════

/** 守卫射程内**声明**用到的 Taro API（实测集必须与它逐值相等，多一个/少一个都红） */
export const ADMIN_SURFACE_TARO_APIS: string[] = ['redirectTo', 'showModal']

/**
 * 平台能力缺口台账：键 = Taro API 名，值 = 该 API 在**用不了的平台**上用户看到什么。
 *
 * 本轮**空台账**（4 项零小程序专有能力依赖）—— 空不是「没做」，而是被守卫核验过的结论：
 * 「清单 ∩ 实测用法 = ∅」。一旦有人往管理面加 `Taro.scanCode` 这类调用，
 * 守卫先红（声明与实测不符），补声明后还会要「缺口文案 + 页面渲染」两件东西。
 *
 * 🔴 台账**只许缩短且条目必须活着**（同 #5650 的 `H5_API_OUTLET_LEDGER`）：
 * 登记了一个射程内已不存在的 API ⇒ 红（防止台账变成自我复制的历史文档）。
 */
export const ADMIN_SURFACE_PLATFORM_GAP_HINTS: Record<string, string> = {}

/** 守卫射程：4 个页面 + 管理面共享实现（服务 / 权限 / 确认框 / 状态组件 / 权限 hook） */
export const ADMIN_SURFACE_SCOPE_FILES: string[] = [
  ...ADMIN_SURFACES.map((surface) => surface.pageFile),
  'src/services/adminOpsService.ts',
  'src/utils/adminPermission.ts',
  'src/utils/adminConfirm.ts',
  'src/utils/afterSalesFlow.ts',
  'src/components/admin/SurfaceState.tsx',
  'src/components/admin/useAdminPermissions.ts',
]
