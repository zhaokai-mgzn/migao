// case_ids: BM-005, BM-006
/**
 * 共用 PAD 的工人身份条（issue #4733，设计 W2/W3）—— 三条纪律各自一条断言。
 *
 * ① **提交前显示「当前工人：张三」**（数据来自服务端 `current-worker`，不是前端 state）；
 * ② **一步快速切换**：点「切换工人」→ 输工号 + PIN → 提交 ⇒ 身份条立即变新人，
 *    且**不触发** `onNeedLogin`（= 不跳走、不丢扫码上下文）；
 * ③ **闲置/失效后回落成未登录**：服务端 401 ⇒ 清本地缓存 + 显示「未登录」+ 给「登录工人身份」
 *    （**不静默保留上一个人的名字** —— 那正是「记到上一个人头上」的形态）。
 */
import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import Taro from '@tarojs/taro'
import { WorkerBar } from '../src/components/WorkerBar'
import { fetchCurrentWorker, switchWorker } from '../src/services/workerService'
import { STORAGE_KEYS } from '../src/utils/constants'

jest.mock('../src/services/workerService', () => ({
  fetchCurrentWorker: jest.fn(),
  switchWorker: jest.fn(),
}))

const mockFetch = fetchCurrentWorker as jest.Mock
const mockSwitch = switchWorker as jest.Mock

const ZHANG = {
  session_id: 'sess-1', worker_id: 'w-1', worker_no: 'W001',
  worker_name: '张三', idle_minutes: 15, idle_expires_at: '2026-09-20T10:00:00Z',
}

describe('WorkerBar（共用 PAD 三条，issue #4733）', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    ;(Taro as any).__clearStorage()
  })

  it('① 提交前显示「当前工人：张三」+ 工号（数据来自服务端 session）', async () => {
    mockFetch.mockResolvedValue({ success: true, data: ZHANG })

    render(<WorkerBar />)

    expect(await screen.findByText('当前工人：张三')).toBeTruthy()
    expect(screen.getByText('工号 W001')).toBeTruthy()
    expect(mockFetch).toHaveBeenCalledTimes(1)
  })

  it('② 一步快速切换：输工号 + PIN ⇒ 身份条变新人，且**不跳走**（onNeedLogin 不被调用）', async () => {
    mockFetch.mockResolvedValue({ success: true, data: ZHANG })
    mockSwitch.mockResolvedValue({
      success: true,
      data: { session_id: 'sess-2', worker_id: 'w-2', worker_no: 'W002', worker_name: '李四' },
    })
    const onNeedLogin = jest.fn()

    render(<WorkerBar onNeedLogin={onNeedLogin} />)
    await screen.findByText('当前工人：张三')

    fireEvent.click(screen.getByText('切换工人'))
    fireEvent.change(screen.getByPlaceholderText('工号'), { target: { value: 'W002' } })
    fireEvent.change(screen.getByPlaceholderText('PIN'), { target: { value: '135790' } })
    fireEvent.click(screen.getByText('确认切换'))

    await waitFor(() => expect(screen.getByText('当前工人：李四')).toBeTruthy())
    expect(mockSwitch).toHaveBeenCalledWith('W002', '135790')
    expect(onNeedLogin).not.toHaveBeenCalled()
  })

  it('② 切换缺 PIN ⇒ 不发请求（前端拦下，不拿半截凭据去试）', async () => {
    mockFetch.mockResolvedValue({ success: true, data: ZHANG })

    render(<WorkerBar />)
    await screen.findByText('当前工人：张三')

    fireEvent.click(screen.getByText('切换工人'))
    fireEvent.change(screen.getByPlaceholderText('工号'), { target: { value: 'W002' } })
    fireEvent.click(screen.getByText('确认切换'))

    expect(mockSwitch).not.toHaveBeenCalled()
    expect(await screen.findByText('请输入工号与 PIN')).toBeTruthy()
  })

  it('③ 会话失效（服务端 401）⇒ 回落成「未登录」+ 清本地缓存（不保留上一个人的名字）', async () => {
    Taro.setStorageSync(STORAGE_KEYS.WORKER, ZHANG)
    Taro.setStorageSync(STORAGE_KEYS.WORKER_SESSION, 'sess-1')
    mockFetch.mockResolvedValue({ success: false, message: '登录已闲置超时（默认 15 分钟），请重新登录' })

    render(<WorkerBar />)

    expect(await screen.findByText('当前工人：未登录')).toBeTruthy()
    expect(screen.getByText('登录工人身份')).toBeTruthy()
    expect(Taro.getStorageSync(STORAGE_KEYS.WORKER_SESSION)).toBe('')
  })

  it('③ 未登录时点「登录工人身份」⇒ 交给父组件跳登录页（onNeedLogin）', async () => {
    mockFetch.mockResolvedValue({ success: false, message: '未登录工人身份' })
    const onNeedLogin = jest.fn()

    render(<WorkerBar onNeedLogin={onNeedLogin} />)
    await screen.findByText('当前工人：未登录')

    fireEvent.click(screen.getByText('登录工人身份'))

    expect(onNeedLogin).toHaveBeenCalledTimes(1)
  })

  it('闲置分钟数来自服务端配置（默认 15，租户可配 5~60）', async () => {
    mockFetch.mockResolvedValue({ success: true, data: { ...ZHANG, idle_minutes: 30 } })

    render(<WorkerBar />)

    expect(await screen.findByText(/闲置 30 分钟自动登出/)).toBeTruthy()
  })
})
