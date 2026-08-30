import { useState, useCallback } from 'react'
import { View, Textarea, Text, Image } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { chooseImages, uploadImages } from '../../utils/imageUpload'
import { recordAndTranscribe } from '../../utils/voice'
import './MessageInput.scss'

interface MessageInputProps {
  onSend: (content: string, images?: string[]) => void
  onStop?: () => void
  isStreaming: boolean
  disabled?: boolean
}

export default function MessageInput({
  onSend,
  onStop,
  isStreaming,
  disabled = false,
}: MessageInputProps) {
  const [value, setValue] = useState('')
  const [selectedImages, setSelectedImages] = useState<string[]>([])
  const [isUploading, setIsUploading] = useState(false)
  const [isRecording, setIsRecording] = useState(false)

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

  /** 语音输入：录音 → 转文字 → 回填并自动发送 */
  const handleVoice = useCallback(async () => {
    if (isStreaming || disabled || isUploading) return

    setIsRecording(true)
    Taro.showToast({ title: '正在聆听...', icon: 'none', duration: 30000 })
    try {
      const result = await recordAndTranscribe()
      if (result && result.text) {
        setValue('')
        onSend(result.text)
      } else {
        Taro.showToast({ title: '未听清，请重试', icon: 'none' })
      }
    } catch (error: any) {
      console.error('语音输入失败:', error)
      Taro.showToast({ title: error.message || '语音输入失败', icon: 'none' })
    } finally {
      setIsRecording(false)
      Taro.hideToast()
    }
  }, [isStreaming, disabled, isUploading, onSend])

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
      {/* 图片预览区域 */}
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
        {/* 语音按钮 */}
        <View
          className={`message-input__voice-btn${isRecording ? ' message-input__voice-btn--recording' : ''}${disabled || isStreaming || isUploading ? ' message-input__voice-btn--disabled' : ''}`}
          onClick={handleVoice}
        >
          <Text className='message-input__voice-btn-icon'>🎤</Text>
        </View>

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
      </View>
    </View>
  )
}
