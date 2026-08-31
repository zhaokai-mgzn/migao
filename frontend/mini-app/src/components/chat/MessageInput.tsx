import { useState, useCallback, useRef } from 'react'
import { View, Textarea, Text, Image } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { chooseImages, uploadImages } from '../../utils/imageUpload'
import { startRecording, stopAndTranscribe, isVoiceSupported } from '../../utils/voice'
import './MessageInput.scss'

interface MessageInputProps {
  onSend: (content: string, images?: string[]) => void
  onStop?: () => void
  isStreaming: boolean
  disabled?: boolean
}

type InputMode = 'voice' | 'keyboard'

/** 上滑取消阈值（px） */
const CANCEL_THRESHOLD = 50

export default function MessageInput({
  onSend,
  onStop,
  isStreaming,
  disabled = false,
}: MessageInputProps) {
  // 默认语音模式（按住说话、松开发送）；H5 等不支持录音的环境默认键盘模式
  const voiceSupported = isVoiceSupported()
  const [mode, setMode] = useState<InputMode>(voiceSupported ? 'voice' : 'keyboard')
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
  const isKeyboard = mode === 'keyboard'

  // ── 语音模式：按住说话 / 松开发送 / 上滑取消 ──

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

  // ── 键盘模式：图片 + 文本 ──

  const handleInput = useCallback((e: any) => {
    setValue(e.detail.value)
  }, [])

  const handleChooseImage = useCallback(async () => {
    if (isUploading || isStreaming || disabled || isRecording) return
    const maxCount = 3 - selectedImages.length
    if (maxCount <= 0) {
      Taro.showToast({ title: '最多选择 3 张图片', icon: 'none' })
      return
    }
    const paths = await chooseImages(maxCount)
    if (paths.length > 0) {
      setSelectedImages(prev => [...prev, ...paths].slice(0, 3))
    }
  }, [selectedImages, isUploading, isStreaming, disabled, isRecording])

  const handleRemoveImage = useCallback((index: number) => {
    setSelectedImages(prev => prev.filter((_, i) => i !== index))
  }, [])

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

  const hasContent = value.trim().length > 0 || selectedImages.length > 0

  let btnClass = 'message-input__btn'
  let btnIcon = '↑'
  if (isStreaming) {
    btnClass += ' message-input__btn--stop'
    btnIcon = '■'
  } else if (isUploading) {
    btnClass += ' message-input__btn--disabled'
    btnIcon = '...'
  } else if (hasContent) {
    btnClass += ' message-input__btn--active'
  } else {
    btnClass += ' message-input__btn--disabled'
  }

  return (
    <View className='message-input'>
      {/* 图片预览区域（键盘模式） */}
      {isKeyboard && selectedImages.length > 0 && (
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
                onClick={() => handleRemoveImage(idx)}
              >
                <Text className='message-input__image-remove-icon'>×</Text>
              </View>
            </View>
          ))}
          {isUploading && (
            <View className='message-input__upload-loading'>
              <Text className='message-input__upload-loading-text'>上传中...</Text>
            </View>
          )}
        </View>
      )}

      <View className='message-input__bar'>
        {/* 语音/键盘模式切换键（仅录音可用环境展示） */}
        {voiceSupported && (
          <View
            className='message-input__mode-btn'
            onClick={() => setMode(mode => (mode === 'voice' ? 'keyboard' : 'voice'))}
          >
            <Text className='message-input__mode-btn-icon'>{isKeyboard ? '🎤' : '⌨️'}</Text>
          </View>
        )}

        {isKeyboard ? (
          <>
            {/* 图片选择按钮 */}
            <View
              className={`message-input__img-btn${disabled || isStreaming || isUploading ? ' message-input__img-btn--disabled' : ''}`}
              onClick={handleChooseImage}
            >
              <Text className='message-input__img-btn-icon'>+</Text>
            </View>

            <View className='message-input__textarea-wrap'>
              <Textarea
                className='message-input__textarea'
                value={value}
                onInput={handleInput}
                onConfirm={handleConfirm}
                placeholder='输入您的问题...'
                placeholderStyle='color: #9AA5B1'
                maxlength={500}
                autoHeight
                confirmType='send'
                adjustPosition
                showConfirmBar={false}
                disabled={disabled || isUploading}
              />
            </View>
            <View className={btnClass} onClick={handleSend}>
              <Text className='message-input__btn-icon'>{btnIcon}</Text>
            </View>
          </>
        ) : (
          <>
            {/* 按住说话 */}
            <View
              className={`message-input__hold-btn${isRecording ? ' message-input__hold-btn--recording' : ''}${isCancelling ? ' message-input__hold-btn--cancelling' : ''}${!canVoice ? ' message-input__hold-btn--disabled' : ''}`}
              onTouchStart={handleTouchStart}
              onTouchMove={handleTouchMove}
              onTouchEnd={handleTouchEnd}
            >
              <Text className='message-input__hold-btn-text'>
                {isRecording
                  ? isCancelling
                    ? '松开 取消'
                    : '松开 发送 · 上滑 取消'
                  : '按住 说话'}
              </Text>
            </View>
          </>
        )}
      </View>
    </View>
  )
}
