import { useCallback, useMemo } from 'react'
import { View, Text, Image } from '@tarojs/components'
import Taro from '@tarojs/taro'
import './GeneratedImageCard.scss'

/**
 * 商品图生成卡（issue #7541，B 端移动 H5）
 *
 * 与 B 端桌面 `frontend/admin-web/src/components/chat/GeneratedImageCard.tsx` **同口径**：
 * 服务端只回一张**临时**图片地址（生图内核不落库、不写表单），本端负责预览 +
 * 「保存到相册」入口。
 *
 * ## 保存路径（用户 2026-10-23 裁定：手机端 = 保存到相册）
 *
 * - 微信内置浏览器：**长按图片**是唯一能真正写入相册的路径（JS 无法直接存相册）⇒ 点按钮弹提示；
 * - 其它手机浏览器：走 `<a download>`（存到「下载 / 相册」目录）⇒ toast 告知已开始下载；
 * - 两者都不把「下载完成」谎报成「已存相册」。
 *
 * ## 失败/空态（不静默）
 *
 * 载荷里没有图片地址 ⇒ 明说「这次没拿到图」并给出下一步（重新生成 / 后台上传），**不画空图框**。
 * 图片加载失败 ⇒ 提示链接可能已过期（内核回的是 24 小时临时地址）。
 */

const IS_H5 = process.env.TARO_ENV === 'h5' || process.env.TARO_ENV === undefined

/** 用途 → 用户可见的中文名（不显示内部 kind 值）。 */
const KIND_LABELS: Record<string, string> = {
  main: '商品主图',
  texture: '材质细节图',
  craft: '工艺细节图',
  scene: '场景效果图',
}

interface GeneratedImageCardProps {
  data: any
}

export default function GeneratedImageCard({ data }: GeneratedImageCardProps) {
  const view = useMemo(() => {
    const product = data?.product || {}
    return {
      imageUrl: typeof data?.image_url === 'string' ? data.image_url.trim() : '',
      name: typeof product.name === 'string' ? product.name.trim() : '',
      kindLabel: KIND_LABELS[String(product.kind ?? 'main')] || '商品图',
    }
  }, [data])

  const handleSave = useCallback(() => {
    if (!view.imageUrl) return
    const ua = typeof navigator !== 'undefined' ? navigator.userAgent : ''
    if (/MicroMessenger/i.test(ua) || !IS_H5) {
      // 微信内 / 小程序环境无法用 JS 写入相册：给唯一可行的路径，不谎报「已保存」
      Taro.showModal({
        title: '保存到相册',
        content: '长按上方图片，选择「保存图片」即可存入相册。',
        showCancel: false,
      })
      return
    }
    const anchor = document.createElement('a')
    anchor.href = view.imageUrl
    anchor.download = `商品图-${view.name || '商品'}.png`
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    Taro.showToast({ title: '已开始下载', icon: 'none' })
  }, [view.imageUrl, view.name])

  if (!view.imageUrl) {
    return (
      <View className='gen-image-card gen-image-card--empty'>
        <Text className='gen-image-card__empty-text'>这次没有拿到商品图，暂时没法预览。</Text>
        <Text className='gen-image-card__empty-hint'>
          可以让我重新生成一次；也可以直接在「商品管理」里上传商品图。
        </Text>
      </View>
    )
  }

  return (
    <View className='gen-image-card'>
      <View className='gen-image-card__header'>
        <Text className='gen-image-card__title'>{view.kindLabel}</Text>
        {view.name ? <Text className='gen-image-card__subtitle'>{view.name}</Text> : null}
      </View>

      <Image
        className='gen-image-card__image'
        src={view.imageUrl}
        mode='widthFix'
        showMenuByLongpress
      />

      <View className='gen-image-card__actions'>
        <View className='gen-image-card__save' onClick={handleSave}>
          <Text>保存到相册</Text>
        </View>
      </View>
      <Text className='gen-image-card__hint'>
        微信内请长按上方图片保存；想换一张直接告诉黄金策。
      </Text>
    </View>
  )
}
