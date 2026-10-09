/**
 * H5 **浏览器录音**适配层（issue #6596）
 *
 * ## 为什么要有它
 *
 * 用户 2026-10-09 裁定 B 端输入条「**默认按住说话**，语音和键盘 icon 可以切换」——
 * 而这条腿跑在 H5（iOS 微信 webview / Safari / Chrome）。旧实现里 H5 的
 * `Taro.getRecorderManager()` 是 stub（`temporarilyNotSupport`）⇒ issue #6476 的结论是
 * 「H5 不许写『按住说话』」。⇒ 要么**把 H5 录音做出来**，要么那句承诺就是空的（#5650 的教训）。
 *
 * 本文件用**浏览器原生** `getUserMedia` + `MediaRecorder` 做出录音 + 交回 **blob URL**
 * （`stopRecording()` 的既有契约就是「交回一个能被上传的临时路径」，weapp 交 `tempFilePath`）。
 * 后端 `POST /api/chat/transcribe` 已支持 `webm/opus` 与 `mp4`（`app/api/asr.py` 的
 * `_get_audio_format` / `_convert_to_wav`）⇒ **不改后端**。
 *
 * ## 边界（照实登记，§19.1）
 *
 * - **安全上下文**：`getUserMedia` 只在 HTTPS / localhost 可用（生产 `app.migaozn.com` 是 HTTPS）。
 *   纯 HTTP 下浏览器不给 ⇒ `isVoiceSupported()` 为假 ⇒ 回落文字模式（不摆按不动的键）。
 * - **授权时机**：麦克风权限只在**按下**时请求（不在页面加载时弹窗）。用户拒绝 ⇒
 *   {@link MIC_DENIED_MESSAGE} 那道**可行动**的错误（说清「去哪开 + 还能怎么办」），
 *   由输入条 toast 出来；**不静默失败**。
 * - **mime 选择器**：优先 `audio/webm;codecs=opus`（体积小、后端 `_convert_to_wav` 走 ffmpeg），
 *   退化到浏览器 `isTypeSupported` 里第一个可用的；Safari 给的是 `audio/mp4`。两者后端都认。
 * - 本文件只负责「录出可上传的 blob URL」；**上传**与格式解析仍在 `utils/voice.ts`（单一上传点）。
 */

/** MediaRecorder 实例的最小面（jsdom 里没有它 ⇒ 必须自己声明，且不许在模块顶层碰全局） */
interface RecorderLike {
  mimeType?: string
  state?: string
  ondataavailable: ((event: { data: Blob }) => void) | null
  onstop: (() => void) | null
  onerror: ((event: unknown) => void) | null
  start(): void
  stop(): void
}

/** 一次录音会话（`startRecording` 起、`stopRecording` 收） */
export interface BrowserRecording {
  /** 录音器已就绪（`MediaRecorder.start()` 已调）；**用户可能在授权弹窗还没点就先松手** ⇒ 先 await 再收 */
  ready: Promise<void>
  /** 停止并 resolve 出可上传的 **blob URL**；交不出（权限被拒 / 空录音）时 reject */
  stop: () => Promise<string>
}

/**
 * 🔴 方向 ① 的**审计**（技术债台账；**只许缩短、不许加**）
 *
 * （`docs/wiki/Development.md` 的 AI-TDD 流程要求：凡「pivot」必须留审计行 —— 本文件正是
 * 「#6476 判定 H5 无录音」→「#6596 判定 H5 有录音」的那次 pivot 的落点。）
 *
 * | # | 原判断（#6476 / #5650） | 现判断（#6596） | 依据 |
 * |---|---|---|---|
 * | 1 | H5 `getRecorderManager` 是 stub ⇒ 无录音 | H5 **有**录音：`getUserMedia` + `MediaRecorder` | 浏览器标准 API；后端已支持 webm/mp4（`app/api/asr.py`） |
 * | 2 | 故 H5 不许出现「按住说话」（空承诺） | **只有**浏览器确实没有这两个 API 时才不许 | `isVoiceSupported()` 现取运行时能力（`supportsBrowserRecording`） |
 */

/** 浏览器是否具备录音能力（**现取运行时**：不缓存 —— 见 `tests/voice-browser-recorder.test.ts` 判据 1） */
export function supportsBrowserRecording(): boolean {
  const MR = (globalThis as { MediaRecorder?: unknown }).MediaRecorder
  const devices = (globalThis as { navigator?: { mediaDevices?: { getUserMedia?: unknown } } })
    .navigator?.mediaDevices
  return typeof MR === 'function' && typeof devices?.getUserMedia === 'function'
}

/** 权限被拒 / 没有麦克风时的**可行动**文案（不静默、不留「点了没反应」） */
export const MIC_DENIED_MESSAGE = '没有麦克风权限：请在浏览器设置里允许后重试，也可以直接用文字发送'
export const MIC_UNAVAILABLE_MESSAGE = '没有找到可用的麦克风：请检查设备后用文字发送'

function describeMicError(error: unknown): Error {
  const name = (error as { name?: string } | null)?.name
  if (name === 'NotAllowedError' || name === 'SecurityError') return new Error(MIC_DENIED_MESSAGE)
  return new Error(MIC_UNAVAILABLE_MESSAGE)
}

/** 优先 webm/opus（体积小；后端走 ffmpeg 转 wav），退化到浏览器支持的第一个容器 */
function pickMimeType(): string | undefined {
  const MR = (globalThis as { MediaRecorder?: { isTypeSupported?: (m: string) => boolean } })
    .MediaRecorder
  const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4']
  if (typeof MR?.isTypeSupported === 'function') {
    return candidates.find((mime) => MR.isTypeSupported?.(mime))
  }
  return undefined
}

/**
 * 开始一次浏览器录音。不支持时返回 `null`（调用方据此回落文字模式 —— **不摆按不动的键**）。
 *
 * 注意：**同步**返回会话对象（`startRecording()` 的调用方在 `touchStart` 里，不能 await）；
 * 麦克风请求挂在 `ready` 上，`stop()` 会先 await 它 —— 因此「按住就松手」也不会漏掉录音结束。
 */
export function startBrowserRecording(): BrowserRecording | null {
  if (!supportsBrowserRecording()) return null

  const MR = (globalThis as { MediaRecorder: new (stream: unknown, opts?: { mimeType?: string }) => RecorderLike })
    .MediaRecorder
  const chunks: Blob[] = []
  let recorder: RecorderLike | null = null
  let failed: Error | null = null

  const ready = (async () => {
    let stream: unknown
    try {
      stream = await (
        globalThis.navigator as { mediaDevices: { getUserMedia: (c: unknown) => Promise<unknown> } }
      ).mediaDevices.getUserMedia({ audio: true })
    } catch (error) {
      failed = describeMicError(error)
      throw failed
    }
    const mimeType = pickMimeType()
    recorder = new MR(stream, mimeType ? { mimeType } : undefined)
    recorder.ondataavailable = (event) => {
      if (event.data) chunks.push(event.data)
    }
    recorder.onerror = () => {
      failed = new Error('录音失败，请重试')
    }
    recorder.start()
  })()

  const stop = async (): Promise<string> => {
    // 授权弹窗可能还没点，用户就先松手 ⇒ 先等录音器就绪
    await ready
    const active = recorder
    if (!active || failed) throw failed ?? new Error('录音未开始')
    return await new Promise<string>((resolve, reject) => {
      active.onstop = () => {
        try {
          ;(active as unknown as { stream?: { getTracks?: () => { stop: () => void }[] } }).stream
            ?.getTracks?.()
            .forEach((track) => track.stop())
        } catch {
          // 释放麦克风失败不影响转写（用户已经松开）
        }
        if (failed) {
          reject(failed)
          return
        }
        if (chunks.length === 0) {
          reject(new Error('未检测到声音，已取消转写'))
          return
        }
        const type = active.mimeType || chunks[0].type || 'audio/webm'
        const blob = new Blob(chunks, { type })
        if (typeof URL.createObjectURL !== 'function') {
          reject(new Error('当前浏览器不支持本地录音回放，请用文字发送'))
          return
        }
        resolve(URL.createObjectURL(blob))
      }
      active.stop()
    })
  }

  return { ready, stop }
}
