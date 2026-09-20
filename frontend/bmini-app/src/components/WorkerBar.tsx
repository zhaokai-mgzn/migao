/**
 * 共用 PAD 的工人身份条（issue #4733，设计 W2/W3）。
 *
 * <p>三条纪律各自落在可见面上：</p>
 * <ol>
 *   <li><b>提交前显示「当前工人：张三」</b>（+ 工号）—— 数据来自**服务端 session**
 *       （`fetchCurrentWorker`），不是前端 state；</li>
 *   <li><b>一步快速切换</b>：点「切换」→ 输入工号 + PIN → 服务端结束旧 session + 建新 session
 *       ⇒ 本组件**不改变父组件状态**（扫码上下文由父组件持有 ⇒ 切完仍在同一屏，不必重扫）；</li>
 *   <li><b>闲置自动登出</b>：服务端 `idle_expires_at` 到期即 401（服务端判据）；前端只做
 *       「到期后把页头回落成未登录 + 提示」这一层可见面（不靠前端定时器当权威）。</li>
 * </ol>
 */

import { useCallback, useEffect, useState } from 'react'
import { View, Text, Button, Input } from '@tarojs/components'
import { fetchCurrentWorker, switchWorker } from '../services/workerService'
import { clearWorkerSession, getCachedWorker, type CurrentWorker } from '../utils/workerSession'
import './WorkerBar.scss'

interface Props {
  /** 登录/切换成功后的回调（父组件可据此刷新「这单是谁在做」的展示）。 */
  onWorkerChange?: (worker: CurrentWorker | null) => void
  /** 跳转工人登录页（无 session 时点「登录工人身份」）。 */
  onNeedLogin?: () => void
}

/** 报工页页头的工人身份条。 */
export function WorkerBar({ onWorkerChange, onNeedLogin }: Props) {
  const [worker, setWorker] = useState<CurrentWorker | null>(() => getCachedWorker())
  const [switching, setSwitching] = useState(false)
  const [workerNo, setWorkerNo] = useState('')
  const [pin, setPin] = useState('')
  const [message, setMessage] = useState('')

  const refresh = useCallback(async () => {
    const res = await fetchCurrentWorker()
    if (res.success && res.data) {
      setWorker(res.data)
      onWorkerChange?.(res.data)
    } else {
      // 401 / 闲置超时 / 未登录：**回落成未登录**（不静默保留上一个人的名字）
      clearWorkerSession()
      setWorker(null)
      onWorkerChange?.(null)
      setMessage(res.message || '')
    }
  }, [onWorkerChange])

  useEffect(() => {
    void refresh()
    // 只在挂载时对齐一次服务端真值；后续由切换/报工 401 触发
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const submitSwitch = useCallback(async () => {
    if (!workerNo.trim() || !pin.trim()) {
      setMessage('请输入工号与 PIN')
      return
    }
    setMessage('')
    const res = await switchWorker(workerNo.trim(), pin.trim())
    if (!res.success || !res.data) {
      setMessage(res.message || '切换失败，请重试')
      return
    }
    setWorker(res.data as CurrentWorker)
    onWorkerChange?.(res.data as CurrentWorker)
    setSwitching(false)
    setWorkerNo('')
    setPin('')
  }, [workerNo, pin, onWorkerChange])

  return (
    <View className='worker-bar'>
      <View className='worker-bar__row'>
        <Text className='worker-bar__label'>
          {worker ? `当前工人：${worker.worker_name || '未署名'}` : '当前工人：未登录'}
        </Text>
        {worker?.worker_no ? (
          <Text className='worker-bar__no'>工号 {worker.worker_no}</Text>
        ) : null}
        <Button
          className='worker-bar__action'
          size='mini'
          onClick={() => {
            if (worker) {
              setSwitching((prev) => !prev)
            } else {
              onNeedLogin?.()
            }
          }}
        >
          {worker ? (switching ? '取消' : '切换工人') : '登录工人身份'}
        </Button>
      </View>

      {switching ? (
        <View className='worker-bar__switch'>
          <Input
            className='worker-bar__input'
            type='text'
            placeholder='工号'
            value={workerNo}
            onInput={(event) => setWorkerNo(event.detail.value)}
          />
          <Input
            className='worker-bar__input'
            password
            placeholder='PIN'
            value={pin}
            onInput={(event) => setPin(event.detail.value)}
          />
          <Button className='worker-bar__action' size='mini' onClick={submitSwitch}>
            确认切换
          </Button>
        </View>
      ) : null}

      {message ? <Text className='worker-bar__message'>{message}</Text> : null}
      <Text className='worker-bar__hint'>
        每笔报工都记到上面这个人头上；闲置 {worker?.idle_minutes ?? 15} 分钟自动登出
      </Text>
    </View>
  )
}

export default WorkerBar
