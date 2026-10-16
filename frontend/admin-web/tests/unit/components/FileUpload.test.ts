// @vitest-environment jsdom
// case_ids: UI-105
/**
 * `FileUpload` 共享上传件的接口契约（issue #7007）。
 *
 * 这一份只钉**真契约**（会红的），不测实现细节：
 * ① `label`/`hint` 给了才渲染；
 * ② `effectiveMax = multiple ? maxFiles : 1` ⇒ `value.length >= effectiveMax` 时
 *    **不渲染拖拽上传区**（「满了就不再显示上传入口」，不是「让用户点了才报错」）；
 * ③ `formatSize` 的三档人类可读体积（`<1024 B` / `KB` 一位小数 / `MB` 一位小数）+
 *    已传文件列表渲染文件名与体积；
 * ④ 超限文件（`size > maxSize*1024*1024`）⇒ 调 `toast.error` 且**不调上传接口**
 *    （真实反例保护：只弹提示不拦请求 = 用户以为被挡下了，服务端其实收了）；
 * ⑤ 上传中条目的进度条 `style.width` = `${progress}%`；失败态进度条 = `bg-red-500`；
 * ⑥ 暖色收口：上传中卡片 `border-primary-200 bg-primary-50/50`、进度槽 `bg-primary-100`、
 *    进度条 `bg-primary-500`、上传区悬停 `hover:border-primary-400`、上传中图标 `text-primary-500`。
 *
 * ⚠️ 未覆盖（如实登记）：`drop` 分支 —— jsdom 30 **不提供** `DataTransfer`
 * （实测 `typeof DataTransfer === 'undefined'`）⇒ 走不了 `fireEvent.drop`；
 * 只覆盖 `input[type=file]` 的 `change` 路径（两条路都汇入同一个 `handleFiles`）。
 */
import { describe, it, expect, vi, beforeEach, type Mock } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import React from 'react'

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

vi.mock('lucide-react', async (importOriginal) =>
  (await import('../helpers/lucide-mock')).lucideMock((await importOriginal()) as Record<string, unknown>))

vi.mock('next/image', () => ({
  default: (p: Record<string, unknown>) => React.createElement('img', p),
}))

vi.mock('@/lib/utils', () => ({
  cn: (...a: unknown[]) => a.filter(Boolean).join(' '),
  resolveImageUrl: (u: string) => u,
}))

const uploadFile = vi.fn()
// `deleteFile` 的返回值不参与本文件的任何判据（`handleRemove` 的清理是 silent best-effort），
// 但**实参形状照抄真实签名**（`(fileId: string, url?: string)`）—— 否则调用点会类型报错。
const deleteFile = vi.fn(async (_fileId: string, _url?: string) => ({ data: { data: {} } }))
vi.mock('@/lib/api', () => ({
  fileApi: {
    uploadFile: (file: unknown, directory?: unknown, onProgress?: unknown) =>
      uploadFile(file, directory, onProgress),
    deleteFile: (id: string, url?: string) => deleteFile(id, url),
  },
}))

import { toast } from 'sonner'
import FileUpload from '@/components/ui/FileUpload'
import type { UploadedFile } from '@/types'

const mockedUpload = uploadFile as Mock
const mockedDelete = deleteFile as Mock
const mockedToast = toast as unknown as { error: Mock; success: Mock }

/** 冷灰族：本仓没有 gray token ⇒ 任何一处都是漂移 */
const NEUTRAL_GRAY = /(?:bg|text|border|ring|from|via|to|divide|outline|shadow|decoration|accent|caret|fill|stroke)-(?:gray|slate|zinc|stone)-[0-9]/
/** 冷彩族：收口后本包内不许再出现（改前这里是 `blue-*`） */
const COOL_ACCENT = /(?:bg|text|border|ring|from|via|to|divide|outline|shadow|decoration|accent|caret|fill|stroke)-(?:blue|indigo|sky|violet|purple|cyan)-[0-9]/

function sourceColorClasses(): string[] {
  const src = readFileSync(resolve(__dirname, '../../../src/components/ui/FileUpload.tsx'), 'utf8')
  return src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\/\/[^\n]*/g, '')
    .match(/(?:bg|text|border|ring|from|via|to|divide|outline|shadow|decoration|accent|caret|fill|stroke)-[a-z]+-[0-9][0-9a-z/]*/g) ?? []
}

/** 造一个带指定体积的 File（`size` 是只读的，用 defineProperty 覆写） */
function makeFile(name: string, size: number, type = 'image/png'): File {
  const f = new File(['x'], name, { type })
  Object.defineProperty(f, 'size', { value: size })
  return f
}

function uploaded(over: Partial<UploadedFile> = {}): UploadedFile {
  return { id: 'u1', url: '/a.png', name: 'a.png', size: 512, type: 'image/png', ...over }
}

/** 上传区 = 有 `border-dashed` 的那个框；满了/上传中它可能整块不在 */
const DROP_ZONE = 'div[class*="border-dashed"]'
/** 上传中卡片 = 上传进度那一块（定位进度槽与进度条的锚点） */
const UPLOADING_CARD = 'div[class*="bg-primary-50/50"]'

function fileInput(container: HTMLElement): HTMLInputElement {
  return container.querySelector('input[type="file"]') as HTMLInputElement
}

describe('FileUpload（共享上传件，issue #7007）', () => {
  beforeEach(() => {
    mockedUpload.mockReset()
    mockedDelete.mockReset()
    mockedDelete.mockResolvedValue({ data: { data: {} } })
    mockedToast.error.mockReset()
  })

  it('label / hint 给了才渲染', () => {
    const { unmount } = render(React.createElement(FileUpload, {}))
    expect(screen.queryByText('商品主图')).toBeNull()
    expect(screen.queryByText('最多 5 张')).toBeNull()
    unmount()

    render(React.createElement(FileUpload, { label: '商品主图', hint: '最多 5 张' }))
    expect(screen.getByText('商品主图')).toBeInTheDocument()
    expect(screen.getByText('最多 5 张')).toBeInTheDocument()
  })

  it('未达上限 ⇒ 有上传区；multiple+maxFiles 达上限 ⇒ 整块上传区不渲染（满了不再显示入口）', () => {
    const { container, unmount } = render(
      React.createElement(FileUpload, { value: [uploaded()], multiple: true, maxFiles: 2 }),
    )
    // 1/2 未满 ⇒ 上传入口在（且没被 isUploading 之类误伤成 disabled）
    const zone = container.querySelector(DROP_ZONE) as HTMLElement
    expect(zone).toBeInTheDocument()
    expect(zone).toHaveTextContent('点击上传')
    unmount()

    const { container: full } = render(
      React.createElement(FileUpload, {
        value: [uploaded({ id: 'u1', name: 'a.png' }), uploaded({ id: 'u2', url: '/b.png', name: 'b.png' })],
        multiple: true,
        maxFiles: 2,
      }),
    )
    // 红证：把 `value.length < effectiveMax &&` 这个条件去掉 ⇒ 这里当场红（已满还挂着上传入口）
    expect(full.querySelector(DROP_ZONE)).toBeNull()
    expect(screen.queryByText('点击上传')).toBeNull()
    // 但文件列表仍在（「藏入口」不是「藏内容」）
    expect(screen.getByText('a.png')).toBeInTheDocument()
    expect(screen.getByText('b.png')).toBeInTheDocument()
  })

  it('单文件档（multiple 缺省）effectiveMax = 1：已有一个文件就不再显示上传区', () => {
    const { container } = render(React.createElement(FileUpload, { value: [uploaded()] }))
    // 红证：把 `effectiveMax = multiple ? maxFiles : 1` 改成 `= maxFiles`（缺省 1 也会过）
    // 或改成 `= multiple ? maxFiles : maxFiles`（多文件档的缺省 1 被放开）⇒ 这里当场红
    expect(container.querySelector(DROP_ZONE)).toBeNull()
  })

  it('已传文件列表：文件名 + formatSize 的人类可读体积（B / KB / MB 三档边界）', () => {
    const files: UploadedFile[] = [
      uploaded({ id: 'f1', url: '/1.bin', name: 'small.bin', size: 1023, type: 'application/octet-stream' }),
      uploaded({ id: 'f2', url: '/2.bin', name: 'kilo.bin', size: 1024, type: 'application/octet-stream' }),
      uploaded({ id: 'f3', url: '/3.bin', name: 'mega.bin', size: 1024 * 1024, type: 'application/octet-stream' }),
    ]
    render(React.createElement(FileUpload, { value: files, multiple: true, maxFiles: 3 }))

    expect(screen.getByText('small.bin')).toBeInTheDocument()
    expect(screen.getByText('kilo.bin')).toBeInTheDocument()
    expect(screen.getByText('mega.bin')).toBeInTheDocument()
    // 边界逐值：1023 B 不进 KB 档 / 1024 B = 1.0 KB / 1024*1024 B = 1.0 MB
    // 红证：把 `bytes < 1024` 改成 `bytes <= 1024` ⇒ 1023 仍过、但 1024 那条从 `1.0 KB` 变 `1024 B` ⇒ 当场红
    expect(screen.getByText('1023 B')).toBeInTheDocument()
    expect(screen.getByText('1.0 KB')).toBeInTheDocument()
    expect(screen.getByText('1.0 MB')).toBeInTheDocument()
  })

  it('超限文件 ⇒ 弹 toast.error 且不调上传接口', async () => {
    const { container } = render(React.createElement(FileUpload, { maxSize: 1 }))
    const big = makeFile('big.png', 2 * 1024 * 1024)
    fireEvent.change(fileInput(container), { target: { files: [big] } })

    await waitFor(() => expect(mockedToast.error).toHaveBeenCalledTimes(1))
    // 文案要带上文件名与限额（用户得知道是哪个文件、超了多少）
    expect(mockedToast.error.mock.calls[0][0]).toBe('big.png 超过 1MB 大小限制')
    // 红证：把 `return` 去掉（只提示不拦）⇒ 下一行当场红（文件已经发到服务端了）
    expect(mockedUpload).not.toHaveBeenCalled()
    // 也不该凭空多出一条上传中条目
    expect(container.querySelector(UPLOADING_CARD)).toBeNull()
  })

  it('上传中条目：进度条 style.width = `${progress}%`，上传卡/槽/条全用暖色 token', async () => {
    let report: ((p: number) => void) | undefined
    mockedUpload.mockImplementation((_f: unknown, _d: unknown, onProgress: unknown) => {
      report = onProgress as (p: number) => void
      return new Promise(() => {}) // 停在「上传中」，不落 success
    })

    const { container } = render(React.createElement(FileUpload, {}))
    fireEvent.change(fileInput(container), {
      target: { files: [makeFile('a.png', 100)] },
    })
    await waitFor(() => expect(mockedUpload).toHaveBeenCalledTimes(1))

    // 上传中：桶底 bg-primary-100（改前是 blue-*）
    const track = container.querySelector('div[class*="bg-primary-100"]') as HTMLElement
    expect(track).toBeInTheDocument()
    const bar = track.firstElementChild as HTMLElement
    expect(bar).toHaveClass('bg-primary-500')
    expect(bar.style.width).toBe('0%')

    act(() => report?.(42))
    // 红证：把 `style={{ width: `${file.progress}%` }}` 写死（或漏传 progress）⇒ 当场红
    await waitFor(() => expect(bar.style.width).toBe('42%'))
    expect(screen.getByText('42%')).toBeInTheDocument()

    // 上传中卡片 = 暖色描边 + 暖色底（改前 border-blue-200 bg-blue-50/50）
    const card = container.querySelector(UPLOADING_CARD) as HTMLElement
    expect(card).toBeInTheDocument()
    expect(container.querySelector('svg[class*="text-primary-500"]')).toBeInTheDocument()
  })

  it('上传失败 ⇒ 进度条转 bg-red-500（不是继续显示暖色进度）', async () => {
    mockedUpload.mockRejectedValue(new Error('boom'))
    const { container } = render(React.createElement(FileUpload, {}))
    fireEvent.change(fileInput(container), { target: { files: [makeFile('a.png', 100)] } })

    await waitFor(() => expect(mockedToast.error).toHaveBeenCalled())
    // 红证：把 `file.status === 'error' ? 'bg-red-500' : 'bg-primary-500'` 写成恒 `bg-primary-500`
    // ⇒ 这里当场红（失败态与成功态在屏幕上读不出来）
    await waitFor(() => {
      expect(container.querySelector('div[class*="bg-primary-100"] div[class*="bg-red-500"]')).toBeInTheDocument()
    })
    // 失败不改变「上限口径」：入口仍要能重试（不能因为失败把上传区吃掉）
    expect(container.querySelector(DROP_ZONE)).toBeInTheDocument()
    expect(mockedToast.error.mock.calls[0][0]).toBe('a.png 上传失败')
  })

  it('上传区：accept 透传到 input，multiple 由 `multiple && effectiveMax > 1` 决定', () => {
    const { container, unmount } = render(React.createElement(FileUpload, { accept: 'image/png' }))
    expect(fileInput(container)).toHaveAttribute('accept', 'image/png')
    // 缺省 multiple=false ⇒ 单文件档，input 不带 multiple
    expect(fileInput(container)).not.toHaveAttribute('multiple')
    unmount()

    const { container: multi } = render(
      React.createElement(FileUpload, { multiple: true, maxFiles: 3 }),
    )
    expect(fileInput(multi)).toHaveAttribute('multiple')
  })

  it('暖色收口：上传区悬停 = hover:border-primary-400，渲染面与源码都不得出现冷灰/冷彩族', () => {
    const { container } = render(React.createElement(FileUpload, {}))
    const zone = container.querySelector(DROP_ZONE) as HTMLElement
    expect(zone).toHaveClass('border-neutral-300')
    // 红证：改回 `hover:border-blue-400` ⇒ 当场红
    expect(zone).toHaveClass('hover:border-primary-400')
    expect(screen.getByText('点击上传')).toHaveClass('text-primary-600')

    const rendered = Array.from(container.querySelectorAll('*'))
      .map((el) => el.getAttribute('class') ?? '')
      .join(' ')
    expect(rendered).not.toMatch(NEUTRAL_GRAY)
    expect(rendered).not.toMatch(COOL_ACCENT)

    const classes = sourceColorClasses()
    expect(classes.length).toBeGreaterThan(0)
    const offenders = classes.filter((c) => NEUTRAL_GRAY.test(c) || COOL_ACCENT.test(c))
    // 红证：任一 class 改回 `bg-blue-50` / `text-gray-500`（改前实测该文件 17 处冷灰）⇒ offenders 非空
    expect(offenders).toEqual([])
    // 暖色 token 必须在位（不是「删光 class」也能过的空集绿）
    for (const token of ['border-primary-200', 'bg-primary-50/50', 'bg-primary-500', 'bg-primary-100', 'border-primary-400', 'text-primary-500']) {
      expect(classes).toContain(token)
    }
  })
})
