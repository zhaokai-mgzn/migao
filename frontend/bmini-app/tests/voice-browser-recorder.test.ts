// case_ids: BM-044
/**
 * B 端 H5 **浏览器录音链路**判据（issue #6596）
 *
 * ## 为什么有这一份（而不是只靠 `isVoiceSupported` 的能力探测）
 *
 * 用户 2026-10-09 裁定「默认按住说话」——而 issue #6476 当时的结论是「H5 没有录音实现，
 * 所以不许写『按住说话』」。本单把 H5 录音**真做出来**（`getUserMedia` + `MediaRecorder`），
 * 那就不该只有一个「入口在不在」的布尔判据：录音**链路本身**（mime 选择 / blob 交回 / 权限拒绝）
 * 必须各有一条会红的判据，否则「能按」= 空按钮，正是 #5650 的病灶换了个形态回来。
 *
 * ## 判据
 *
 * | # | 断言 | 回归时会怎么红 |
 * |---|---|---|
 * | 1 | 能力探测**不假绿**：无 `MediaRecorder` / 无 `getUserMedia` ⇒ `isVoiceSupported()` 为假 | 探测恒真（H5 摆出按不动的键）⇒ 红 |
 * | 2 | 有两者 ⇒ 为真；`startRecording()` 真调 `getUserMedia({audio:true})` + `MediaRecorder.start()` | 只探测不接线（按了没录）⇒ 红 |
 * | 3 | `stopRecording()` 交回**可上传的 blob URL**，扩展名与 mime 匹配（webm / mp4 —— 后端 `_get_audio_format` 按这两族解析） | 交回空串 / 扩展名与容器不符（后端认不出格式）⇒ 红 |
 * | 4 | 🔴 麦克风**拒绝授权** ⇒ 抛出**可行动**的错误（说清「去哪开 + 还能怎么办」），不是静默失败 | 静默 resolve（用户以为在录）⇒ 红 |
 *
 * ## 边界（照实登记）
 *
 * - jsdom 里没有真录音设备 ⇒ 本文件注入**最小 MediaRecorder / getUserMedia 桩**
 *   （只实现链路用到的那几个成员）。它证明的是「接线对了」，不是「真机录出的音频能被 DashScope 转写」
 *   —— 后者需要真机读数（PR body 的未覆盖登记）。
 * - 上传那一段（`transcribeFile`）**有意不在这里判**：它要求 `Taro.uploadFile` / `fetch`
 *   与鉴权头，属另一条腿；本文件只到「交回的 blob URL 长什么样」为止。
 */
import { isVoiceSupported, startRecording, stopRecording } from '../src/utils/voice'

/** 最小 MediaRecorder 桩：只实现链路用到的那几个成员 */
class FakeMediaRecorder {
  static instances: FakeMediaRecorder[] = []
  static isTypeSupported = (mime: string) => mime.includes('webm') || mime.includes('mp4')
  mimeType: string
  state = 'inactive'
  ondataavailable: ((e: any) => void) | null = null
  onstop: (() => void) | null = null
  onerror: ((e: any) => void) | null = null
  constructor(_stream: any, opts?: { mimeType?: string }) {
    this.mimeType = opts?.mimeType ?? ''
    FakeMediaRecorder.instances.push(this)
  }
  start() {
    this.state = 'recording'
  }
  stop() {
    this.state = 'inactive'
    this.ondataavailable?.({ data: new Blob(['audio-bytes'], { type: this.mimeType }) })
    this.onstop?.()
  }
}

const gum = jest.fn(async () => ({ getTracks: () => [{ stop: jest.fn() }] }))
const originalMediaRecorder = (globalThis as any).MediaRecorder
const originalCreateObjectURL = (URL as any).createObjectURL

function installRecorder() {
  ;(globalThis as any).MediaRecorder = FakeMediaRecorder
  Object.defineProperty(globalThis.navigator, 'mediaDevices', {
    value: { getUserMedia: gum },
    configurable: true,
  })
  ;(URL as any).createObjectURL = jest.fn(() => 'blob:bmini-voice')
}

function removeRecorder() {
  delete (globalThis as any).MediaRecorder
  Object.defineProperty(globalThis.navigator, 'mediaDevices', {
    value: undefined,
    configurable: true,
  })
}

beforeEach(() => {
  jest.clearAllMocks()
  FakeMediaRecorder.instances = []
  // 本文件判的是 **h5 分支**（`getRecorder()` 在 h5 直接 return null ⇒ 走浏览器录音）。
  // 不设它的话会落到「非 h5」分支去碰 `Taro.getRecorderManager()` 的 mock，判据就测错了对象。
  process.env.TARO_ENV = 'h5'
})

afterEach(() => {
  ;(process.env as Record<string, string | undefined>).TARO_ENV = undefined
  if (originalMediaRecorder === undefined) delete (globalThis as any).MediaRecorder
  else (globalThis as any).MediaRecorder = originalMediaRecorder
  ;(URL as any).createObjectURL = originalCreateObjectURL
  removeRecorder()
})

describe('B 端 H5 浏览器录音链路（issue #6596）', () => {
  it('能力探测不假绿：缺 MediaRecorder 或缺 getUserMedia ⇒ 不支持', () => {
    removeRecorder()
    expect(isVoiceSupported()).toBe(false)

    // 只有 MediaRecorder、没有 getUserMedia：仍然不支持（半条链路 = 按不动的键）
    ;(globalThis as any).MediaRecorder = FakeMediaRecorder
    expect(isVoiceSupported()).toBe(false)

    installRecorder()
    expect(isVoiceSupported()).toBe(true)
  })

  it('startRecording 真接线：请求麦克风 + 开录（不是只探测）', async () => {
    installRecorder()
    startRecording()
    await Promise.resolve()
    expect(gum).toHaveBeenCalledWith({ audio: true })
    expect(FakeMediaRecorder.instances).toHaveLength(1)
    expect(FakeMediaRecorder.instances[0].state).toBe('recording')
  })

  it('stopRecording 交回可上传的 blob URL（mime → 后端认得的扩展名）', async () => {
    installRecorder()
    startRecording()
    const path = await stopRecording()
    expect(path).toBe('blob:bmini-voice')
    expect((URL as any).createObjectURL).toHaveBeenCalledTimes(1)
  })

  it('🔴 麦克风被拒绝 ⇒ 抛出可行动的错误（说清去哪开 + 还能怎么办）', async () => {
    installRecorder()
    gum.mockRejectedValueOnce(
      Object.assign(new Error('Permission denied'), { name: 'NotAllowedError' }),
    )
    startRecording()
    await expect(stopRecording()).rejects.toThrow(/麦克风权限/)
  })
})
