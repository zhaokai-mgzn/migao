/**
 * 观星台终端的**发布清单**解析（issue #8195）—— 官网下载页与「暂未发布」判定的唯一真值源。
 *
 * 清单由 `.github/workflows/terminal-publish.yml` → `deploy/scripts/terminal-publish-ci.sh prepare`
 * 生成并发布到 `app.migaozn.com/terminal/` 下：
 *   · Windows：`/terminal/latest.json`（终端 `Program.cs` 读 `version` / `notes` / `download_url`）
 *   · Android：`/terminal/android/latest.json`（终端 `Updater.java` 读 `versionCode` / `versionName` / `download_url`）
 *
 * ⚠️ 字段名是**对方定的**（终端仓已上线，改不动）：`download_url` / `published_at` 是 snake_case、
 * Android 是 `versionCode` / `versionName`。这里**不做驼峰归一**，改名前先看终端仓。
 *
 * 解析原则：**任何一项不合格就整条作废**（返回 `null`）。理由 = 下载页的承诺是
 * 「显示出来的东西都能下载、都能校验」：半份数据比空白更坏（商家长按下载拿到 404，
 * 或者看到一个不存在的版本）。所以宁可显示「暂未发布」。
 */

export type TerminalPlatform = 'windows' | 'android'

export interface TerminalRelease {
  platform: TerminalPlatform
  /** Windows：`1.0.1.0`（与终端 `Application.ProductVersion` 同形）；Android：`versionName` */
  version: string
  /** 仅 Android：更新比较的**唯一**依据（必须单调递增） */
  versionCode?: number
  downloadUrl: string
  sha256: string
  /** 字节数（原值；展示用 `formatBytes`） */
  size: number
  notes: string
  /** `YYYY-MM-DD` */
  publishedAt: string
}

/** 清单地址（**同源**：由 `next.config.mjs` 的 rewrites 转发到 `app.migaozn.com/terminal/`）。 */
export const WINDOWS_MANIFEST_URL = '/terminal/latest.json'
export const ANDROID_MANIFEST_URL = '/terminal/android/latest.json'

const SHA256_RE = /^[0-9a-f]{64}$/i
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/

function asText(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  return trimmed === '' ? null : trimmed
}

/**
 * `notes` 是可选字段（老清单可以没有），但**给了就必须是字符串**：
 * `notes: 42` 这种形态说明发布腿或人工改坏了清单，整条作废比把 `42` 渲染上屏好。
 */
function notesOf(row: Record<string, unknown>): string | null {
  if (row.notes === undefined || row.notes === null) return ''
  return typeof row.notes === 'string' ? row.notes.trim() : null
}

function asPositiveInt(value: unknown): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  if (!Number.isInteger(value) || value <= 0) return null
  return value
}

/**
 * 下载地址：只接受 `https://` 绝对地址或站内绝对路径。
 * 🔴 清单是**外部输入**（发布腿写、浏览器读）：`javascript:` / `data:` 绝不能变成 `href`
 * （`<a href="javascript:...">` 是脚本执行面，不是下载）。
 */
function asDownloadUrl(value: unknown): string | null {
  const text = asText(value)
  if (!text) return null
  if (/^https:\/\/[^\s]+$/i.test(text)) return text
  if (text.startsWith('/') && !text.startsWith('//')) return text
  return null
}

function asSha256(value: unknown): string | null {
  const text = asText(value)
  return text && SHA256_RE.test(text) ? text.toLowerCase() : null
}

function asPublishedAt(value: unknown): string | null {
  const text = asText(value)
  return text && DATE_RE.test(text) ? text : null
}

/** Windows 清单（`latest.json`）。任何字段不合格 ⇒ `null`。 */
export function parseWindowsManifest(raw: unknown): TerminalRelease | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null
  const row = raw as Record<string, unknown>
  const version = asText(row.version)
  const downloadUrl = asDownloadUrl(row.download_url)
  const sha256 = asSha256(row.sha256)
  const size = asPositiveInt(row.size)
  const publishedAt = asPublishedAt(row.published_at)
  const notes = notesOf(row)
  if (!version || !downloadUrl || !sha256 || size === null || !publishedAt || notes === null) return null
  return {
    platform: 'windows',
    version,
    downloadUrl,
    sha256,
    size,
    notes,
    publishedAt,
  }
}

/** Android 清单（`android/latest.json`）。`versionCode` 必须是正整数（更新比较的唯一依据）。 */
export function parseAndroidManifest(raw: unknown): TerminalRelease | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null
  const row = raw as Record<string, unknown>
  const versionCode = asPositiveInt(row.versionCode)
  const version = asText(row.versionName)
  const downloadUrl = asDownloadUrl(row.download_url)
  const sha256 = asSha256(row.sha256)
  const size = asPositiveInt(row.size)
  const publishedAt = asPublishedAt(row.published_at)
  const notes = notesOf(row)
  if (versionCode === null || !version || !downloadUrl || !sha256 || size === null || !publishedAt || notes === null) {
    return null
  }
  return {
    platform: 'android',
    version,
    versionCode,
    downloadUrl,
    sha256,
    size,
    notes,
    publishedAt,
  }
}

/** 安装包大小的人类可读读数（保留一位小数：安装包按 KB/MB 量级，多余精度没有意义）。 */
export function formatBytes(size: number): string {
  if (!Number.isFinite(size) || size < 0) return ''
  if (size < 1024) return `${size} B`
  const kb = size / 1024
  if (kb < 1024) return `${kb.toFixed(1)} KB`
  return `${(kb / 1024).toFixed(1)} MB`
}
