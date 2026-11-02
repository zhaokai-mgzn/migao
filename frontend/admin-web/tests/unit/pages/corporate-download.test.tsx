// case_ids: UI-144
//
// 官网下载页（`/download`）—— 观星台终端正式发布链路的前台（issue #8195）。
//
// ## 病（开工前现取）
//
// | 件 | 读数 |
// |---|---|
// | `https://migaozn.com/download` | **404**（`(corporate)` 下没有该路由，nav / footer 也没有入口） |
// | 终端更新清单 | 只存在于终端程序的硬编码地址（`app.migaozn.com/terminal/latest.json`）⇒ 商家没有任何可见入口 |
// | 下载页要展示的身份 | 版本 / SHA-256 / 大小 / 发布时间 / notes / 两个下载按钮 / 安装说明（安卓未知来源、Windows SmartScreen、检查更新） |
//
// ## 本文件锁什么
//
// 1. **清单缺失 / 格式坏 / 网络失败 ⇒ 明确「暂未发布」**，**不编造版本号**（这是本页最容易犯的假绿：
//    页面看起来正常、商家长按下载却拿到 404，或者更糟——看到一个不存在的新版本）。
// 2. **清单存在 ⇒ 逐项展示 + 两个下载按钮**（href 来自清单的 `download_url`，只接受 http(s)）。
// 3. **安全**：清单里的 `javascript:` / `data:` 伪协议一律不渲染成链接（清单是外部输入）。
// 4. **结构**：页面是服务端组件（`(corporate)` 类级判据另有守卫，这里再钉本页自己的 `h1` 在初始 HTML 里）；
//    Next 侧的 `/terminal/*` 同源转发存在（否则浏览器直连 `app.migaozn.com` 会被 CORS 挡）；
//    `proxy.ts` 的官网白名单含 `/download`（否则裸域访问会被改写 404）；
//    nav / footer 都有入口（否则没人找得到这页）。
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { readFileSync } from 'fs'
import { join } from 'path'

vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

import DownloadPage, { metadata } from '@/app/(corporate)/download/page'

const WINDOWS_MANIFEST = {
  version: '1.0.1.0',
  download_url: 'https://app.migaozn.com/terminal/GuanxingtaiSetup.exe',
  sha256: 'a'.repeat(64),
  size: 328704,
  notes: '首个发布版：车间一体机裁高终端',
  published_at: '2026-10-31',
}

const ANDROID_MANIFEST = {
  versionCode: 7,
  versionName: '1.0.1',
  download_url: 'https://app.migaozn.com/terminal/GuanxingtaiTerminal-1.0.1.apk',
  sha256: 'b'.repeat(64),
  size: 1234567,
  notes: '工人手持终端：登录 + 拍照入库 / 补打 / 发货 + 内置标签打印 + 扫码报工',
  published_at: '2026-10-31',
}

type Responder = (url: string) => Response | Promise<Response>

function jsonResponse(url: string, body: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    url,
    json: async () => body,
  } as unknown as Response
}

function stubFetch(responder: Responder) {
  const fetchMock = vi.fn(async (input: any) => responder(String(input)))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function bothManifests() {
  return stubFetch((url) => {
    if (url.includes('android')) return jsonResponse(url, ANDROID_MANIFEST)
    return jsonResponse(url, WINDOWS_MANIFEST)
  })
}

beforeEach(() => {
  vi.unstubAllGlobals()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('官网下载页：清单正常时逐项展示（issue #8195）', () => {
  it('Windows：版本 / SHA-256 / 大小 / 发布时间 / notes / 下载按钮', async () => {
    bothManifests()
    render(<DownloadPage />)

    expect(await screen.findByText('1.0.1.0')).toBeInTheDocument()
    expect(screen.getByText('a'.repeat(64))).toBeInTheDocument()
    expect(screen.getByText(/321\.0 KB/)).toBeInTheDocument()
    expect(screen.getAllByText('2026-10-31').length).toBeGreaterThan(0)
    expect(screen.getByText(/车间一体机裁高终端/)).toBeInTheDocument()

    const link = screen.getByRole('link', { name: /下载 Windows 安装包/ })
    expect(link).toHaveAttribute('href', WINDOWS_MANIFEST.download_url)
  })

  it('Android：versionName/versionCode 与 APK 下载按钮', async () => {
    bothManifests()
    render(<DownloadPage />)

    expect(await screen.findByText(/1\.0\.1（versionCode 7）/)).toBeInTheDocument()
    expect(screen.getByText('b'.repeat(64))).toBeInTheDocument()
    const link = screen.getByRole('link', { name: /下载 Android 安装包/ })
    expect(link).toHaveAttribute('href', ANDROID_MANIFEST.download_url)
  })

  it('两个清单各自取各自地址（Windows 走 /terminal/latest.json，Android 走 /terminal/android/latest.json）', async () => {
    const fetchMock = bothManifests()
    render(<DownloadPage />)
    await screen.findByText('1.0.1.0')

    const urls = fetchMock.mock.calls.map((call) => String(call[0]))
    expect(urls.some((u) => u === '/terminal/latest.json')).toBe(true)
    expect(urls.some((u) => u === '/terminal/android/latest.json')).toBe(true)
  })
})

describe('清单缺失 / 坏 / 网络失败 ⇒ 明确「暂未发布」，不编造版本号', () => {
  it('两个清单都 404 ⇒ 两处「暂未发布」，且没有任何下载按钮与版本号', async () => {
    stubFetch((url) => jsonResponse(url, { detail: 'Not Found' }, false, 404))
    render(<DownloadPage />)

    await waitFor(() => {
      expect(screen.getAllByText(/暂未发布/).length).toBe(2)
    })
    expect(screen.queryByRole('link', { name: /下载 Windows 安装包/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /下载 Android 安装包/ })).not.toBeInTheDocument()
    expect(screen.queryByText(/\d+\.\d+\.\d+/)).not.toBeInTheDocument()
  })

  it('清单返回坏 JSON ⇒ 「暂未发布」（解析失败不许把页面打崩）', async () => {
    stubFetch((url) => {
      const res = jsonResponse(url, {})
      ;(res as any).json = async () => {
        throw new SyntaxError('Unexpected token < in JSON')
      }
      return res
    })
    render(<DownloadPage />)
    await waitFor(() => {
      expect(screen.getAllByText(/暂未发布/).length).toBe(2)
    })
  })

  it('清单字段缺失 / 类型不对 ⇒ 「暂未发布」（不渲染半份数据）', async () => {
    stubFetch((url) =>
      url.includes('android')
        ? jsonResponse(url, { ...ANDROID_MANIFEST, versionCode: 'seven' })
        : jsonResponse(url, { ...WINDOWS_MANIFEST, sha256: 'not-a-hash' }),
    )
    render(<DownloadPage />)
    await waitFor(() => {
      expect(screen.getAllByText(/暂未发布/).length).toBe(2)
    })
  })

  it('网络失败（fetch reject）⇒ 「暂未发布」而不是抛错', async () => {
    stubFetch(() => Promise.reject(new TypeError('Failed to fetch')))
    render(<DownloadPage />)
    await waitFor(() => {
      expect(screen.getAllByText(/暂未发布/).length).toBe(2)
    })
  })

  it('只有 Android 已发布 ⇒ Windows 暂未发布、Android 正常（互不牵连）', async () => {
    stubFetch((url) =>
      url.includes('android')
        ? jsonResponse(url, ANDROID_MANIFEST)
        : jsonResponse(url, {}, false, 404),
    )
    render(<DownloadPage />)

    expect(await screen.findByRole('link', { name: /下载 Android 安装包/ })).toBeInTheDocument()
    expect(screen.getAllByText(/暂未发布/).length).toBe(1)
    expect(screen.queryByRole('link', { name: /下载 Windows 安装包/ })).not.toBeInTheDocument()
  })
})

describe('安全：清单是外部输入，伪协议不许变成链接', () => {
  it('download_url 是 javascript: ⇒ 该端按「暂未发布」处理，不渲染 href', async () => {
    stubFetch((url) =>
      url.includes('android')
        ? jsonResponse(url, { ...ANDROID_MANIFEST, download_url: 'javascript:alert(1)' })
        : jsonResponse(url, WINDOWS_MANIFEST),
    )
    render(<DownloadPage />)

    expect(await screen.findByRole('link', { name: /下载 Windows 安装包/ })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /下载 Android 安装包/ })).not.toBeInTheDocument()
    expect(screen.getAllByText(/暂未发布/).length).toBe(1)
  })
})

describe('首屏（服务端渲染）：标题与安装说明在初始 HTML 里', () => {
  it('渲染出 h1 与三段安装说明，且不含「加载中...」骨架', () => {
    bothManifests()
    const { container } = render(<DownloadPage />)
    const html = container.innerHTML

    expect(container.querySelector('h1')?.textContent).toContain('下载观星台终端')
    expect(html).not.toContain('加载中...')
    expect(html).toContain('未知来源')
    expect(html).toContain('SmartScreen')
    expect(html).toContain('检查更新')
    expect(metadata.title).toBeTruthy()
    expect(String(metadata.description)).toMatch(/终端|下载/)
  })
})

describe('结构：同源转发与入口（否则这页在线上打不到）', () => {
  const pkg = process.cwd()

  it('next.config.mjs 把 /terminal/* 同源转发到 app.migaozn.com（浏览器直连会被 CORS 挡）', () => {
    const src = readFileSync(join(pkg, 'next.config.mjs'), 'utf-8')
    expect(src).toMatch(/source:\s*'\/terminal\/:path\*'/)
    expect(src).toMatch(/app\.migaozn\.com/)
  })

  it('proxy.ts 的官网白名单含 /download（否则裸域访问会被改写 404）', () => {
    const src = readFileSync(join(pkg, 'src', 'proxy.ts'), 'utf-8')
    expect(src).toMatch(/'\/download'/)
  })

  it('nav 与 footer 都有下载入口', () => {
    const nav = readFileSync(join(pkg, 'src', 'components', 'corporate', 'CorporateNav.tsx'), 'utf-8')
    const footer = readFileSync(join(pkg, 'src', 'components', 'corporate', 'CorporateFooter.tsx'), 'utf-8')
    for (const [name, src] of [
      ['CorporateNav', nav],
      ['CorporateFooter', footer],
    ] as const) {
      expect(src, `${name} 缺 /download 入口`).toMatch(/href=\{[^}]*'\/download'|href="\/download"|'\/download'/)
    }
  })
})
