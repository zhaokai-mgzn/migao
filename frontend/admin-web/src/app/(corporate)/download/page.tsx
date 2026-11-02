import type { Metadata } from 'next'
import { PageHero } from '@/components/corporate/CorporateSection'
import TerminalDownloadPanel from './TerminalDownloadPanel'

// 本页必须是**服务端组件**（不要在这里加 'use client'，issue #6307）：
// 正文（标题、安装说明、校验方法）由 SSR 渲染进初始 HTML，SEO 与无 JS 环境都能读；
// 只有「读发布清单」那一块是客户端子组件（`TerminalDownloadPanel`）。
// 类级判据 = frontend/admin-web/tests/unit/pages/corporate-pages-server-component-guard.test.ts
//
// 安装包真身在 `app.migaozn.com/terminal/`（终端程序的更新检查地址），本页只做展示与引导：
// 版本 / 校验值 / 发布时间一律**来自清单**（读不到就写「暂未发布」，不写死任何版本号）。

export const metadata: Metadata = {
  title: '下载中心 — 观星台终端（车间一体机 / 工人手持机）',
  description:
    '观星台终端安装包下载：车间一体机 Windows 版与工人手持机 Android 版，含版本号、SHA-256 校验值与安装说明（未知来源安装、SmartScreen 提示、检查更新）。',
}

const INSTALL_NOTES = [
  {
    title: 'Windows：首次运行的系统提示',
    body: '安装包未购买商业代码签名证书，Windows 10 / 11 首次运行可能弹出 SmartScreen 提示「Windows 已保护您的电脑」。选择「更多信息」后点「仍要运行」即可完成安装；安装包是否被篡改，请对照本页公布的 SHA-256 校验值。',
  },
  {
    title: 'Android：允许安装未知来源应用',
    body: '手持机不在任何应用市场发布，安装包直接从本页下载。下载后按系统提示为浏览器或文件管理器开启「安装未知来源应用」权限，再用系统安装器完成安装。',
  },
  {
    title: '检查更新',
    body: '终端内「检查更新」读取的是发布清单（Windows 读 /terminal/latest.json，Android 读 /terminal/android/latest.json）；清单出现更高版本时按提示下载安装，不覆盖已配置的企业号与工号。',
  },
]

const VERIFY_STEPS = [
  { label: 'Windows（资源管理器 / PowerShell）', command: 'certutil -hashfile 安装包路径 SHA256' },
  { label: 'macOS / Linux', command: 'shasum -a 256 安装包路径' },
  { label: 'Linux（coreutils）', command: 'sha256sum 安装包路径' },
]

export default function DownloadPage() {
  return (
    <>
      <PageHero
        kicker="下载中心"
        title="下载观星台终端"
        lead="车间一体机（Windows）与工人手持机（Android）的正式安装包在此下载。版本号、发布时间与校验值以发布清单为准；尚未发布的终端会明确标注，不以占位版本充数。"
        chips={['Windows 10 / 11 一体机', 'Android 手持机（商米）', '官网直发 · 不上架应用市场']}
      />

      <section className="bg-white py-16 sm:py-20">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <TerminalDownloadPanel />
        </div>
      </section>

      <section className="bg-neutral-50 py-16 sm:py-20">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <span className="corporate-kicker">安装说明</span>
          <h2 className="mt-3 text-2xl font-bold tracking-tight text-neutral-900 sm:text-3xl">
            安装前请先看这三条
          </h2>
          <div className="mt-10 grid grid-cols-1 gap-6 md:grid-cols-3">
            {INSTALL_NOTES.map((item) => (
              <div key={item.title} className="rounded-2xl border border-neutral-200 bg-white p-6">
                <h3 className="text-base font-semibold text-neutral-900">{item.title}</h3>
                <p className="mt-3 text-sm leading-relaxed text-neutral-600">{item.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="bg-white py-16 sm:py-20">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <span className="corporate-kicker">校验</span>
          <h2 className="mt-3 text-2xl font-bold tracking-tight text-neutral-900 sm:text-3xl">
            用 SHA-256 确认安装包没有被改过
          </h2>
          <p className="mt-4 max-w-3xl text-sm leading-relaxed text-neutral-600">
            每个安装包都有唯一的 SHA-256 值，页面上显示的值与您在命令行算出的值一致，说明文件完整、没有被替换。
            终端软件本身也会在启动日志里记录自身的 SHA-256，便于事后核对。
          </p>
          <div className="mt-8 grid grid-cols-1 gap-4 md:grid-cols-3">
            {VERIFY_STEPS.map((step) => (
              <div key={step.label} className="rounded-2xl border border-neutral-200 bg-neutral-50 p-5">
                <p className="text-sm font-medium text-neutral-900">{step.label}</p>
                <code className="mt-2 block break-all font-mono text-xs text-neutral-600">{step.command}</code>
              </div>
            ))}
          </div>
          <p className="mt-8 text-sm leading-relaxed text-neutral-500">
            Windows 版尚未购买商业代码签名证书，这是当前口径：不签名、公布 SHA-256、由安装程序自证哈希。
            证书补齐后会在这里同步说明。
          </p>
        </div>
      </section>
    </>
  )
}
