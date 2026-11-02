// case_ids: UI-144
//
// 终端发布清单的**解析真值源**（issue #8195，`frontend/admin-web/src/lib/terminal-manifest.ts`）。
//
// 为什么单独成文件：下载页（`tests/unit/pages/corporate-download.test.tsx`）测的是**页面行为**
// （渲染 / 「暂未发布」/ 链接），而「什么算一份合格清单」是**纯函数**判据 —— 两者混在一起时，
// 清单字段一改就要改页面测试，归因也会指错对象。QA 覆盖率映射同样按路径要求这份文件
// （`frontend/admin-web` 模块的 `src/lib/**` ⇒ `tests/unit/lib/**`）。
//
// 口径（与终端仓的读法对齐，**改名前先看终端仓**）：
//   · Windows `src/terminal/Program.cs` 读 `version` / `notes` / `download_url`（字符串比较）
//   · Android `android/.../Updater.java` 读 `versionCode`(int) / `versionName` / `download_url`
//   · 两个页面共用：`sha256` / `size` / `published_at`
// 任何一项不合格 ⇒ 整条作废（返回 `null`）：页面宁可写「暂未发布」，也不显示半份数据。
import { describe, it, expect } from 'vitest'
import {
  ANDROID_MANIFEST_URL,
  WINDOWS_MANIFEST_URL,
  formatBytes,
  parseAndroidManifest,
  parseWindowsManifest,
} from '@/lib/terminal-manifest'

const WINDOWS = {
  version: '1.0.1.0',
  download_url: 'https://app.migaozn.com/terminal/GuanxingtaiSetup.exe',
  sha256: 'a'.repeat(64),
  size: 328704,
  notes: '首个发布版：车间一体机裁高终端',
  published_at: '2026-10-31',
}

const ANDROID = {
  versionCode: 7,
  versionName: '1.0.1',
  download_url: 'https://app.migaozn.com/terminal/GuanxingtaiTerminal-1.0.1.apk',
  sha256: 'b'.repeat(64),
  size: 1234567,
  notes: '工人手持终端',
  published_at: '2026-10-31',
}

describe('清单地址（与 nginx / 终端仓逐字一致）', () => {
  it('Windows 走 /terminal/latest.json，Android 走 /terminal/android/latest.json', () => {
    expect(WINDOWS_MANIFEST_URL).toBe('/terminal/latest.json')
    expect(ANDROID_MANIFEST_URL).toBe('/terminal/android/latest.json')
  })
})

describe('parseWindowsManifest：只认终端客户端真实字段名（snake_case）', () => {
  it('合格清单 ⇒ 归一成 TerminalRelease（platform=windows）', () => {
    const parsed = parseWindowsManifest(WINDOWS)
    expect(parsed).toEqual({
      platform: 'windows',
      version: '1.0.1.0',
      downloadUrl: WINDOWS.download_url,
      sha256: 'a'.repeat(64),
      size: 328704,
      notes: WINDOWS.notes,
      publishedAt: '2026-10-31',
    })
  })

  it('驼峰字段（downloadUrl / publishedAt）不算合格 —— 清单契约是对方定的', () => {
    const camel = {
      version: '1.0.1.0',
      downloadUrl: WINDOWS.download_url,
      sha256: WINDOWS.sha256,
      size: 1,
      publishedAt: '2026-10-31',
    }
    expect(parseWindowsManifest(camel)).toBeNull()
  })

  it('任一项不合格 ⇒ 整条作废（不渲染半份数据）', () => {
    expect(parseWindowsManifest({ ...WINDOWS, version: '' })).toBeNull()
    expect(parseWindowsManifest({ ...WINDOWS, version: '   ' })).toBeNull()
    expect(parseWindowsManifest({ ...WINDOWS, size: -1 })).toBeNull()
    expect(parseWindowsManifest({ ...WINDOWS, size: 1.5 })).toBeNull()
    expect(parseWindowsManifest({ ...WINDOWS, size: '328704' })).toBeNull()
    expect(parseWindowsManifest({ ...WINDOWS, sha256: 'not-a-hash' })).toBeNull()
    expect(parseWindowsManifest({ ...WINDOWS, sha256: 'a'.repeat(63) })).toBeNull()
    expect(parseWindowsManifest({ ...WINDOWS, published_at: '2026/10/31' })).toBeNull()
    expect(parseWindowsManifest({ ...WINDOWS, notes: 42 })).toBeNull()
    expect(parseWindowsManifest(null)).toBeNull()
    expect(parseWindowsManifest('not an object')).toBeNull()
    expect(parseWindowsManifest([])).toBeNull()
  })

  it('下载地址只接受 https 绝对地址或站内绝对路径（伪协议一律拒绝）', () => {
    expect(parseWindowsManifest({ ...WINDOWS, download_url: 'javascript:alert(1)' })).toBeNull()
    expect(parseWindowsManifest({ ...WINDOWS, download_url: 'data:text/html,<b>x' })).toBeNull()
    expect(parseWindowsManifest({ ...WINDOWS, download_url: '//evil.example/a.exe' })).toBeNull()
    expect(parseWindowsManifest({ ...WINDOWS, download_url: 'http://app.migaozn.com/a.exe' })).toBeNull()
    const relative = parseWindowsManifest({ ...WINDOWS, download_url: '/terminal/a.exe' })
    expect(relative?.downloadUrl).toBe('/terminal/a.exe')
  })

  it('sha256 大小写归一（终端算出来的十六进制可能是大写）', () => {
    expect(parseWindowsManifest({ ...WINDOWS, sha256: 'A'.repeat(64) })?.sha256).toBe('a'.repeat(64))
  })

  it('notes 可以缺省（老清单没有版本说明），其余字段不行', () => {
    const { notes, ...withoutNotes } = WINDOWS
    expect(parseWindowsManifest(withoutNotes)?.notes).toBe('')
    expect(notes).toBeTruthy()
  })
})

describe('parseAndroidManifest：versionCode 必须是正整数（更新比较的唯一依据）', () => {
  it('合格清单 ⇒ platform=android 且带 versionCode', () => {
    const parsed = parseAndroidManifest(ANDROID)
    expect(parsed?.platform).toBe('android')
    expect(parsed?.version).toBe('1.0.1')
    expect(parsed?.versionCode).toBe(7)
    expect(parsed?.size).toBe(1234567)
  })

  it('versionCode 非法 ⇒ 整条作废（猜一个会让已装机器收不到更新或收到降级）', () => {
    expect(parseAndroidManifest({ ...ANDROID, versionCode: 0 })).toBeNull()
    expect(parseAndroidManifest({ ...ANDROID, versionCode: -3 })).toBeNull()
    expect(parseAndroidManifest({ ...ANDROID, versionCode: 1.5 })).toBeNull()
    expect(parseAndroidManifest({ ...ANDROID, versionCode: 'seven' })).toBeNull()
    expect(parseAndroidManifest({ ...ANDROID, versionCode: undefined })).toBeNull()
  })

  it('缺 versionName / sha256 坏 / 地址伪协议 ⇒ 整条作废', () => {
    expect(parseAndroidManifest({ ...ANDROID, versionName: '' })).toBeNull()
    expect(parseAndroidManifest({ ...ANDROID, sha256: 'zz' })).toBeNull()
    expect(parseAndroidManifest({ ...ANDROID, download_url: 'javascript:alert(1)' })).toBeNull()
  })
})

describe('formatBytes：与页面上看到的读数逐字一致', () => {
  it('B / KB / MB 三档各一位小数以内', () => {
    expect(formatBytes(0)).toBe('0 B')
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(1024)).toBe('1.0 KB')
    expect(formatBytes(328704)).toBe('321.0 KB')
    expect(formatBytes(1234567)).toBe('1.2 MB')
  })

  it('非法读数给空串（不显示 NaN KB）', () => {
    expect(formatBytes(-1)).toBe('')
    expect(formatBytes(Number.NaN)).toBe('')
  })
})
