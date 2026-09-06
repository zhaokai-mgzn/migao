/**
 * 图片上传工具
 *
 * 使用 Taro.uploadFile 上传图片到 /api/chat/upload-image
 * 注意：Taro.uploadFile 只支持单文件上传，多张需循环
 */

import Taro from '@tarojs/taro'
import { AI_API_BASE_URL } from './constants'
import { getToken } from './auth'
import { getTenantId } from './auth'

export interface UploadedFile {
  id: string
  url: string
  name: string
  size: number
}

/**
 * 上传单张图片
 */
async function uploadSingleImage(filePath: string): Promise<UploadedFile> {
  const token = getToken()
  const tenantId = getTenantId()

  const res = await Taro.uploadFile({
    url: `${AI_API_BASE_URL}/api/chat/upload-image`,
    filePath,
    name: 'files',
    header: {
      'Authorization': token ? `Bearer ${token}` : '',
      'X-Client-Type': 'wechat_mini',
      ...(tenantId ? { 'X-Tenant-Id': String(tenantId) } : {}),
    },
  })

  if (res.statusCode !== 200) {
    throw new Error(`上传失败: ${res.statusCode}`)
  }

  const data = typeof res.data === 'string' ? JSON.parse(res.data) : res.data

  if (!data.success || !data.data?.files?.length) {
    throw new Error(data.error?.message || '上传失败')
  }

  return data.data.files[0]
}

/**
 * 上传多张图片（串行）
 * @param filePaths 本地文件路径列表（最多 3 张）
 * @returns 上传后的文件信息列表
 */
export async function uploadImages(filePaths: string[]): Promise<UploadedFile[]> {
  if (filePaths.length === 0) return []
  if (filePaths.length > 3) {
    throw new Error('最多上传 3 张图片')
  }

  const results: UploadedFile[] = []
  for (const filePath of filePaths) {
    const file = await uploadSingleImage(filePath)
    results.push(file)
  }
  return results
}

/**
 * 选择图片（调用 Taro.chooseImage）
 * @param maxCount 最多选择数量（默认 3）
 * @returns 选择的本地临时文件路径列表
 */
export async function chooseImages(maxCount = 3): Promise<string[]> {
  try {
    const res = await Taro.chooseImage({
      count: maxCount,
      sizeType: ['compressed'],
      sourceType: ['album', 'camera'],
    })
    return res.tempFilePaths
  } catch {
    // 用户取消选择
    return []
  }
}
