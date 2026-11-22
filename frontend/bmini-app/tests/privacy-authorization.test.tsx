// case_ids: BM-067
/**
 * 微信隐私授权弹窗（选中的照片或视频信息 / 摄像头 / 麦克风）—— issue #9011
 *
 * ## 判据（每条都能单独变红）
 *
 * | # | 判据 | 怎么单独变红 |
 * |---|---|---|
 * | ① | `setupPrivacyAuthorization` **幂等**：连调两次只 bind 一次、返回**同一个** unsubscribe | 去掉 `if (unsubscribeAll) return` ⇒ bind 2 次、判据红 |
 * | ② | `resolvePrivacy(true)` 的 payload = `{ event: 'agree', buttonId: 'agree-btn' }`；`false` = `{ event: 'disagree' }` | 删 `buttonId`（微信不认，pending 接口永不继续）⇒ 红 |
 * | ③ | 多个隐私接口同时 pending ⇒ **每个 resolve 都被回应**（只留最后一个 ⇒ 先到的接口永远 pending） | 把队列改成单变量 ⇒ 第一个 resolve 不被调用 ⇒ 红 |
 * | ④ | h5 环境 **no-op 且不抛错**（taro-h5 的实现是 `temporarilyNotSupport` 的 stub，**函数存在但不是真实现**） | 只按 `typeof` 判 ⇒ h5 里真去调 stub ⇒ 红 |
 * | ⑤ | 弹窗文案**逐字等于后台申报**（标题 / 正文 / 三条用途 / 拒绝说明 / 指引链接） | 任改一个字 ⇒ 红（申报内容与代码不符本身就是驳回理由） |
 * | ⑥ | 只有「同意并继续」是 `open-type='agreePrivacyAuthorization'` 且 `id='agree-btn'`；「暂不同意」**不是** open-type 按钮 | 给拒绝按钮加 openType ⇒ 平台会当成同意按钮 ⇒ 红 |
 * | ⑦ | 🔴 类级守卫：**会（直接或经依赖传递）触发隐私接口的页面**必须渲染 `<PrivacyPopup />`（那一组页面**现取**，不手抄清单） | 新增一个调 `Taro.scanCode` 的页面却不挂弹窗 ⇒ 红并具名 |
 * | ⑧ | 注册点**只有一处**（`app.tsx`）：页面不得各自注册（每页注册 ⇒ 幂等失效、resolve 互相覆盖） | 任一页面里加 `setupPrivacyAuthorization()` ⇒ 红 |
 *
 * ## 为什么用**静态 import**（不 `jest.resetModules()`）
 *
 * 模块级状态（`registered` / pending 队列）确实会跨用例残留，但 `jest.resetModules()` 会连
 * **React** 一起重置 ⇒ 组件拿到的是另一份 React（`Cannot read properties of null (reading 'useState')`，
 * 实测踩过）。所以：组件与 `utils/privacy` **同一个模块实例**（静态 import），h5 那一态用
 * `jest.isolateModules` 单独取一份（它只拉 Taro + platform，**不拉 React**，安全）。
 *
 * 边界（照实登记）：本文件**不**验证微信真机上的授权链路（要真机 + 后台申报的隐私指引），
 * 那是验收面的读数；这里钉的是「传给微信的 payload 与挂载面」。
 */
import fs from 'fs'
import path from 'path'
import React from 'react'
import { act, fireEvent, render, screen } from '@testing-library/react'
import Taro from '@tarojs/taro'
import * as privacy from '../src/utils/privacy'
import PrivacyPopup from '../src/components/privacy/PrivacyPopup'
import { SRC_DIR, stripComments, walk } from './helpers/h5PlatformLists'

/** 微信交给开发者的 `resolve`（官方 `onNeedPrivacyAuthorization(listener)` 的第一个参数） */
type PrivacyListener = (resolve: (option: any) => void, eventInfo: { referrer: string }) => void

/** 取已注册的监听函数（`setupPrivacyAuthorization` 幂等 ⇒ 这里再调一次不会多 bind） */
function needPrivacyListener(): PrivacyListener {
  privacy.setupPrivacyAuthorization()
  const call = (Taro.onNeedPrivacyAuthorization as unknown as jest.Mock).mock.calls[0]
  expect(call).toBeTruthy()
  return call[0] as PrivacyListener
}

/** 触发一次 needPrivacyAuthorization（等价于用户点了扫码 / 拍照 / 录音），返回微信侧的 resolve */
function trigger(referrer: string): jest.Mock {
  const resolve = jest.fn()
  act(() => needPrivacyListener()(resolve, { referrer }))
  return resolve
}

describe('微信隐私授权（issue #9011）', () => {
  it('① setupPrivacyAuthorization 幂等：注册两次只 bind 一次，返回同一个 unsubscribe', () => {
    const first = privacy.setupPrivacyAuthorization()
    const second = privacy.setupPrivacyAuthorization()
    expect(second).toBe(first)
    expect(Taro.onNeedPrivacyAuthorization).toHaveBeenCalledTimes(1)
    expect(typeof first).toBe('function')
  })

  it('② agree 的 payload 必带 buttonId（官方字段名），disagree 只带 event', () => {
    const agreeResolver = trigger('chooseImage')
    privacy.resolvePrivacy(true)
    expect(agreeResolver).toHaveBeenCalledWith({ event: 'agree', buttonId: 'agree-btn' })

    const disagreeResolver = trigger('getRecorderManager')
    privacy.resolvePrivacy(false)
    expect(disagreeResolver).toHaveBeenCalledWith({ event: 'disagree' })
  })

  it('③ 多个隐私接口同时 pending：每个 resolve 都被回应（先到的不会永远 pending）', () => {
    const first = trigger('chooseImage')
    const second = trigger('scanCode')
    privacy.resolvePrivacy(true)
    expect(first).toHaveBeenCalledTimes(1)
    expect(second).toHaveBeenCalledTimes(1)
    expect(first).toHaveBeenCalledWith({ event: 'agree', buttonId: 'agree-btn' })
  })

  it('④ h5 环境 no-op：不注册监听、不抛错、不碰 stub', () => {
    const previous = process.env.TARO_ENV
    process.env.TARO_ENV = 'h5'
    try {
      jest.isolateModules(() => {
        // 只拉 Taro + platform（**不拉 React**），见文件头「为什么用静态 import」
        const h5Taro = require('@tarojs/taro').default
        const h5Privacy: typeof privacy = require('../src/utils/privacy')
        const unsubscribe = h5Privacy.setupPrivacyAuthorization()
        expect(h5Taro.onNeedPrivacyAuthorization).not.toHaveBeenCalled()
        expect(() => {
          unsubscribe()
          h5Privacy.resolvePrivacy(true)
          h5Privacy.openPrivacyContract()
        }).not.toThrow()
        // h5 的 openPrivacyContract 是 stub ⇒ 不调它，改走说明弹窗（不留一个点了没反应的死链）
        expect(h5Taro.openPrivacyContract).not.toHaveBeenCalled()
        expect(h5Taro.showModal).toHaveBeenCalledTimes(1)
      })
    } finally {
      if (previous === undefined) delete (process.env as any).TARO_ENV
      else process.env.TARO_ENV = previous
    }
  })

  it('⑤ 文案逐字等于小程序后台申报的三类用途', () => {
    render(<PrivacyPopup />)
    trigger('chooseImage')

    expect(screen.getByText('隐私保护提示')).toBeTruthy()
    expect(
      screen.getByText('为了完成扫码、拍照与语音输入，我们需要在下列场景使用你的信息：'),
    ).toBeTruthy()
    expect(
      screen.getByText(
        '选中的照片或视频信息：用于入库、出库、盘点、返修补打的现场照片记录，以及 AI 识图问答（仅在你主动选择时读取）',
      ),
    ).toBeTruthy()
    expect(
      screen.getByText('摄像头：用于扫描产品与水洗唛上的二维码/条码，以及拍摄作业现场照片'),
    ).toBeTruthy()
    expect(
      screen.getByText('麦克风：用于语音输入转文字（按住说话时录音，松开即停止）'),
    ).toBeTruthy()
    expect(screen.getByText('查看完整《隐私保护指引》')).toBeTruthy()
    expect(
      screen.getByText('不同意不影响你浏览，但无法使用扫码、拍照与语音功能。'),
    ).toBeTruthy()
  })

  it('⑥ 只有同意按钮带 open-type，且 id 与 resolve 的 buttonId 逐字相等', () => {
    render(<PrivacyPopup />)
    expect(screen.queryByTestId('privacy-popup')).toBeNull()
    const resolve = trigger('chooseImage')
    expect(screen.getByTestId('privacy-popup')).toBeTruthy()

    const agree = screen.getByText('同意并继续')
    expect(agree.getAttribute('id')).toBe(privacy.AGREE_BUTTON_ID)
    expect(agree.getAttribute('id')).toBe('agree-btn')
    expect(agree.getAttribute('open-type')).toBe('agreePrivacyAuthorization')

    const disagree = screen.getByText('暂不同意')
    expect(disagree.getAttribute('open-type')).toBeNull()

    fireEvent.click(agree)
    expect(resolve).toHaveBeenCalledWith({ event: 'agree', buttonId: 'agree-btn' })
    // 做出选择后弹窗收起（用户不会再看到「点了没反应」）
    expect(screen.queryByTestId('privacy-popup')).toBeNull()
  })

  it('⑦ 拒绝分支：点「暂不同意」⇒ resolve(disagree)，不发 agree', () => {
    render(<PrivacyPopup />)
    const resolve = trigger('scanCode')

    fireEvent.click(screen.getByText('暂不同意'))
    expect(resolve).toHaveBeenCalledWith({ event: 'disagree' })
    expect(resolve).not.toHaveBeenCalledWith({ event: 'agree', buttonId: 'agree-btn' })
  })

  it('⑧ 「查看完整《隐私保护指引》」走 Taro.openPrivacyContract（小程序端）', () => {
    render(<PrivacyPopup />)
    trigger('chooseImage')

    fireEvent.click(screen.getByTestId('privacy-contract-link'))
    expect(Taro.openPrivacyContract).toHaveBeenCalledTimes(1)
  })

  it('⑨ 类级守卫：会触发隐私接口的页面必须挂 <PrivacyPopup />（页面集合现取）', () => {
    const pages = privacyTriggerPages()
    const offenders = pages.filter((page) => {
      const text = fs.readFileSync(path.join(SRC_DIR, page), 'utf8')
      return !/components\/privacy\/PrivacyPopup/.test(text) || !/<PrivacyPopup\s*\/>/.test(text)
    })
    expect(offenders).toEqual([])
    // 射程自证：这一组页面**真的被算出来了**（否则「0 命中 = 通过」就是假绿）
    expect(pages.length).toBeGreaterThanOrEqual(9)
  })

  it('⑩ 注册点只有一处：app.tsx 注册，页面不得各自注册', () => {
    const app = fs.readFileSync(path.join(SRC_DIR, 'app.tsx'), 'utf8')
    expect(app).toContain('setupPrivacyAuthorization()')
    const selfRegistered = walk(SRC_DIR, (name) => /\.tsx$/.test(name))
      .filter((file) => path.relative(SRC_DIR, file).startsWith('pages/'))
      .filter((file) => /setupPrivacyAuthorization\s*\(/.test(stripComments(fs.readFileSync(file, 'utf8'))))
      .map((file) => path.relative(SRC_DIR, file).split(path.sep).join('/'))
    expect(selfRegistered).toEqual([])
  })
})

// ── 「哪些页面会触发隐私接口」的唯一抽取实现（判据 ⑨ 用它现取，不手抄清单）──────────────
/** 隐私接口（三类信息对应的触发面；与小程序后台申报的《用户隐私保护指引》一一对应） */
const PRIVACY_API = /Taro\.(chooseImage|chooseMedia|scanCode|getRecorderManager)\s*\(/

function relativeImports(file: string): string[] {
  const text = stripComments(fs.readFileSync(file, 'utf8'))
  const out: string[] = []
  for (const match of text.matchAll(/from\s+['"](\.[^'"]+)['"]/g)) {
    const base = path.resolve(path.dirname(file), match[1])
    for (const candidate of [
      `${base}.ts`,
      `${base}.tsx`,
      path.join(base, 'index.ts'),
      path.join(base, 'index.tsx'),
    ]) {
      if (fs.existsSync(candidate)) out.push(candidate)
    }
  }
  return out
}

/**
 * 会（直接或经依赖传递）调用隐私接口的页面，返回**相对 `src/` 的 posix 路径**。
 *
 * 为什么要传递：页面自己往往不直接调 `Taro.chooseImage` —— 它 import `utils/imageUpload`
 * （聊天页）或 `utils/voice`；只扫页面源码会漏掉真实触发面（漏挂弹窗 = 工人点了没反应）。
 */
function privacyTriggerPages(): string[] {
  const cache = new Map<string, boolean>()
  const triggers = (file: string, seen: Set<string>): boolean => {
    if (cache.has(file)) return cache.get(file) as boolean
    if (seen.has(file)) return false
    seen.add(file)
    const direct = PRIVACY_API.test(stripComments(fs.readFileSync(file, 'utf8')))
    const result = direct || relativeImports(file).some((dep) => triggers(dep, seen))
    cache.set(file, result)
    return result
  }
  return walk(path.join(SRC_DIR, 'pages'), (name) => name.endsWith('.tsx'))
    .filter((file) => triggers(file, new Set()))
    .map((file) => path.relative(SRC_DIR, file).split(path.sep).join('/'))
    .sort()
}
