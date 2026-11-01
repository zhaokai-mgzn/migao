// case_ids: BM-063
/**
 * 上传照片：h5 走 **Blob 直传**，不再依赖 `Taro.uploadFile`（issue #8307）。
 *
 * 真机取证（商米 V2s / WebView 83）：点「识别」后 3s 就显示「正在上传照片…」，24s 后超时
 * —— 卡点在上传。读码得因：`@tarojs/taro-h5` 的 `uploadFile` 对 `filePath` 一律先做
 * `convertObjectUrlToBlob()`，里面是**只有 `onload` 的裸 XHR**（无 `onerror` / `ontimeout` / `onabort`）
 * ⇒ 不回调时 promise 永不 settle。
 *
 * 判据（都会红）：
 * ① 给了 Blob ⇒ 用 `FormData`（字段名 `files`）直传，**一次都不碰** `Taro.uploadFile`；
 *   红证：把 `uploadInboundPhotoSmart` 改回走 `Taro.uploadFile`，且把该 mock 设成永不返回 ⇒ 本文件超时红。
 * ② 只有 `blob:` 串 ⇒ 先 `fetch` 读成 Blob 再直传；
 * ③ 读不到 Blob（fetch 失败）⇒ 回落 `Taro.uploadFile`（不静默失败）；
 * ④ 响应归一化仍是服务端的 `data[0].url` 形状（与服务端 `ApiResponse<List<UploadedFileInfo>>` 同口径）。
 */
import Taro from '@tarojs/taro'
import {
  resolvePhotoBlob,
  uploadInboundPhotoBlob,
  uploadInboundPhotoSmart,
} from '../src/services/workerInboundService'

const OK_BODY = JSON.stringify({ success: true, data: [{ url: 'https://cdn.example.com/a.jpg' }] })

function jsonResponse(body: string, ok = true): any {
  return { ok, status: ok ? 200 : 500, text: async () => body }
}

describe('上传照片：Blob 直传（issue #8307）', () => {
  const originalFetch = global.fetch
  afterEach(() => {
    global.fetch = originalFetch
    jest.clearAllMocks()
  })

  it('① 有 Blob ⇒ FormData 直传（字段名 files），且不调用 Taro.uploadFile', async () => {
    const calls: any[] = []
    global.fetch = jest.fn(async (url: any, init: any) => {
      calls.push({ url, init })
      return jsonResponse(OK_BODY)
    }) as any
    // 红证底座：Taro.uploadFile 永不返回 —— 只要还依赖它，这条用例就不会结束
    ;(Taro.uploadFile as jest.Mock).mockImplementation(() => new Promise(() => {}))

    const file = new Blob(['fake-jpeg'], { type: 'image/jpeg' }) as any
    file.name = 'label.jpg'
    const res = await uploadInboundPhotoSmart({ file })

    expect(res.success).toBe(true)
    expect(res.data?.url).toBe('https://cdn.example.com/a.jpg')
    expect(Taro.uploadFile).not.toHaveBeenCalled()
    expect(calls).toHaveLength(1)
    expect(String(calls[0].url)).toContain('/api/worker/inbound/upload')
    expect(calls[0].init.method).toBe('POST')
    const form = calls[0].init.body as FormData
    expect(form).toBeInstanceOf(FormData)
    expect(form.get('files')).toBeTruthy()
    // 🔴 不许设 Content-Type：multipart 的 boundary 必须由浏览器生成
    expect(Object.keys(calls[0].init.headers || {}).map((k) => k.toLowerCase())).not.toContain('content-type')
  })

  it('② 只有 blob: 串 ⇒ 先 fetch 读成 Blob 再直传', async () => {
    const seen: string[] = []
    global.fetch = jest.fn(async (url: any) => {
      seen.push(String(url))
      if (String(url).startsWith('blob:')) {
        return { ok: true, blob: async () => new Blob(['from-blob-url'], { type: 'image/jpeg' }) } as any
      }
      return jsonResponse(OK_BODY)
    }) as any

    const blob = await resolvePhotoBlob({ tempFilePath: 'blob:http://x/abc' })
    expect(blob).toBeInstanceOf(Blob)

    const res = await uploadInboundPhotoSmart({ tempFilePath: 'blob:http://x/abc' })
    expect(res.success).toBe(true)
    expect(seen[0]).toBe('blob:http://x/abc')
    expect(seen.some((u) => u.includes('/api/worker/inbound/upload'))).toBe(true)
  })

  it('③ 读不到 Blob ⇒ 回落 Taro.uploadFile（不静默失败）', async () => {
    global.fetch = jest.fn(async () => {
      throw new Error('blob url revoked')
    }) as any
    ;(Taro.uploadFile as jest.Mock).mockResolvedValueOnce({
      statusCode: 200,
      data: JSON.stringify({ success: true, data: [{ url: 'https://cdn.example.com/fallback.jpg' }] }),
    })

    const res = await uploadInboundPhotoSmart({ tempFilePath: 'blob:http://x/revoked' })
    expect(Taro.uploadFile).toHaveBeenCalledTimes(1)
    expect(res.success).toBe(true)
    expect(res.data?.url).toBe('https://cdn.example.com/fallback.jpg')
  })

  it('④ 响应形状按服务端 data[0].url 归一（对象 data 也接受）', async () => {
    global.fetch = jest.fn(async () => jsonResponse(JSON.stringify({ success: true, data: { url: 'https://cdn.example.com/b.jpg' } }))) as any
    const res = await uploadInboundPhotoBlob(new Blob(['x']))
    expect(res.success).toBe(true)
    expect(res.data?.url).toBe('https://cdn.example.com/b.jpg')
  })

  it('⑤ 非 JSON 响应 ⇒ 明确失败文案（不是空结果）', async () => {
    global.fetch = jest.fn(async () => jsonResponse('<html>502</html>', false)) as any
    const res = await uploadInboundPhotoBlob(new Blob(['x']))
    expect(res.success).toBe(false)
    expect(res.message).toContain('不是 JSON')
  })
})
