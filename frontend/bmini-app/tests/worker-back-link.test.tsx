// case_ids: BM-064
/**
 * 工人端子页的「返回」入口（issue #8657）。
 *
 * 病：工人端页面在**手机浏览器 / 微信 / 手持标签机的全屏 WebView** 里没有系统返回键
 * （终端是 kiosk 全屏），工人做完一件事想回工作台只能靠手势或杀掉重进。
 *
 * 判据（每条都能单独变红）：
 * | # | 判据 | 红证 |
 * |---|---|---|
 * | ① | 有上一页 ⇒ `navigateBack({delta:1})`，**不** reLaunch | 改成无条件 reLaunch ⇒ 红 |
 * | ② | 🔴 没有历史（扫码短链 / 直接打开子页 / 终端冷启动）⇒ `reLaunch` 到工人工作台，**不静默失败** | 只调 navigateBack ⇒ 红 |
 * | ③ | 🔴 **类级**：`src/pages/worker/*` 的每个子页（除 home / login）都必须挂这个入口 | 新增一个子页不挂 ⇒ 红 |
 */
import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'

const navigateBack = jest.fn()
const reLaunch = jest.fn()
let pageStack: any[] = []

jest.mock('@tarojs/taro', () => ({
  __esModule: true,
  default: {
    navigateBack: (...args: any[]) => navigateBack(...args),
    reLaunch: (...args: any[]) => reLaunch(...args),
    getCurrentPages: () => pageStack,
  },
}))

import { WorkerBackLink } from '../src/components/WorkerBackLink'

describe('工人子页返回入口（issue #8657）', () => {
  beforeEach(() => {
    navigateBack.mockClear()
    reLaunch.mockClear()
  })

  it('① 有上一页 ⇒ navigateBack(delta 1)，不 reLaunch', () => {
    pageStack = [{}, {}]
    render(<WorkerBackLink />)
    fireEvent.click(screen.getByTestId('worker-back'))
    expect(navigateBack).toHaveBeenCalledWith({ delta: 1 })
    expect(reLaunch).not.toHaveBeenCalled()
  })

  it('② 没有历史 ⇒ reLaunch 到工人工作台（不静默失败）', () => {
    pageStack = [{}]
    render(<WorkerBackLink />)
    fireEvent.click(screen.getByTestId('worker-back'))
    expect(reLaunch).toHaveBeenCalledWith({ url: '/pages/worker/home/index' })
    expect(navigateBack).not.toHaveBeenCalled()
  })

  it('③ 类级：每个工人子页都挂了返回入口', () => {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const fs = require('fs')
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const path = require('path')
    const root = path.join(__dirname, '..', 'src', 'pages', 'worker')
    const pages = fs
      .readdirSync(root)
      .filter((dir: string) => dir !== 'home' && dir !== 'login')
      .filter((dir: string) => fs.existsSync(path.join(root, dir, 'index.tsx')))
    expect(pages.length).toBeGreaterThan(0)
    const missing = pages.filter(
      (dir: string) =>
        !fs.readFileSync(path.join(root, dir, 'index.tsx'), 'utf8').includes('<WorkerBackLink')
    )
    expect(missing).toEqual([])
  })
})
