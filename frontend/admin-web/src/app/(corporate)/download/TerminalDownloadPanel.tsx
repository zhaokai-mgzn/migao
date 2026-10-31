'use client'

import { useEffect, useState } from 'react'
import {
  ANDROID_MANIFEST_URL,
  WINDOWS_MANIFEST_URL,
  formatBytes,
  parseAndroidManifest,
  parseWindowsManifest,
  type TerminalRelease,
} from '@/lib/terminal-manifest'

// 终端下载页的**数据面**（issue #8195）。
//
// 为什么是客户端组件：清单是**发布后才知道**的事实（版本 / 校验值 / 发布时间），
// 而营销页本身要留在服务端组件里（正文进初始 HTML，SEO 与无 JS 环境都能读，见
// `frontend/admin-web/tests/unit/pages/corporate-pages-server-component-guard.test.ts`）。
// ⇒ 页面（服务端）写静态说明，本组件只负责「把清单读出来」。
//
// 读不到 / 格式坏 / 网络失败 ⇒ 显示「暂未发布」，**不编造版本号**。
// 这一条是本页最容易犯的假绿：页面看着正常、下载按钮点下去 404，或者看到一个不存在的版本。

type LoadState =
  | { status: 'loading' }
  | { status: 'missing' }
  | { status: 'ready'; release: TerminalRelease }

const INITIAL: LoadState = { status: 'loading' }

async function loadRelease(
  url: string,
  parse: (raw: unknown) => TerminalRelease | null,
): Promise<TerminalRelease | null> {
  try {
    const response = await fetch(url, { headers: { accept: 'application/json' } })
    if (!response.ok) return null
    return parse(await response.json())
  } catch {
    // 网络失败与坏 JSON 同口径：清单没拿到就等于没发布，不猜。
    return null
  }
}

function ReleaseCard({
  title,
  subtitle,
  state,
  linkLabel,
  versionText,
  versionHint,
}: {
  title: string
  subtitle: string
  state: LoadState
  linkLabel: string
  versionText: (release: TerminalRelease) => string
  versionHint: string
}) {
  return (
    <div className="flex h-full flex-col rounded-2xl border border-neutral-200 bg-white p-8 shadow-sm">
      <h2 className="text-xl font-bold tracking-tight text-neutral-900">{title}</h2>
      <p className="mt-2 text-sm leading-relaxed text-neutral-500">{subtitle}</p>

      {state.status === 'loading' && (
        <p className="mt-6 text-sm text-neutral-500">正在读取发布信息…</p>
      )}

      {state.status === 'missing' && (
        <div className="mt-6 space-y-2">
          <p className="text-sm font-semibold text-neutral-800">暂未发布</p>
          <p className="text-sm leading-relaxed text-neutral-500">
            该终端还没有可下载的正式版。正式版发布后，本页会自动显示安装包、版本号与校验值。
          </p>
        </div>
      )}

      {state.status === 'ready' && (
        <>
          <dl className="mt-6 grid grid-cols-1 gap-4 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-neutral-500">版本</dt>
              <dd className="mt-1 font-medium text-neutral-900">{versionText(state.release)}</dd>
            </div>
            <div>
              <dt className="text-neutral-500">发布时间</dt>
              <dd className="mt-1 font-medium text-neutral-900">{state.release.publishedAt}</dd>
            </div>
            <div>
              <dt className="text-neutral-500">安装包大小</dt>
              <dd className="mt-1 font-medium text-neutral-900">{formatBytes(state.release.size)}</dd>
            </div>
            <div>
              <dt className="text-neutral-500">版本说明</dt>
              <dd className="mt-1 text-neutral-700">{versionHint}</dd>
            </div>
          </dl>

          {state.release.notes && (
            <p className="mt-5 text-sm leading-relaxed text-neutral-600">{state.release.notes}</p>
          )}

          <div className="mt-5">
            <p className="text-sm text-neutral-500">SHA-256 校验值</p>
            <code className="mt-1 block break-all rounded-lg bg-neutral-50 px-3 py-2 font-mono text-xs text-neutral-600">
              {state.release.sha256}
            </code>
          </div>

          <a
            href={state.release.downloadUrl}
            className="mt-6 inline-flex w-full items-center justify-center rounded-lg bg-primary-600 px-5 py-3 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-primary-700 sm:w-auto"
          >
            {linkLabel}
          </a>
        </>
      )}
    </div>
  )
}

export default function TerminalDownloadPanel() {
  const [windows, setWindows] = useState<LoadState>(INITIAL)
  const [android, setAndroid] = useState<LoadState>(INITIAL)

  useEffect(() => {
    let alive = true
    void (async () => {
      const [win, apk] = await Promise.all([
        loadRelease(WINDOWS_MANIFEST_URL, parseWindowsManifest),
        loadRelease(ANDROID_MANIFEST_URL, parseAndroidManifest),
      ])
      if (!alive) return
      setWindows(win ? { status: 'ready', release: win } : { status: 'missing' })
      setAndroid(apk ? { status: 'ready', release: apk } : { status: 'missing' })
    })()
    return () => {
      alive = false
    }
  }, [])

  return (
    <div className="grid grid-cols-1 gap-8 lg:grid-cols-2">
      <ReleaseCard
        title="Windows 一体机"
        subtitle="Windows 10 / 11 一体机（裁高终端）。下载后双击安装，无需管理员权限。"
        state={windows}
        linkLabel="下载 Windows 安装包"
        versionText={(release) => release.version}
        versionHint="一体机版本"
      />
      <ReleaseCard
        title="Android 手持机"
        subtitle="车间工人手持终端（商米）。下载后用系统安装器安装，不上架应用市场。"
        state={android}
        linkLabel="下载 Android 安装包"
        versionText={(release) =>
          release.versionCode ? `${release.version}（versionCode ${release.versionCode}）` : release.version
        }
        versionHint="versionCode 是系统判断版本高低的依据"
      />
    </div>
  )
}
