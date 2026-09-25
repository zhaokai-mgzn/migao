/**
 * 首登强制改密页测试（B 端商家小程序，issue #5485）
 *
 * 覆盖: 渲染（三个密码框 + 提交 + 出口指引）、遮蔽输入、空字段/两次不一致本地拦截、
 *       提交调用、成功进主界面、失败不跳转、换账号出口
 */
// case_ids: AU-006
import React from 'react'
import { render, screen, fireEvent, act } from '@testing-library/react'

const mockChangePasswordAction = jest.fn()
const mockLogout = jest.fn()

jest.mock('../src/store/authStore', () => ({
  useAuthStore: jest.fn(() => ({
    isLoading: false,
    changePasswordAction: mockChangePasswordAction,
    logout: mockLogout,
  })),
}))

import Taro from '@tarojs/taro'
import ChangePasswordPage from '../src/pages/auth/change-password/index'

const OLD_PLACEHOLDER = '请输入初始密码'
const NEW_PLACEHOLDER = '请输入新密码'
const CONFIRM_PLACEHOLDER = '请再次输入新密码'

function fillForm(oldPwd: string, newPwd: string, confirmPwd: string) {
  fireEvent.change(screen.getByPlaceholderText(OLD_PLACEHOLDER), { target: { value: oldPwd } })
  fireEvent.change(screen.getByPlaceholderText(NEW_PLACEHOLDER), { target: { value: newPwd } })
  fireEvent.change(screen.getByPlaceholderText(CONFIRM_PLACEHOLDER), { target: { value: confirmPwd } })
}

async function clickSubmit() {
  await act(async () => {
    fireEvent.click(screen.getByText('确认修改'))
  })
}

describe('ChangePasswordPage', () => {
  beforeEach(() => {
    jest.clearAllMocks()
  })

  it('应渲染标题、三个密码字段、提交按钮与出口指引', () => {
    render(<ChangePasswordPage />)

    expect(screen.getByText('设置新密码')).toBeTruthy()
    expect(screen.getByText('原密码')).toBeTruthy()
    expect(screen.getByText('新密码')).toBeTruthy()
    expect(screen.getByText('确认新密码')).toBeTruthy()
    expect(screen.getByText('确认修改')).toBeTruthy()
    // 文案要说清「下一步做什么」（不是只说一句失败）
    expect(screen.getByText(/首次登录需先修改密码/)).toBeTruthy()
    // 出口：本页是 redirectTo 进来的、没有返回键 ⇒ 必须有换账号的路
    expect(screen.getByText('使用其他账号登录')).toBeTruthy()
  })

  it('三个密码框都是遮蔽输入（password → type="password"）', () => {
    render(<ChangePasswordPage />)

    for (const placeholder of [OLD_PLACEHOLDER, NEW_PLACEHOLDER, CONFIRM_PLACEHOLDER]) {
      const input = screen.getByPlaceholderText(placeholder) as HTMLInputElement
      expect(input.getAttribute('type')).toBe('password')
    }
  })

  it('任一字段为空 ⇒ 本地拦截、不发请求', async () => {
    render(<ChangePasswordPage />)
    fillForm('', 'new-pass-456', 'new-pass-456')
    await clickSubmit()

    expect(mockChangePasswordAction).not.toHaveBeenCalled()
    expect(Taro.showToast).toHaveBeenCalledWith(
      expect.objectContaining({ title: expect.stringContaining('原密码') }),
    )
  })

  it('两次新密码不一致 ⇒ 本地拦截、不发请求', async () => {
    render(<ChangePasswordPage />)
    fillForm('init-pass-123', 'new-pass-456', 'new-pass-457')
    await clickSubmit()

    expect(mockChangePasswordAction).not.toHaveBeenCalled()
    expect(Taro.showToast).toHaveBeenCalledWith(
      expect.objectContaining({ title: expect.stringContaining('不一致') }),
    )
  })

  it('提交 ⇒ changePasswordAction(原密码, 新密码)（AU-006）', async () => {
    mockChangePasswordAction.mockResolvedValueOnce(true)

    render(<ChangePasswordPage />)
    fillForm('init-pass-123', 'new-pass-456', 'new-pass-456')
    await clickSubmit()

    expect(mockChangePasswordAction).toHaveBeenCalledWith('init-pass-123', 'new-pass-456')
  })

  it('改密成功 ⇒ 用换发的新凭据进主界面（问米宝）', async () => {
    mockChangePasswordAction.mockResolvedValueOnce(true)

    render(<ChangePasswordPage />)
    fillForm('init-pass-123', 'new-pass-456', 'new-pass-456')
    await clickSubmit()

    expect(Taro.switchTab).toHaveBeenCalledWith({ url: '/pages/chat/index/index' })
  })

  it('改密失败（原密码不正确 / 新密码不合规）⇒ 不跳转，文案由 store 展示服务端原文', async () => {
    mockChangePasswordAction.mockResolvedValueOnce(false)

    render(<ChangePasswordPage />)
    fillForm('init-pass-123', 'short1', 'short1')
    await clickSubmit()

    expect(mockChangePasswordAction).toHaveBeenCalledTimes(1)
    expect(Taro.switchTab).not.toHaveBeenCalled()
  })

  it('「使用其他账号登录」⇒ 登出并回登录页', () => {
    render(<ChangePasswordPage />)

    fireEvent.click(screen.getByText('使用其他账号登录'))

    expect(mockLogout).toHaveBeenCalled()
    expect(Taro.redirectTo).toHaveBeenCalledWith({ url: '/pages/auth/login/index' })
  })
})