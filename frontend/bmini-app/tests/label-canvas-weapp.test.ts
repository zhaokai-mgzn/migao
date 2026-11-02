// case_ids: BM-060
/**
 * **小程序画布工厂**（issue #8287）：无 DOM 时标签也能画出位图。
 *
 * ## 为什么这条必须单独有判据
 *
 * #7802 / #7803 把**通道**（微信原生 BLE）接好了，能力探测也说 `weapp` 可用 ——
 * 但渲染层仍要求 DOM canvas（`labelPageKit.createH5CanvasFactory` 在无 DOM 时直接抛错）。
 * 结果：小程序里按钮是亮的、真点却「标签图没画出来」⇒ **打印通道等于没接**。
 * 本文件钉住：小程序走 `Taro.createOffscreenCanvas` 并真的产出位图；h5 / 终端仍走 DOM canvas。
 *
 * | # | 判据 | 红证（怎么让它单独变红） |
 * |---|---|---|
 * | W8 | 无 DOM + `TARO_ENV=weapp` ⇒ 调用 `Taro.createOffscreenCanvas({type:'2d',width,height})` | 删掉离屏分支 / 仍只认 document ⇒ 红（工厂抛错） |
 * | W9 | 离屏画布必须能取到 `getImageData`（取不到 ⇒ `renderRowsLabel` 抛错，不静默打白图） | 去掉 `requirePixels` ⇒ 红 |
 * | W10 | 有 DOM ⇒ **不**调用离屏画布（h5 / 手持终端的 WebView 仍走 DOM canvas） | 把离屏分支提到 DOM 分支之前 ⇒ 红 |
 */
import fs from 'fs'
import path from 'path'

jest.mock('@tarojs/taro', () => {
  const ctx = {
    fillStyle: '',
    font: '',
    textBaseline: '',
    fillRect: jest.fn(),
    fillText: jest.fn(),
    getImageData: jest.fn((x: number, y: number, width: number, height: number) => ({
      data: new Uint8ClampedArray(width * height * 4),
      width,
      height,
    })),
  }
  return {
    __esModule: true,
    default: {
      createOffscreenCanvas: jest.fn((options: { type: string; width: number; height: number }) => ({
        width: options.width,
        height: options.height,
        getContext: () => ctx,
      })),
    },
  }
})

import Taro from '@tarojs/taro'
import { createH5CanvasFactory } from '../src/utils/inbound/labelPageKit'
import { renderRowsLabel } from '../src/utils/labels/rowsLabel'
import { labelGeometry } from '../src/utils/inbound/truth'
import { SHIP_LABEL_MEDIA_ID } from '../src/utils/inbound/truth'

const mockOffscreen = (Taro as any).createOffscreenCanvas as jest.Mock
const DOC_DESCRIPTOR = Object.getOwnPropertyDescriptor(global, 'document')
const ORIGINAL_ENV = process.env.TARO_ENV

function withoutDom(): void {
  Object.defineProperty(global, 'document', {
    value: undefined,
    configurable: true,
    writable: true,
  })
}

function restoreDom(): void {
  if (DOC_DESCRIPTOR) Object.defineProperty(global, 'document', DOC_DESCRIPTOR)
}

describe('小程序画布工厂（issue #8287）', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    process.env.TARO_ENV = 'weapp'
  })

  afterEach(() => {
    restoreDom()
    process.env.TARO_ENV = ORIGINAL_ENV
  })

  it('W8 无 DOM ⇒ 用离屏画布，且尺寸 = 版面计划（能产出台图）', () => {
    withoutDom()
    const geometry = labelGeometry(SHIP_LABEL_MEDIA_ID)
    const label = renderRowsLabel(
      { rows: [{ key: 'name', label: '品名', value: '遮光布' }], fixedLengthMm: 70, shortCode: 'ABCD2345' },
      createH5CanvasFactory(),
    )

    expect(mockOffscreen).toHaveBeenCalledTimes(1)
    const options = mockOffscreen.mock.calls[0][0]
    expect(options.type).toBe('2d')
    expect(options.width).toBe(geometry.canvasWidthPx)
    expect(label.widthPx).toBe(options.width)
    expect(label.heightPx).toBe(options.height)
    // 位图真的取到了（不是空白占位：白图会被当成「打出来了」）
    expect(label.image.width).toBe(label.widthPx)
    expect(label.image.height).toBe(label.heightPx)
    expect(label.image.data.length).toBe(label.widthPx * label.heightPx * 4)
  })

  it('W9 离屏画布取不到位图 ⇒ 渲染抛错（不静默打白图）', () => {
    withoutDom()
    // 这一次让离屏画布的 ctx 没有 getImageData
    mockOffscreen.mockImplementationOnce((options: { width: number; height: number }) => ({
      width: options.width,
      height: options.height,
      getContext: () => ({
        fillStyle: '',
        font: '',
        textBaseline: '',
        fillRect: jest.fn(),
        fillText: jest.fn(),
      }),
    }))
    expect(() =>
      renderRowsLabel(
        { rows: [{ key: 'name', label: '品名', value: '遮光布' }], fixedLengthMm: 70 },
        createH5CanvasFactory(),
      ),
    ).toThrow(/取不到位图/)
  })

  it('W10 有 DOM ⇒ 不调用离屏画布（h5 / 终端 WebView 仍走 DOM canvas）', () => {
    const factory = createH5CanvasFactory()
    const canvas = factory(40, 80)
    expect(canvas.width).toBe(40)
    expect(canvas.height).toBe(80)
    expect(mockOffscreen).not.toHaveBeenCalled()
  })

  it('W10 源码：离屏分支在 DOM 分支之后，且无画布时显式抛错', () => {
    const src = fs.readFileSync(path.resolve(__dirname, '../src/utils/inbound/labelPageKit.ts'), 'utf8')
    const body = src.slice(src.indexOf('export function createH5CanvasFactory'))
    expect(body).toContain('Taro.createOffscreenCanvas')
    expect(body).toContain('isWeapp()')
    expect(body.indexOf('Taro.createOffscreenCanvas')).toBeGreaterThan(
      body.indexOf("typeof document === 'undefined'"),
    )
    expect(body).toMatch(/throw new Error\(['"]当前平台没有可用画布/)
  })
})
