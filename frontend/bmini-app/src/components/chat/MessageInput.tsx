import { useState, useCallback, useRef } from 'react'
import { View, Text, Textarea, Image } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { chooseImages, uploadImages } from '../../utils/imageUpload'
import { startRecording, stopAndTranscribe, isVoiceSupported } from '../../utils/voice'
import { isH5, H5_VOICE_UNAVAILABLE_HINT } from '../../utils/platform'
import {
  ICON_AUDIO_LINES,
  ICON_KEYBOARD,
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
 * 键盘模式的 placeholder（语音**不可达**那条腿才用得上 —— 做不到就不承诺语音，issue #6476）。
 * 给一个**真答得出来**的例子（服务端六格快捷问题里的第一条）。
 */
const PLACEHOLDER_TEXT = '打字问黄金策，比如「今天经营怎么样？」'
/** 语音模式中间那句话（用户 2026-10-09 逐字：「默认文字叫按住说话」） */
const HOLD_LABEL = '按住说话'

/**
 * 输入条（**单行** `[切换][输入框 或「按住说话」][加图][发送]`）
 *
 * ## 形态（用户 2026-10-09 逐字裁定，issue #6596）
 *
 * > 「把输入框，添加图片，语音的按钮放一行，然后定义一个格式的宽高，而且默认文字叫按住说话，
 * >  通过语音对话，语音和键盘 icon 可以切换文字输入和语音对话。」
 *
 * - **单行定高**：一行四格，触摸键统一 88px（44pt）；容器高随草稿图增长，行本身不抖
 * - **默认语音模式**：中间是「按住说话」；点键盘图标 ⇒ 文字输入（出现输入框）；再点 ⇒ 回语音
 * - 语音：按住说话、松开直接发送（UI-007 行为保持）、上滑取消
 * - 添图统一进草稿（预览可删），空文本有图 = 纯图消息（UI-013 协议不变）
 * - 自适应主动作键：流式中 = 停止 / 有草稿 = 发送 / 空草稿 = 不占位
 *
 * ## 语音可达性（#6596 起按**浏览器能力**分流，不再按编译目标写死）
 *
 * - 语音可用 ⇒ 语音模式；**按住真的会录**（h5 走 `getUserMedia` + `MediaRecorder`，
 *   见 `frontend/bmini-app/src/utils/voiceBrowserRecorder.ts`；weapp 走 `RecorderManager`）
 * - 语音不可用 ⇒ 回落文字模式：**不渲染**「按住说话」（不许摆一个按不动的键 —— #5650 的教训），
 *   切换键仍在，点了给一句**可行动**的解释
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
  /** 默认语音模式（用户裁定）；语音不可达时直接落在文字模式 */
  const [voiceMode, setVoiceMode] = useState(voiceSupported)

  // 录音触摸跟踪（ref，避免触摸事件竞态）
  const touchStartYRef = useRef(0)
  const cancellingRef = useRef(false)
  const recordingRef = useRef(false)

  const canVoice = voiceSupported && !disabled && !isStreaming && !isUploading
  const canAttach = !disabled && !isStreaming && !isUploading
  const hasDraft = value.trim().length > 0 || selectedImages.length > 0
  const canSend = hasDraft && !disabled && !isUploading && !isRecording

  // ── 键盘 ⇄ 语音切换 ──

  /**
   * 切到语音模式。浏览器**确实没有**录音能力时不给空承诺：不切模式（留在文字模式）、
   * 给一句「为什么 + 怎么办」的显式解释（issue #5650）。
   */
  const handleSwitchToVoice = useCallback(() => {
    if (!voiceSupported) {
      Taro.showToast({ title: H5_VOICE_UNAVAILABLE_HINT, icon: 'none' })
      return
    }
    setVoiceMode(true)
  }, [voiceSupported])

  const handleSwitchToKeyboard = useCallback(() => {
    setVoiceMode(false)
  }, [])

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

        {/* 单行：[切换][输入框 或「按住说话」][加图][动作键] */}
        <View className='message-input__row'>
          <View
            className={`message-input__mode-toggle${!voiceSupported ? ' message-input__mode-toggle--disabled' : ''}`}
            // 标签说的是**这个键会做什么**（点它切到哪个模式），到哪儿都是「切换」语义 ⇒
            // 浏览器录音不可达时不在这里撒谎（那时点了会给一句显式解释，见 handleSwitchToVoice）
            aria-label={voiceMode ? '切换到键盘输入' : '切换到语音输入'}
            onClick={voiceMode ? handleSwitchToKeyboard : handleSwitchToVoice}
          >
            <Image
              className='message-input__icon'
              src={voiceMode ? ICON_KEYBOARD : ICON_AUDIO_LINES}
            />
          </View>

          <View className='message-input__center'>
            {voiceMode ? (
              <View
                className={`message-input__hold${!canVoice ? ' message-input__hold--disabled' : ''}${isRecording ? ' message-input__hold--recording' : ''}`}
                aria-label={canVoice ? HOLD_LABEL : `${HOLD_LABEL}（当前不可用）`}
                onTouchStart={handleTouchStart}
                onTouchMove={handleTouchMove}
                onTouchEnd={handleTouchEnd}
              >
                <Text className='message-input__hold-text'>{HOLD_LABEL}</Text>
              </View>
            ) : (
              /* 键盘模式：语音可达 ⇒ 双语义 placeholder；不可达 ⇒ 只说实话（不写「按住说话」） */
              <Textarea
                className='message-input__textarea'
                value={value}
                onInput={handleInput}
                onConfirm={handleConfirm}
                placeholder={voiceSupported ? `发消息或${HOLD_LABEL}` : PLACEHOLDER_TEXT}
                placeholderClass='message-input__placeholder'
                maxlength={500}
                autoHeight
                adjustPosition
                confirmType='send'
                showConfirmBar={false}
                disabled={disabled || isUploading}
                aria-label='消息输入框'
              />
            )}
          </View>

          <View
            className={`message-input__attach message-input__icon-btn${!canAttach || selectedImages.length >= MAX_IMAGES ? ' message-input__icon-btn--disabled' : ''}`}
            aria-label='添加图片'
            onClick={handleChooseImage}
          >
            <Image className='message-input__icon' src={ICON_IMAGE_PLUS} />
          </View>

          <View className='message-input__actions'>
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
            ) : null}
          </View>
        </View>
      </View>
    </View>
  )
}
