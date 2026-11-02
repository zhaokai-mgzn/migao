// case_ids: BM-057
/**
 * **跨端一致性守卫：小程序工人登录表单 ≟ 终端 `/w/` 的 `loginView()`**（issue #8194）
 *
 * ## 治的形态：「同一件事在两个端各写一份，然后各自漂」
 *
 * 工人登录在两处落地：终端（`frontend/worker-h5`，`/w/`）与小程序（`frontend/bmini-app`，
 * weapp + `/b/` H5）。改前两边的标题 / 副标题 / 字段标签 / 按钮**没有一处相同**：
 * `/w/` 是「工人报工 / 工号 + PIN 登录（手机 / PAD 均可，无需微信）/ 企业编码（向商家索取）→ 工号 → PIN /
 * 登 录」，小程序是「工人登录 / 用工号 + PIN 登录，登录后每笔报工都记到这个人头上 / 工号 → PIN →
 * 设备标签 → 企业编码 / 登录」。两个端讲同一件事，却像两个产品；而**没有任何判据会因此变红**
 * —— 两边的测试各自只断言自己那一份文案（= 互为镜像的空断言）。
 *
 * 本守卫把「**逐字相等**」变成可执行判据：**真值 = `/w/` 的 `render.mjs::loginView()`**（基准 UI，
 * 不是手抄的期望值），bmini 一侧 = 共享组件 `src/components/WorkerLoginForm.tsx` 的常量与字段序列。
 *
 * | # | 判据 | 回归时会怎么红 |
 * |---|---|---|
 * | 1 | 标题 / 副标题 / 按钮文案逐字相等 | 改任一处（任一端）⇒ 具名红 |
 * | 2 | 三个字段标签**逐字且同序**相等（企业编码 → 工号 → PIN） | 改一个标签 / 换顺序 ⇒ 具名红 |
 * | 3 | **不出现「设备标签」字段**（`/w/` 没有它；它只留在三角色登录页的工人 tab，不在本单范围） | 加回设备标签 ⇒ 红 |
 * | 4 | 渲染面与上面解析的同一份（标题 → 副标题 → 三字段（顺序）→ 按钮），错误位在**字段上方** | 组件改了 JSX 顺序而常量没改 ⇒ 红（判据从**渲染结果**取，不是从源码猜） |
 * | 5 | 注入即红（真语料上做内存变异）：改一个标签 / 换顺序 / 改副标题（**两侧各自**）⇒ 判红并具名 | 判据退化成恒真 ⇒ 红 |
 *
 * ## 边界（照实登记，§19.1）
 * ① 判的是**文案与顺序**，不是像素：配色 / 字号 / 间距 / 390×844 的视觉对比交给多模态验收
 *    （`migao-dev-flow` §15.7 那轮读图），本判据不越权替它下结论；
 * ② 射程 = 本组件渲染出的登录表单那一块。🔴 **报工页在 `unauthorized` 态不得有页头**
 *    （用户 2026-10-31 裁定：`/w/` 的登录屏只有一张卡片，页头 = 登录后的页面身份）——
 *    这条是**本次要求的可见一致性**，判据在 `tests/worker-report-login.test.tsx` 的 ① / ②
 *    （未登录 ⇒ 取不到 `worker-report-header` / 「扫码报工」；登录后出现）；**登录后的页头**
 *    （`扫码报工` + 当前工人）仍不在本跨端判据内（它没有 `/w/` 的对应物）；
 * ③ 三角色登录页（`pages/auth/login` 的工人 tab）**有意不在面内** —— 它是常规入口，
 *    带「设备标签」；本单不改它，也不让本判据把它钉成「必须像 `/w/`」。
 */
import fs from 'fs'
import path from 'path'
import React from 'react'
import { render, screen, fireEvent, act } from '@testing-library/react'
import { BMINI_ROOT, stripComments } from './helpers/h5PlatformLists'

/** `/w/` 的基准 UI（真值）：`loginView()` 就在这一份里 */
const WORKER_H5_RENDER = path.join(BMINI_ROOT, '..', 'worker-h5', 'src', 'render.mjs')
const COMPONENT_FILE = 'src/components/WorkerLoginForm.tsx'

export interface LoginCopy {
  title: string
  subtitle: string
  /** 字段标签，**按渲染顺序** */
  labels: string[]
  button: string
  /** 是否出现「设备标签」字段（`/w/` 没有 ⇒ bmini 也必须没有） */
  deviceLabelField: boolean
}

export interface BminiLoginCopy extends LoginCopy {
  /** 字段键序列（防「标签对了但字段接错」：企业编码 → 工号 → PIN） */
  fields: string[]
}

function read(rel: string): string {
  return fs.readFileSync(path.join(BMINI_ROOT, rel), 'utf8')
}

/** `/w/` 一侧：从 `loginView()` 的真语料里抽标题 / 副标题 / 三标签 / 按钮（顺序 = 源码顺序） */
export function h5LoginCopy(source: string): LoginCopy {
  const match = source.match(/function loginView\(state\) \{([\s\S]*?)\n\}/)
  const body = match ? match[1] : ''
  const pick = (re: RegExp): string => (body.match(re) ?? [])[1] ?? ''
  return {
    title: pick(/class="wh5-title">([^<]+)</),
    subtitle: pick(/class="wh5-sub">([^<]+)</),
    labels: Array.from(body.matchAll(/class="wh5-label">([^<]+)<input/g)).map((m) => m[1]),
    button: pick(/class="wh5-primary" type="button">([^<]+)<\/button>/),
    deviceLabelField: stripComments(body).includes('设备标签'),
  }
}

/**
 * 抽「字段声明数组」那段源码（`export const WORKER_LOGIN_FIELDS = [ … ]`）。
 * 🔴 必须从**声明**起（`export const …`）—— 从别处的提及起会把接口里的 `label: string`
 * 也当字段读进去（第一次写这条判据时就踩过：两个注入红证「莫名变红」）。
 */
export function fieldsBlock(source: string): string {
  return (source.match(/export const WORKER_LOGIN_FIELDS[\s\S]*?\n\]/) ?? [''])[0]
}

/** 小程序一侧：从共享组件的源码里抽同一组常量与字段序列 */
export function bminiLoginCopy(source: string): BminiLoginCopy {
  const constant = (name: string): string =>
    (source.match(new RegExp(`export const ${name} = '([^']*)'`)) ?? [])[1] ?? ''
  const block = fieldsBlock(source)
  return {
    title: constant('WORKER_LOGIN_TITLE'),
    subtitle: constant('WORKER_LOGIN_SUBTITLE'),
    labels: Array.from(block.matchAll(/label: '([^']*)'/g)).map((m) => m[1]),
    fields: Array.from(block.matchAll(/key: '([^']*)'/g)).map((m) => m[1]),
    button: constant('WORKER_LOGIN_SUBMIT_TEXT'),
    deviceLabelField: stripComments(source).includes('设备标签'),
  }
}

/** 核心判定（真判据与注入式红证**共用同一份**，`migao-dev-flow` §23.5） */
export function parityProblems(h5: LoginCopy, bmini: LoginCopy): string[] {
  const problems: string[] = []
  if (h5.title !== bmini.title) {
    problems.push(`标题不一致：/w/「${h5.title}」 vs bmini「${bmini.title}」`)
  }
  if (h5.subtitle !== bmini.subtitle) {
    problems.push(`副标题不一致：/w/「${h5.subtitle}」 vs bmini「${bmini.subtitle}」`)
  }
  if (h5.button !== bmini.button) {
    problems.push(`按钮文案不一致：/w/「${h5.button}」 vs bmini「${bmini.button}」`)
  }
  if (h5.labels.length !== bmini.labels.length) {
    problems.push(
      `字段个数不一致：/w/ ${h5.labels.length} 个（${h5.labels.join(' / ')}）vs bmini ${bmini.labels.length} 个（${bmini.labels.join(' / ')}）`,
    )
  }
  const count = Math.max(h5.labels.length, bmini.labels.length)
  for (let i = 0; i < count; i += 1) {
    if (h5.labels[i] !== bmini.labels[i]) {
      problems.push(
        `第 ${i + 1} 个字段标签不一致（含顺序）：/w/「${h5.labels[i] ?? '（缺）'}」 vs bmini「${bmini.labels[i] ?? '（缺）'}」`,
      )
    }
  }
  if (bmini.deviceLabelField) {
    problems.push('bmini 登录表单出现了「设备标签」字段：/w/ 的 loginView() 没有它（它只在三角色登录页的工人 tab）')
  }
  if (h5.deviceLabelField) {
    problems.push('/w/ 的 loginView() 出现了「设备标签」字段：基准 UI 变了，先复核本判据的口径而不是改这里')
  }
  return problems
}

function realCopy(): { h5: LoginCopy; bmini: BminiLoginCopy } {
  return {
    h5: h5LoginCopy(fs.readFileSync(WORKER_H5_RENDER, 'utf8')),
    bmini: bminiLoginCopy(read(COMPONENT_FILE)),
  }
}

describe('跨端一致性：小程序工人登录表单 ≟ /w/（issue #8194）', () => {
  it('真语料零差异：/w/ 的 loginView() 与 WorkerLoginForm 的标题/副标题/三字段及顺序/按钮逐字相等', () => {
    const { h5, bmini } = realCopy()
    // 反空跑：两侧都真的抽到了（否则「两边都空」会让下面的相等恒真）
    expect(h5.title).not.toBe('')
    expect(h5.subtitle).not.toBe('')
    expect(h5.labels).toHaveLength(3)
    expect(h5.button).not.toBe('')
    expect(bmini.labels).toHaveLength(3)
    // 字段键序列：企业编码 → 工号 → PIN（标签对了但字段接错 ⇒ 这里红）
    expect(bmini.fields).toEqual(['enterpriseCode', 'workerNo', 'pin'])

    expect(parityProblems(h5, bmini)).toEqual([])
  })

  it('🔴 判据 5 红证：改一个标签（内存变异）⇒ 判红并具名', () => {
    const { h5, bmini } = realCopy()
    const mutated = bminiLoginCopy(
      read(COMPONENT_FILE).replace("label: '工号'", "label: '工号（必填）'"),
    )
    // 变异生效自证：否则红证会退化成「什么都没改也红」的空断言
    expect(mutated.labels).not.toEqual(bmini.labels)
    const problems = parityProblems(h5, mutated)
    expect(problems.join('\n')).toContain('第 2 个字段标签不一致')
    expect(problems.join('\n')).toContain('工号（必填）')
  })

  it('🔴 判据 5 红证：把两个字段换顺序（内存变异）⇒ 判红（顺序也是判据）', () => {
    const { h5, bmini } = realCopy()
    const source = read(COMPONENT_FILE)
    const block = fieldsBlock(source)
    // 把「企业编码」与「工号」两行对调：标签**集合没变**，顺序变了（这正是「换顺序」的形态）
    const lines = block.split('\n')
    const enterpriseLine = lines.find((line) => line.includes("key: 'enterpriseCode'")) ?? ''
    const workerNoLine = lines.find((line) => line.includes("key: 'workerNo'")) ?? ''
    expect(enterpriseLine).not.toBe('')
    expect(workerNoLine).not.toBe('')
    const reordered = lines
      .map((line) => {
        if (line === enterpriseLine) return workerNoLine
        if (line === workerNoLine) return enterpriseLine
        return line
      })
      .join('\n')
    expect(reordered).not.toBe(block)
    const mutated = bminiLoginCopy(source.replace(block, reordered))
    // 变异生效自证：标签集合仍是那三个（否则红可能只是「改坏了」）
    expect([...mutated.labels].sort()).toEqual([...bmini.labels].sort())
    expect(mutated.labels[0]).toBe('工号')
    expect(parityProblems(h5, mutated).join('\n')).toContain('第 1 个字段标签不一致')
  })

  it('🔴 判据 5 红证：改 /w/ 一侧的副标题（反向变异）⇒ 同样判红（判据是双边的）', () => {
    const { bmini } = realCopy()
    const h5 = h5LoginCopy(
      fs
        .readFileSync(WORKER_H5_RENDER, 'utf8')
        .replace('工号 + PIN 登录（手机 / PAD 均可，无需微信）', '工号 + PIN 登录'),
    )
    expect(h5.subtitle).toBe('工号 + PIN 登录')
    expect(parityProblems(h5, bmini).join('\n')).toContain('副标题不一致')
  })

  it('🔴 判据 3 红证：把「设备标签」塞回表单 ⇒ 判红', () => {
    const { h5 } = realCopy()
    const withDeviceLabel: BminiLoginCopy = {
      ...bminiLoginCopy(read(COMPONENT_FILE)),
      deviceLabelField: true,
    }
    expect(parityProblems(h5, withDeviceLabel).join('\n')).toContain('设备标签')
  })

  it('判据 4：渲染面同序（标题 → 副标题 → 企业编码 → 工号 → PIN → 按钮），且错误位在字段上方', async () => {
    const h5 = h5LoginCopy(fs.readFileSync(WORKER_H5_RENDER, 'utf8'))
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const WorkerLoginForm = require('../src/components/WorkerLoginForm').default as React.ComponentType<any>
    const onSubmit = jest.fn(async () => ({ ok: true as const }))

    render(React.createElement(WorkerLoginForm, { onSubmit }))

    const form = screen.getByTestId('worker-login-form')
    const text = form.textContent ?? ''
    expect(text).toContain(h5.title)
    expect(text).toContain(h5.subtitle)

    // 字段顺序从**渲染结果**取（不是从源码猜）：三个 input 的父容器文本 = 该字段标签
    const inputs = Array.from(form.querySelectorAll('input'))
    expect(inputs).toHaveLength(3)
    expect(inputs.map((input) => (input.parentElement?.textContent ?? '').trim())).toEqual(h5.labels)

    // 按钮文案逐字（含 `登 录` 中间那个空格）
    const button = screen.getByTestId('worker-login-submit')
    expect(button.textContent).toBe(h5.button)

    // 错误位：校验失败 ⇒ 上屏，且**在字段之上**（与 /w/ 的 `wh5-error` 同位）
    await act(async () => {
      fireEvent.click(button)
    })
    const error = screen.getByTestId('worker-login-error')
    expect(error.textContent).toBe('请输入工号与 PIN')
    const firstInput = screen.getByTestId('worker-login-enterprise-code')
    // eslint-disable-next-line no-bitwise
    expect(error.compareDocumentPosition(firstInput) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    // 校验没过 ⇒ 不提交（否则「空表单也能登录」会把错误位变成装饰）
    expect(onSubmit).not.toHaveBeenCalled()
  })
})
