import { useCallback, useEffect, useMemo, useState } from 'react'
import { View, Text, Image } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { API_BASE_URL } from '../../utils/constants'
import {
  posterViewFromCard,
  resolvePosterImage,
  type MarketingPosterView,
} from '../../utils/poster/posterLayout'
import {
  renderMarketingPoster,
  type PosterCanvasLike,
  type PosterImageLike,
} from '../../utils/poster/posterCanvas'
import './PosterCard.scss'

/**
 * 营销海报卡（issue #7351，B 端移动 H5）
 *
 * 与 B 端桌面 `frontend/admin-web/src/components/chat/MarketingPosterCard.tsx` **同口径**：
 * 服务端只下发商品事实 + 商家确认过的文案，本端画 750×1000 PNG，并给「保存到相册」入口。
 *
 * ## 保存路径（用户 2026-10-19 裁定：手机端 = bmini H5）
 *
 * - 微信内置浏览器：**长按图片**是唯一能真正写入相册的路径（JS 无法直接存相册）⇒ 点按钮弹提示；
 * - 其它手机浏览器 / PC：走 `<a download>`（下载到「下载/相册」目录）⇒ toast 告知已开始下载；
 * - 图片本身始终展示，长按提示常驻 —— 不把「下载成功」谎报成「已存相册」。
 *
 * ## 非 H5（小程序）的边界（如实登记）
 *
 * 本卡当前只在 H5 分支生成图片（`document.createElement('canvas')`）。小程序端
 * 需要在页面上放 `<Canvas>` + `canvasToTempFilePath`，属**另一条实现**；当前用户口径
 * 是 H5，故非 H5 渲染一句如实说明，**不画空白卡**。
 */

const IS_H5 = process.env.TARO_ENV === 'h5' || process.env.TARO_ENV === undefined

type RenderState =
  | { status: 'loading' }
  | { status: 'unsupported' }
  | { status: 'ready'; dataUrl: string; hadImage: boolean }
  | { status: 'error'; message: string }

function createCanvas(width: number, height: number): PosterCanvasLike {
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  return canvas as unknown as PosterCanvasLike
}

function loadImage(url: string): Promise<PosterImageLike | null> {
  return new Promise((resolve) => {
    const image = new window.Image()
    image.crossOrigin = 'anonymous'
    image.onload = () => resolve(image)
    image.onerror = () => {
      // CORS 失败 ⇒ 再试一次不限 CORS（能画但可能污染画布；导出失败由绘制层降级为无图）
      const retry = new window.Image()
      retry.onload = () => resolve(retry)
      retry.onerror = () => resolve(null)
      retry.src = url
    }
    image.src = url
  })
}

interface PosterCardProps {
  data: any
}

export default function PosterCard({ data }: PosterCardProps) {
  const view: MarketingPosterView = useMemo(() => {
    const parsed = posterViewFromCard(data || {})
    return {
      ...parsed,
      product: {
        ...parsed.product,
        image: resolvePosterImage(parsed.product.image, API_BASE_URL),
      },
    }
  }, [data])

  const [state, setState] = useState<RenderState>({ status: 'loading' })
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    if (!IS_H5) {
      setState({ status: 'unsupported' })
      return
    }
    let mounted = true
    setState({ status: 'loading' })
    renderMarketingPoster(view, { createCanvas, loadImage })
      .then((rendered) => {
        if (!mounted) return
        setState({ status: 'ready', dataUrl: rendered.dataUrl, hadImage: rendered.hadImage })
      })
      .catch((error: unknown) => {
        if (!mounted) return
        setState({
          status: 'error',
          message: error instanceof Error ? error.message : '海报生成失败，请重试',
        })
      })
    return () => {
      mounted = false
    }
  }, [view, reloadKey])

  const handleSave = useCallback(() => {
    if (state.status !== 'ready') return
    const ua = typeof navigator !== 'undefined' ? navigator.userAgent : ''
    if (/MicroMessenger/i.test(ua)) {
      // 微信内无法用 JS 写入相册：给唯一可行的路径，不谎报「已保存」
      Taro.showModal({
        title: '保存到相册',
        content: '长按上方海报图片，选择「保存图片」即可存入相册。',
        showCancel: false,
      })
      return
    }
    const anchor = document.createElement('a')
    anchor.href = state.dataUrl
    anchor.download = `营销海报-${view.product.name}.png`
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    Taro.showToast({ title: '已开始下载', icon: 'none' })
  }, [state, view.product.name])

  return (
    <View className='poster-card'>
      <View className='poster-card__header'>
        <Text className='poster-card__title'>营销海报</Text>
        <Text className='poster-card__subtitle'>750×1000</Text>
      </View>

      {state.status === 'loading' && <View className='poster-card__loading'>海报生成中…</View>}

      {state.status === 'unsupported' && (
        <Text className='poster-card__empty'>
          海报生成请在手机浏览器（或微信内打开的 H5）中使用，当前环境暂不支持。
        </Text>
      )}

      {state.status === 'error' && (
        <View className='poster-card__error'>
          <Text className='poster-card__error-text'>{state.message}</Text>
          <View className='poster-card__retry' onClick={() => setReloadKey((key) => key + 1)}>
            <Text>重试</Text>
          </View>
        </View>
      )}

      {state.status === 'ready' && (
        <>
          <Image
            className='poster-card__image'
            src={state.dataUrl}
            mode='widthFix'
            showMenuByLongpress
          />
          {!state.hadImage && (
            <Text className='poster-card__note'>
              商品图未能加载，已生成无图海报（商品名/价格/文案完整）
            </Text>
          )}
          <View className='poster-card__actions'>
            <View className='poster-card__save' onClick={handleSave}>
              <Text>保存到相册</Text>
            </View>
          </View>
          <Text className='poster-card__hint'>
            微信内请长按上方海报保存；想换文案直接告诉黄金策。
          </Text>
        </>
      )}
    </View>
  )
}
