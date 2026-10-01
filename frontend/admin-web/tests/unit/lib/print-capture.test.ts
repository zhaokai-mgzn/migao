// case_ids: UI-026
// @vitest-environment jsdom

import { describe, it, expect, vi, afterEach } from 'vitest'

import { captureNodeToPngBlob, copyPngToClipboard, downloadPng } from '@/lib/print-capture'

/**
 * 单据**截图**（issue #5914 功能④：点「复制截图」把单据按真尺寸写进剪贴板）。
 *
 * jsdom 里没有排版、没有 canvas、没有 `foreignObject` 渲染 ⇒ **成品 PNG 的几何判据在
 * 真实浏览器侧**（`tests/e2e/specs/orders/print-preview.spec.ts` 的「④ 复制截图」按
 * `createImageBitmap` 读尺寸 + 像素覆盖率）。这里判的是它的**失败面**：
 * 尺寸为 0 时必须**出声**、剪贴板不可用时必须**如实返回 false**（交给调用方降级下载）、
 * 下载出口必须真的产出一个带文件名的 `<a>`。三条都是「不许静默失败」。
 */
describe('单据截图 print-capture（issue #5914）', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('① 节点没有尺寸（没渲染出来）⇒ 抛出可行动的错误，绝不导出一张空图', async () => {
    const node = document.createElement('div')
    await expect(captureNodeToPngBlob(node)).rejects.toThrow(/尺寸为 0/)
  })

  it('② 剪贴板不可用 ⇒ 返回 false（调用方据此降级下载），不把异常抛出去', async () => {
    // jsdom 没有 ClipboardItem ⇒ 走「浏览器不支持」这条分支
    expect(typeof ClipboardItem).toBe('undefined')
    await expect(copyPngToClipboard(new Blob())).resolves.toBe(false)

    // 有 ClipboardItem 但写入被拒（权限 / 非安全上下文）⇒ 仍然是 false，不抛
    class FakeClipboardItem {
      constructor(public readonly items: Record<string, Blob>) {}
    }
    vi.stubGlobal('ClipboardItem', FakeClipboardItem)
    const write = vi.fn().mockRejectedValue(new Error('NotAllowedError'))
    Object.defineProperty(navigator, 'clipboard', { value: { write }, configurable: true })
    await expect(copyPngToClipboard(new Blob())).resolves.toBe(false)
    expect(write).toHaveBeenCalledTimes(1)
  })

  it('③ 降级下载：产出一个带文件名的 <a download> 并点击，objectURL **异步**释放', async () => {
    const createObjectURL = vi.fn(() => 'blob:mock-url')
    const revokeObjectURL = vi.fn()
    const url = URL as unknown as Record<string, unknown>
    const savedCreate = url.createObjectURL
    const savedRevoke = url.revokeObjectURL
    url.createObjectURL = createObjectURL
    url.revokeObjectURL = revokeObjectURL

    const clicked: string[] = []
    const createElement = document.createElement.bind(document)
    vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      const el = createElement(tag)
      if (tag === 'a') (el as HTMLAnchorElement).click = () => clicked.push((el as HTMLAnchorElement).download)
      return el
    })

    try {
      downloadPng(new Blob(['x'], { type: 'image/png' }), '销售单.png')

      expect(clicked).toEqual(['销售单.png'])
      expect(createObjectURL).toHaveBeenCalledTimes(1)
      // 🔴 同步路径**不许**释放：部分浏览器还没取到流就被 revoke 会得到一张空文件
      expect(revokeObjectURL).not.toHaveBeenCalled()

      // 而是**下一轮事件循环**释放（这条同时保证不会一直占着 blob）
      await new Promise((resolve) => setTimeout(resolve, 0))
      expect(revokeObjectURL).toHaveBeenCalledWith('blob:mock-url')
    } finally {
      url.createObjectURL = savedCreate
      url.revokeObjectURL = savedRevoke
    }
  })
})
