'use client'

import { useState, useRef, useCallback } from 'react'
import { chatApi } from '@/lib/api'
import { useAuthStore } from '@/store/auth'
import { toast } from 'sonner'
import { shouldTranscribeVoice, toFriendlyTranscribeError } from '@/lib/voice-guard'

export type VoiceState = 'idle' | 'recording' | 'transcribing' | 'done'

interface VoiceRecorderReturn {
  /** 当前状态 */
  state: VoiceState
  /** 开始录音 */
  startRecording: () => Promise<void>
  /** 停止录音并转写 */
  stopRecording: () => void
  /** 取消录音（不转写） */
  cancelRecording: () => void
  /** 录音时长（秒） */
  duration: number
}

export function useVoiceRecorder(
  onTranscribed: (text: string) => void,
): VoiceRecorderReturn {
  const [state, setState] = useState<VoiceState>('idle')
  const [duration, setDuration] = useState(0)

  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const startTimeRef = useRef<number>(0)

  const cleanup = useCallback(() => {
    // 停止计时器
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
    // 释放麦克风
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop())
      streamRef.current = null
    }
    mediaRecorderRef.current = null
    chunksRef.current = []
  }, [])

  const startRecording = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: 16000,
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      })
      streamRef.current = stream

      // 检测支持的 MIME 类型
      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : MediaRecorder.isTypeSupported('audio/webm')
          ? 'audio/webm'
          : 'audio/mp4'

      const recorder = new MediaRecorder(stream, { mimeType })
      mediaRecorderRef.current = recorder
      chunksRef.current = []

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) {
          chunksRef.current.push(e.data)
        }
      }

      recorder.onstop = async () => {
        const blob = new Blob(chunksRef.current, { type: mimeType })
        chunksRef.current = []
        const recordedMs = Date.now() - startTimeRef.current
        cleanup()

        // #2984：空口语/误触录音（<0.8s 或 <4KB）不发转写请求，轻提示后复位 ——
        // 取代旧逻辑「无条件 POST → 后端 500 → Failed to fetch 生硬报错」
        if (!shouldTranscribeVoice(recordedMs, blob.size)) {
          setState('idle')
          setDuration(0)
          toast.info('未检测到声音，已取消转写')
          return
        }

        // 开始转写
        setState('transcribing')
        try {
          const token = useAuthStore.getState().accessToken || ''
          const result = await chatApi.transcribeAudio(blob, token)
          setState('done')
          onTranscribed(result.text)
          // 短暂显示完成态后恢复空闲
          setTimeout(() => setState('idle'), 1500)
        } catch (err) {
          console.error('语音转写失败:', err)
          // #2984：网络失败/裸 500 都转成用户可理解的文案，不再透出 "Failed to fetch"
          toast.error(toFriendlyTranscribeError(err))
          setState('idle')
        }
      }

      recorder.start()
      startTimeRef.current = Date.now()
      setState('recording')
      setDuration(0)

      // 更新录音时长
      timerRef.current = setInterval(() => {
        setDuration(Math.floor((Date.now() - startTimeRef.current) / 1000))
      }, 200)

      // 最长录音 60 秒自动停止
      setTimeout(() => {
        if (mediaRecorderRef.current?.state === 'recording') {
          mediaRecorderRef.current.stop()
        }
      }, 60_000)
    } catch (err) {
      console.error('麦克风访问失败:', err)
      const error = err as Error
      if (error.name === 'NotAllowedError') {
        toast.error('请在浏览器设置中允许麦克风权限')
      } else if (error.name === 'NotFoundError') {
        toast.error('未检测到麦克风设备')
      } else {
        toast.error('无法访问麦克风，请检查设备连接')
      }
      setState('idle')
    }
  }, [cleanup, onTranscribed])

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current?.state === 'recording') {
      mediaRecorderRef.current.stop()
    }
  }, [])

  const cancelRecording = useCallback(() => {
    if (mediaRecorderRef.current?.state === 'recording') {
      // 丢弃数据
      mediaRecorderRef.current.ondataavailable = null
      mediaRecorderRef.current.onstop = null
      mediaRecorderRef.current.stop()
    }
    cleanup()
    setState('idle')
    setDuration(0)
  }, [cleanup])

  return { state, startRecording, stopRecording, cancelRecording, duration }
}
