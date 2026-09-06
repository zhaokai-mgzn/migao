import { useState, useCallback, useRef } from 'react'
import { View, Text, Textarea, Image } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { chooseImages, uploadImages } from '../../utils/imageUpload'
import { startRecording, stopAndTranscribe, isVoiceSupported } from '../../utils/voice'
import {
  ICON_AUDIO_LINES,
  ICON_IMAGE_PLUS,
  ICON_ARROW_UP,
  ICON_STOP_SQUARE,
  ICON_CLOSE,
} from './icons'
import './MessageInput.scss'

interface MessageInputProps {
  onSend: (content: string, images?: string[]) => void
  onStop?: () => void
  isStreaming: boolean
  disabled?: boolean
}

/** 上滑取消阈值（px） */
const CANCEL_THRESHOLD = 50
/** 草稿图片上限 */
const MAX_IMAGES = 3

/**
 * 输入条（豆包式单容器，参考 docs/design/agent-input-bar-unified-design.md）
 *
 * - textarea 常驻 + placeholder「发消息或按住说话」：两种输入方式共用一个容器，无模式切换键
 * - 语音：按住说话、松开直接发送（UI-007 行为保持）、上滑取消
 * - 添图统一进草稿（预览可删），空文本有图 = 纯图消息（UI-013 协议不变）
 * - 自适应主动作键：草稿空 = 按住说话 / 有草稿 = 发送 / 流式中 = 停止
 */
export default function MessageInput({
  onSend,
  onStop,
  isStreaming,
  disabled = false,
}: MessageInputProps) {
  const voiceSupported = isVoiceSupported()
  const [value, setValue] = useState('')
  const [selectedImages, setSelectedImages] = useState<string[]>([])
  const [isUploading, setIsUploading] = useState(false)
  const [isRecording, setIsRecording] = useState(false)
  const [isCancelling, setIsCancelling] = useState(false)

  // 录音触摸跟踪（ref，避免触摸事件竞态）
  const touchStartYRef = useRef(0)
  const cancellingRef = useRef(false)
  const recordingRef = useRef(false)

  const canVoice = voiceSupported && !disabled && !isStreaming && !isUploading
  const canAttach = !disabled && !isStreaming && !isUploading
  const hasDraft = value.trim().length > 0 || selectedImages.length > 0
  const canSend = hasDraft && !disabled && !isUploading && !isRecording

  // ── 语音：按住说话 / 松开直接发送（行为保持）/ 上滑取消 ──

  const handleTouchStart = useCallback(
    (e: any) => {
      if (!canVoice) return
      recordingRef.current = true
      cancellingRef.current = false
      touchStartYRef.current = e.touches?.[0]?.clientY ?? 0
      setIsRecording(true)
      setIsCancelling(false)
      startRecording()
    },
    [canVoice]
  )

  const handleTouchMove = useCallback((e: any) => {
    if (!recordingRef.current) return
    const y = e.touches?.[0]?.clientY ?? 0
    const cancelled = touchStartYRef.current - y > CANCEL_THRESHOLD
    cancellingRef.current = cancelled
    setIsCancelling(cancelled)
  }, [])

  const handleTouchEnd = useCallback(async () => {
    if (!recordingRef.current) return
    recordingRef.current = false
    setIsRecording(false)
    setIsCancelling(false)

    if (cancellingRef.current) {
      cancellingRef.current = false
      Taro.showToast({ title: '已取消', icon: 'none' })
      return
    }

    try {
      const result = await stopAndTranscribe()
      if (result && result.text) {
        onSend(result.text)
      } else {
        Taro.showToast({ title: '未听清，请重试', icon: 'none' })
      }
    } catch (error: any) {
      console.error('语音输入失败:', error)
      Taro.showToast({ title: error.message || '语音输入失败', icon: 'none' })
    }
  }, [onSend])

  // ── 键盘 + 添图（统一草稿语义）──

  const handleInput = useCallback((e: any) => {
    setValue(e.detail.value)
  }, [])

  const handleChooseImage = useCallback(async () => {
    if (!canAttach || isRecording) return
    const remaining = MAX_IMAGES - selectedImages.length
    if (remaining <= 0) {
      Taro.showToast({ title: `最多添加 ${MAX_IMAGES} 张图片`, icon: 'none' })
      return
    }
    const paths = await chooseImages(remaining)
    if (paths.length > 0) {
      setSelectedImages(prev => [...prev, ...paths].slice(0, MAX_IMAGES))
    }
  }, [canAttach, isRecording, selectedImages])

  const handleRemoveImage = useCallback((index: number) => {
    setSelectedImages(prev => prev.filter((_, i) => i !== index))
  }, [])

  /** 发送：流式中=停止；有图先上传；空文本+图=纯图消息（UI-013） */
  const handleSend = useCallback(async () => {
    if (isStreaming) {
      onStop?.()
      return
    }

    const trimmed = value.trim()
    if ((!trimmed && selectedImages.length === 0) || disabled || isUploading) return

    // 有图片需要先上传
    if (selectedImages.length > 0) {
      setIsUploading(true)
      try {
        const uploaded = await uploadImages(selectedImages)
        const imageUrls = uploaded.map(f => f.url)
        onSend(trimmed || '', imageUrls)
        setValue('')
        setSelectedImages([])
      } catch (error: any) {
        console.error('图片上传失败:', error)
        Taro.showToast({ title: error.message || '图片上传失败', icon: 'none' })
      } finally {
        setIsUploading(false)
      }
    } else {
      if (!trimmed) return
      onSend(trimmed)
      setValue('')
    }
  }, [value, selectedImages, isStreaming, disabled, isUploading, onSend, onStop])

  const handleConfirm = useCallback(() => {
    handleSend()
  }, [handleSend])

  return (
    <View className='message-input'>
      <View className='message-input__container'>
        {/* 录音状态条（录音中内嵌容器顶部） */}
        {isRecording && (
          <View className='message-input__recording'>
            <View className='message-input__recording-dot' />
            <Text className='message-input__recording-text'>
              {isCancelling ? '松开手指，取消发送' : '正在说话，松开发送'}
            </Text>
          </View>
        )}

        {/* 草稿图预览（统一草稿语义，不再区分模式） */}
        {selectedImages.length > 0 && (
          <View className='message-input__images'>
            {selectedImages.map((path, idx) => (
              <View key={`preview-${idx}`} className='message-input__image-item'>
                <Image
                  className='message-input__image-thumb'
                  src={path}
                  mode='aspectFill'
                />
                <View
                  className='message-input__image-remove'
                  aria-label='删除图片'
                  onClick={() => handleRemoveImage(idx)}
                >
                  <Image className='message-input__image-remove-icon' src={ICON_CLOSE} />
                </View>
              </View>
            ))}
          </View>
        )}

        {/* 文本输入（常驻，双语义 placeholder） */}
        <Textarea
          className='message-input__textarea'
          value={value}
          onInput={handleInput}
          onConfirm={handleConfirm}
          placeholder='发消息或按住说话'
          placeholderClass='message-input__placeholder'
          maxlength={500}
          autoHeight
          adjustPosition
          confirmType='send'
          showConfirmBar={false}
          disabled={disabled || isUploading}
          aria-label='消息输入框'
        />

        {/* 右下自适应动作组：[添图] + [按住说话 / 发送 / 停止] */}
        <View className='message-input__actions'>
          <View
            className={`message-input__icon-btn${!canAttach || selectedImages.length >= MAX_IMAGES ? ' message-input__icon-btn--disabled' : ''}`}
            aria-label='添加图片'
            onClick={handleChooseImage}
          >
            <Image className='message-input__icon' src={ICON_IMAGE_PLUS} />
          </View>

          {isStreaming ? (
            <View
              className='message-input__icon-btn message-input__icon-btn--stop'
              aria-label='停止生成'
              onClick={handleSend}
            >
              <Image className='message-input__icon' src={ICON_STOP_SQUARE} />
            </View>
          ) : hasDraft ? (
            <View
              className={`message-input__icon-btn message-input__icon-btn--send${!canSend ? ' message-input__icon-btn--disabled' : ''}`}
              aria-label='发送'
              onClick={handleSend}
            >
              <Image className='message-input__icon' src={ICON_ARROW_UP} />
            </View>
          ) : (
            voiceSupported && (
              <View
                className={`message-input__icon-btn message-input__icon-btn--voice${!canVoice ? ' message-input__icon-btn--disabled' : ''}${isRecording ? ' message-input__icon-btn--recording' : ''}`}
                aria-label='按住说话'
                onTouchStart={handleTouchStart}
                onTouchMove={handleTouchMove}
                onTouchEnd={handleTouchEnd}
              >
                <Image className='message-input__icon' src={ICON_AUDIO_LINES} />
              </View>
            )
          )}
        </View>
      </View>
    </View>
  )
}
