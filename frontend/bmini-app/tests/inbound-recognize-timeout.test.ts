// case_ids: BM-062
/**
 * 拍照入库识别链：**三步各自封顶 + 分步进度**（issue #8307）。
 *
 * 真机（商米 V2s / WebView 83，终端壳 1.0.17 与 1.0.19）取证 2/2：点「识别」后按钮**永久置灰**，
 * 5s / 10s / 20s / 45s / 60s 截图逐字节相同、CPU 0.0%。页面 `onRecognize` 的 `finally` 只要走到
 * 就会恢复按钮 ⇒ 不恢复 = 某个 await **永不 settle**。因此判据不是「跑得快」，而是：
 * ① 三步（读图 / 上传 / 识别）各自有上限；② 超时后按钮必须恢复、进度必须清空；
 * ③ 识别中必须有可见进度（否则工人只看到灰按钮，分不清「在跑」和「卡死」）。
 *
 * 判据 1~3 走**页面接线**这一层（读源码断言线上真有这三处接线）：`withTimeout` 工具本身由上面
 * 四条单测覆盖；接线被摘掉时这里点名判红，而不是靠人记得。
 */
import { readFileSync } from 'fs'
import { join } from 'path'
import {
  INBOUND_DECODE_TIMEOUT_HINT,
  INBOUND_DECODE_TIMEOUT_MS,
  INBOUND_PROGRESS_DECODE,
  INBOUND_PROGRESS_RECOGNIZE,
  INBOUND_PROGRESS_UPLOAD,
  INBOUND_RECOGNIZE_TIMEOUT_HINT,
  INBOUND_RECOGNIZE_TIMEOUT_MS,
  INBOUND_UPLOAD_TIMEOUT_HINT,
  INBOUND_UPLOAD_TIMEOUT_MS,
  withTimeout,
} from '../src/utils/inbound/withTimeout'

const read = (rel: string) => readFileSync(join(__dirname, '..', rel), 'utf8')

const PAGE = read('src/pages/worker/inbound/index.tsx')

describe('withTimeout（上限本身）', () => {
  it('有结果 ⇒ 原样透传，不额外等待', async () => {
    await expect(withTimeout(Promise.resolve('ok'), 1000, '不该超时')).resolves.toBe('ok')
  })

  it('超时 ⇒ 用**点名那一步**的人话 reject', async () => {
    const never = new Promise<string>(() => {})
    await expect(withTimeout(never, 5, INBOUND_UPLOAD_TIMEOUT_HINT)).rejects.toThrow('照片上传超时')
  })

  it('底层自己报错 ⇒ 原样透传（不许被改写成超时文案）', async () => {
    await expect(withTimeout(Promise.reject(new Error('网络断开')), 1000, '不该超时')).rejects.toThrow('网络断开')
  })

  it('按时返回后定时器被清掉（不会在之后再来一发超时）', async () => {
    jest.useFakeTimers()
    try {
      const task = withTimeout(Promise.resolve(1), 20_000, '不该超时')
      jest.advanceTimersByTime(19_999)
      await expect(task).resolves.toBe(1)
      expect(jest.getTimerCount()).toBe(0)
    } finally {
      jest.useRealTimers()
    }
  })

  it('三步的上限是各自独立的（读图 < 上传 < 识别）', () => {
    expect(INBOUND_DECODE_TIMEOUT_MS).toBeLessThan(INBOUND_UPLOAD_TIMEOUT_MS)
    expect(INBOUND_UPLOAD_TIMEOUT_MS).toBeLessThan(INBOUND_RECOGNIZE_TIMEOUT_MS)
    expect(INBOUND_DECODE_TIMEOUT_HINT).toContain('读取超时')
    expect(INBOUND_RECOGNIZE_TIMEOUT_HINT).toContain('识别超时')
  })
})

describe('页面接线（判据 1~3）', () => {
  it('判据 1·三步各自 withTimeout，且各自的上限常量为参', () => {
    expect(PAGE).toMatch(/withTimeout\(\s*decodeBarcodeFromPhoto\(photo\),\s*INBOUND_DECODE_TIMEOUT_MS/)
    expect(PAGE).toMatch(/withTimeout\(\s*uploadInboundPhoto\(/)
    expect(PAGE).toMatch(/INBOUND_UPLOAD_TIMEOUT_MS/)
    expect(PAGE).toMatch(/withTimeout\(\s*recognizeInbound\(payload\),\s*INBOUND_RECOGNIZE_TIMEOUT_MS/)
  })

  it('判据 2·超时后按钮恢复：finally 里 busy=false 且 progress 清空', () => {
    expect(PAGE).toMatch(/finally\s*\{\s*setBusy\(false\)\s*setProgress\(''\)/)
  })

  it('判据 3·识别中要有可见进度（busy 且 progress 非空才渲染）', () => {
    expect(PAGE).toContain("import {\n  INBOUND_DECODE_TIMEOUT_HINT")
    expect(PAGE).toContain("data-testid='inbound-progress'")
    expect(PAGE).toContain('{busy && progress !== \'\'')
    expect(PAGE).toContain('INBOUND_PROGRESS_DECODE')
    expect(PAGE).toContain('INBOUND_PROGRESS_UPLOAD')
    expect(PAGE).toContain('INBOUND_PROGRESS_RECOGNIZE')
    expect([INBOUND_PROGRESS_DECODE, INBOUND_PROGRESS_UPLOAD, INBOUND_PROGRESS_RECOGNIZE]).toEqual([
      '正在读取照片…',
      '正在上传照片…',
      '正在识别标签…',
    ])
  })
})

describe('正式版文案：不许把型号 / 品牌 / 选机指令丢给用户', () => {
  const COPY_FILES = [
    'src/utils/inbound/printCapability.ts',
    'src/utils/inbound/printerLink.ts',
    'src/pages/worker/inbound/index.tsx',
    'src/pages/worker/reprint/index.tsx',
  ]

  it.each(COPY_FILES)('%s 不出现 DP235S / 「DP 开头」/ 德佟', (rel) => {
    const src = read(rel)
    expect(src).not.toMatch(/DP235S/)
    expect(src).not.toMatch(/DP 开头/)
    expect(src).not.toMatch(/德佟/)
  })
})
