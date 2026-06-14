/**
 * 常量配置
 */

// API 基础地址（管理后台 API / Java 服务）
export const API_BASE_URL = process.env.TARO_APP_API_URL || 'http://localhost:8080'

// AI Agent 服务地址（Python 服务）
export const AI_API_BASE_URL = process.env.TARO_APP_AI_API_URL || 'http://localhost:8000'

// 本地存储键名
export const STORAGE_KEYS = {
  TOKEN: 'auth_token',
  USER: 'auth_user',
  TENANT_ID: 'tenant_id',
} as const

// 默认租户 ID（开发用）
export const DEFAULT_TENANT_ID = 1

// 请求重试配置
export const REQUEST_CONFIG = {
  MAX_RETRIES: 3,
  RETRY_DELAY: 1000, // ms，指数退避基准
  TIMEOUT: 30000,    // 30s
} as const
