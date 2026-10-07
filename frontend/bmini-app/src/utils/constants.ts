/**
 * 常量配置
 */

// API 基础地址（管理后台 API / Java 服务）
export const API_BASE_URL = process.env.TARO_APP_API_URL || 'http://localhost:8080'

// AI Agent 服务地址（Python 服务）
export const AI_API_BASE_URL = process.env.TARO_APP_AI_API_URL || 'http://localhost:8001'

// 本地存储键名
export const STORAGE_KEYS = {
  TOKEN: 'auth_token',
  USER: 'auth_user',
  TENANT_ID: 'tenant_id',
  // 工人登录态（issue #4733）：与商家账号**彻底分离**的两个键 —— 工人 session id 是不可猜的
  // 服务端会话标识（不是 JWT），WORKER 是「当前工人」的展示缓存（真值仍在服务端）。
  WORKER_SESSION: 'worker_session_id',
  WORKER: 'worker_current',
  // 「记住上次成功登录的账号名」（issue #6478）：**只记账号名**，按登录面分开存、进登录页预填。
  // 🔴 绝不记 PIN / 密码 / 验证码 —— 落盘的键只有这三个 + 上面的登录态键，凭据一个都不进来。
  LOGIN_ACCOUNT_EMPLOYEE: 'login_account_employee',
  LOGIN_ACCOUNT_ADMIN: 'login_account_admin',
  LOGIN_ACCOUNT_WORKER: 'login_account_worker',
} as const

// 默认租户 ID（开发用）
export const DEFAULT_TENANT_ID = 1

// 请求重试配置
export const REQUEST_CONFIG = {
  MAX_RETRIES: 3,
  RETRY_DELAY: 1000, // ms，指数退避基准
  TIMEOUT: 30000,    // 30s
} as const
