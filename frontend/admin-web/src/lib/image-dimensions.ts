/**
 * 读取图片文件的自然尺寸（naturalWidth / naturalHeight）
 *
 * 用于 Logo 等固定展示尺寸的上传校验：jsdom/SSR 环境不支持真实图片解码，
 * 校验失败时抛错由调用方决定是否放行（浏览器环境正常可用）。
 */
export interface ImageDimensions {
  width: number
  height: number
}

export function readImageDimensions(file: File): Promise<ImageDimensions> {
  return new Promise((resolve, reject) => {
    if (typeof Image === 'undefined' || typeof URL.createObjectURL === 'undefined') {
      reject(new Error('当前环境不支持读取图片尺寸'))
      return
    }
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => {
      URL.revokeObjectURL(url)
      resolve({ width: img.naturalWidth, height: img.naturalHeight })
    }
    img.onerror = () => {
      URL.revokeObjectURL(url)
      reject(new Error('无法读取图片，请更换图片后重试'))
    }
    img.src = url
  })
}
