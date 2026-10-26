// case_ids: AU-014
/**
 * 登录自检探针（issue #7825）—— 让「又掉线了」变成可读的一行读数。
 *
 * 判据（每条都能单独变红）：
 * 1. 环形缓冲：按时间**追加**、超上限**丢最旧**（不是丢最新）；
 * 2. 坏数据（非法 JSON / 非数组）⇒ 空表，不抛；
 * 3. 面板**默认不显示**（`shouldShowAuthDiag()` 在普通地址下为 false）；`?diag=1` 才显示；
 * 4. 面板只列 kind / 时间 / detail —— 不是凭据面（写入侧不接收 token，测试用「不出现 token 值」反证）。
 */
import '@testing-library/jest-dom'
import Taro from '@tarojs/taro'
import { render, screen } from '@testing-library/react'
import AuthDiagPanel, { shouldShowAuthDiag } from '../src/components/auth/AuthDiagPanel'
import {
  AUTH_DIAG_MAX,
  AUTH_DIAG_STORAGE_KEY,
  clearAuthDiag,
  formatAuthDiagTime,
  readAuthDiag,
  recordAuthDiag,
} from '../src/utils/authDiag'

describe('登录自检探针（issue #7825）', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    ;(Taro as any).__clearStorage()
    window.history.replaceState({}, '', '/b/')
  })

  it('环形缓冲：按时间追加；超过上限丢**最旧**的', () => {
    for (let i = 0; i < AUTH_DIAG_MAX + 5; i++) {
      recordAuthDiag('refresh_ok', `n=${i}`)
    }

    const entries = readAuthDiag()
    expect(entries).toHaveLength(AUTH_DIAG_MAX)
    expect(entries[entries.length - 1].detail).toBe(`n=${AUTH_DIAG_MAX + 4}`)
    expect(entries[0].detail).toBe('n=5')
  })

  it('坏数据 ⇒ 空表（不抛、不崩登录页）', () => {
    Taro.setStorageSync(AUTH_DIAG_STORAGE_KEY, 'not-json')
    expect(readAuthDiag()).toEqual([])

    Taro.setStorageSync(AUTH_DIAG_STORAGE_KEY, JSON.stringify({ kind: 'refresh_ok' }))
    expect(readAuthDiag()).toEqual([])

    clearAuthDiag()
    expect(readAuthDiag()).toEqual([])
  })

  it('时间格式：MM-DD HH:mm:ss（本机时区，补零）', () => {
    expect(formatAuthDiagTime(new Date(2026, 9, 26, 9, 5, 7).getTime())).toBe('10-26 09:05:07')
  })

  it('面板默认不显示；`?diag=1` 才显示（路由参数与地址两种形态都认）', () => {
    expect(shouldShowAuthDiag()).toBe(false)

    window.history.replaceState({}, '', '/b/?diag=1')
    expect(shouldShowAuthDiag()).toBe(true)

    window.history.replaceState({}, '', '/b/')
    ;(Taro.getCurrentInstance as jest.Mock).mockReturnValueOnce({ router: { params: { diag: '1' } } })
    expect(shouldShowAuthDiag()).toBe(true)
  })

  it('面板逐条列出记录，且不是凭据面（只有 kind / 时间 / detail）', () => {
    recordAuthDiag('refresh_401', '缺少 Refresh Token')
    recordAuthDiag('qr_login_ok', 'user=u1')

    render(<AuthDiagPanel />)

    expect(screen.getByTestId('auth-diag-panel')).toBeInTheDocument()
    const rows = screen.getAllByTestId('auth-diag-row')
    expect(rows).toHaveLength(2)
    expect(rows[0].textContent).toContain('qr_login_ok')
    expect(rows[0].textContent).toContain('user=u1')
    expect(rows[1].textContent).toContain('refresh_401')
    // 反证「不是凭据面」：面板里不许出现 token / JWT / Bearer 这类凭据形态的字（文案里提到「密码」是免责声明）
    expect(screen.getByTestId('auth-diag-panel').textContent).not.toMatch(/tok-|eyJ|Bearer/i)
  })
})
