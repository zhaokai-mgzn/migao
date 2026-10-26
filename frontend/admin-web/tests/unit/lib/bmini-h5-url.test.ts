// case_ids: UI-064, MC-012
// （UI-064 = 「手机端入口二维码」用例；MC-012 = tests/unit_ci_workflows/ 的结构类 L0 不变式惯例。
//   本文件是 growth gate 对 frontend/admin-web/src/lib/bmini-h5-url.ts 要求的同名单测。）
import { describe, it, expect, vi, afterEach } from 'vitest'

import { buildMobileEntryUrl, getBminiH5Url } from '@/lib/bmini-h5-url'

// issue #5668：B 端 h5（手机端入口）地址的**唯一读取点**。
// 判据两面：① 有值 ⇒ 逐字返回（含首尾空白裁剪）；② 无值/空/纯空白 ⇒ 空串 ——
// 调用方据此渲染「移动端地址未配置」而**不画假码**（画了假码，用户扫出白屏而页面看起来正常）。
describe('getBminiH5Url — 手机端入口地址的单一真值（issue #5668）', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('有值时逐字返回配置值', () => {
    vi.stubEnv('NEXT_PUBLIC_BMINI_H5_URL', 'https://app.migaozn.com/b/')
    expect(getBminiH5Url()).toBe('https://app.migaozn.com/b/')
  })

  it('首尾空白被裁剪（构建期注入常带换行 ⇒ 不裁会画出一个带空白的码）', () => {
    vi.stubEnv('NEXT_PUBLIC_BMINI_H5_URL', '  https://bmini-entry.invalid/b/\n')
    expect(getBminiH5Url()).toBe('https://bmini-entry.invalid/b/')
  })

  it('未配置 ⇒ 空串（调用方据此显示「未配置」且不画码）', () => {
    vi.stubEnv('NEXT_PUBLIC_BMINI_H5_URL', '')
    expect(getBminiH5Url()).toBe('')
  })

  it('只有空白字符 ⇒ 同样按未配置处理（不许画一个指向空白的码）', () => {
    vi.stubEnv('NEXT_PUBLIC_BMINI_H5_URL', '   ')
    expect(getBminiH5Url()).toBe('')
  })

  it('环境变量未定义 ⇒ 空串（不是 undefined / 不是抛错）', () => {
    // 刻意**不用** `vi.stubEnv(name, undefined)`：不同版本的 vitest 对 undefined 的处置不同
    // （可能落成字符串 'undefined'）⇒ 这条判据会变成"看版本"的。直接删除键，测完还原。
    const original = process.env.NEXT_PUBLIC_BMINI_H5_URL
    delete process.env.NEXT_PUBLIC_BMINI_H5_URL
    try {
      expect(getBminiH5Url()).toBe('')
    } finally {
      if (original === undefined) delete process.env.NEXT_PUBLIC_BMINI_H5_URL
      else process.env.NEXT_PUBLIC_BMINI_H5_URL = original
    }
  })
})

// issue #7825（扫码即登录）：二维码内容 = 裸地址 + 可选 `?qr=<票据>`。
// 拼 query 只许发生在**单一真值模块**里（组件里拼 = 第二份副本，判据见
// tests/unit_ci_workflows/test_frontend_bmini_entry_single_source.py）。
describe('buildMobileEntryUrl — 二维码内容派生（issue #7825）', () => {
  const BASE = 'https://bmini-entry.invalid/b/'

  it('无票据 ⇒ 原样返回裸地址（降级形态：扫码后登录）', () => {
    expect(buildMobileEntryUrl(BASE)).toBe(BASE)
    expect(buildMobileEntryUrl(BASE, '')).toBe(BASE)
    expect(buildMobileEntryUrl(BASE, null)).toBe(BASE)
  })

  it('有票据 ⇒ 追加 `?qr=<urlencoded ticket>`（jwt 里的 . 与 - 不需要编码，但大字符集必须安全）', () => {
    expect(buildMobileEntryUrl(BASE, 'a.b-c')).toBe(`${BASE}?qr=a.b-c`)
    expect(buildMobileEntryUrl(BASE, 'x+y/z=')).toBe(`${BASE}?qr=x%2By%2Fz%3D`)
  })

  it('地址已带 query ⇒ 用 & 续接（不产生两个 ?）', () => {
    expect(buildMobileEntryUrl(`${BASE}?from=pc`, 't1')).toBe(`${BASE}?from=pc&qr=t1`)
  })

  it('地址为空 ⇒ 空串（缺配置不画假码，同上一条的孪生判据）', () => {
    expect(buildMobileEntryUrl('', 't1')).toBe('')
    expect(buildMobileEntryUrl('   ', 't1')).toBe('')
  })
})
