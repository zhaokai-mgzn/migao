// case_ids: ST-001
import { describe, it, expect, vi, afterEach } from 'vitest'
import { readImageDimensions } from '@/lib/image-dimensions'

/**
 * readImageDimensions 单元测试
 * 用可控的全局 Image 模拟浏览器图片解码，验证自然尺寸读取与错误兜底。
 */
class FakeImage {
  naturalWidth = 0
  naturalHeight = 0
  onload: (() => void) | null = null
  onerror: (() => void) | null = null
  src = ''
}

function installFakeImage(dims: { width: number; height: number } | 'error') {
  const Fake = FakeImage as any
  vi.stubGlobal('Image', class extends Fake {
    set src(_v: string) {
      // 模拟解码：异步触发 onload / onerror
      queueMicrotask(() => {
        if (dims === 'error') {
          this.onerror?.()
        } else {
          this.naturalWidth = dims.width
          this.naturalHeight = dims.height
          this.onload?.()
        }
      })
    }
  })
  // jsdom 环境无 createObjectURL，补一个 no-op stub
  vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:fake'), revokeObjectURL: vi.fn() })
}

describe('readImageDimensions', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('返回图片自然尺寸', async () => {
    installFakeImage({ width: 512, height: 256 })
    const dims = await readImageDimensions(new File(['x'], 'logo.png', { type: 'image/png' }))
    expect(dims).toEqual({ width: 512, height: 256 })
  })

  it('解码失败时 reject', async () => {
    installFakeImage('error')
    await expect(readImageDimensions(new File(['x'], 'broken.png', { type: 'image/png' })))
      .rejects.toThrow()
  })
})
