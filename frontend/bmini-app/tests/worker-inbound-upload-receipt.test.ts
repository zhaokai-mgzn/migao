// case_ids: BM-011
/**
 * 工人端**上传回执形状**判据（issue #6864；2026-10-14 线上 P0）
 *
 * 病：工人端「拍照入库 / 拍照发货」每一次上传都提示「照片上传失败，请重试」，而服务端**每次都成功**
 * （nginx 200 + admin-api「照片已上传 count=1, storage=oss」）。根因是回执形状两侧不一致 ——
 * 服务端 `ApiResponse<List<UploadedFileInfo>>` 的 `data` 是**数组**，端侧按对象读 `data.url`。
 *
 * 为什么以前测不出来：页面级用例把服务**整个 mock** 掉，并手写 `{success:true, data:{url}}`
 * —— 那个形状服务端从来不回。本文件喂的是**服务端逐字回执**（后端用例断言 `$.data[0].url`）。
 *
 * | # | 判据 | 红证 |
 * |---|---|---|
 * | C1 | `data` 是数组 ⇒ 取第 0 张、`success=true` + `url` 到位 | 按对象读 `data.url`（= 修复前形态）⇒ 红 |
 * | C2 | 多张时取**第 0 张**（与服务端「一次 1~3 张」不冲突） | 取最后一张 / 读成整体 ⇒ 红 |
 * | C3 | 空数组**不静默成功**（200 但没有照片地址） | 空数组也报 success ⇒ 红 |
 * | C4 | 传输层失败 / 非 JSON 响应仍走既有分诊（`offline` / 「上传返回的不是 JSON」） | 压成一句通用失败 ⇒ 红 |
 */
import Taro from '@tarojs/taro'
import { uploadInboundPhoto } from '../src/services/workerInboundService'

const uploadFile = Taro.uploadFile as unknown as jest.Mock

/** 服务端**逐字**回执（`WorkerInboundUploadControllerTest` 逐字断言 `$.data[0].url`）：`data` 是数组 */
function serverReceipt(files: Array<{ url: string }>): any {
  return {
    statusCode: 200,
    errMsg: 'uploadFile:ok',
    data: JSON.stringify({ success: true, data: files, requestId: 'req_1', timestamp: 1 }),
  }
}

beforeEach(() => {
  uploadFile.mockReset()
})

describe('工人端上传回执：服务端 data 是数组（issue #6864）', () => {
  it('C1 单张：取到 data[0].url（按对象读 ⇒ 这里必红）', async () => {
    uploadFile.mockResolvedValueOnce(serverReceipt([{ url: 'https://oss/inbound/a.jpg' }]))

    const res = await uploadInboundPhoto('/tmp/a.jpg')

    expect(res.success).toBe(true)
    expect(res.data?.url).toBe('https://oss/inbound/a.jpg')
  })

  it('C1 对照：对象形态回执仍原样可读（不为数组改坏既有形状）', async () => {
    uploadFile.mockResolvedValueOnce({
      statusCode: 200,
      errMsg: 'uploadFile:ok',
      data: JSON.stringify({ success: true, data: { url: 'https://oss/inbound/obj.jpg' } }),
    })

    const res = await uploadInboundPhoto('/tmp/obj.jpg')

    expect(res.success).toBe(true)
    expect(res.data?.url).toBe('https://oss/inbound/obj.jpg')
  })

  it('C2 多张：取第 0 张（不取最后一张、不读成整体）', async () => {
    uploadFile.mockResolvedValueOnce(
      serverReceipt([{ url: 'https://oss/inbound/1.jpg' }, { url: 'https://oss/inbound/2.jpg' }]),
    )

    const res = await uploadInboundPhoto('/tmp/1.jpg')

    expect(res.data?.url).toBe('https://oss/inbound/1.jpg')
  })

  it('C3 空数组：不静默成功', async () => {
    uploadFile.mockResolvedValueOnce(serverReceipt([]))

    const res = await uploadInboundPhoto('/tmp/empty.jpg')

    expect(res.success).toBe(false)
    expect(res.data).toBeUndefined()
  })

  it('C4 传输层失败：offline 标记 + 既有兜底文案（不静默成功）', async () => {
    uploadFile.mockRejectedValueOnce({ errMsg: 'uploadFile:fail timeout' })

    const res = await uploadInboundPhoto('/tmp/net.jpg')

    expect(res.success).toBe(false)
    expect(res.offline).toBe(true)
    expect(res.message).toBe('照片上传失败，请重试')
  })

  it('C4 非 JSON 响应：明说「不是 JSON」（不压成一句通用失败）', async () => {
    uploadFile.mockResolvedValueOnce({ statusCode: 502, errMsg: 'uploadFile:ok', data: '<html>502</html>' })

    const res = await uploadInboundPhoto('/tmp/html.jpg')

    expect(res.success).toBe(false)
    expect(res.message).toBe('上传返回的不是 JSON，请重试')
  })
})
