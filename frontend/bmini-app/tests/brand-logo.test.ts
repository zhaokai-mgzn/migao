// case_ids: BM-064
/**
 * 类级守卫：**生意管家的品牌标必须真的挂在登录页上，且规格/配色/缩得下去都成立**（issue #9121）。
 *
 * 需求沿革：用户 2026-11-04「我们还需要给观星台设计一个 logo」→ 2026-11-24 产品更名「生意管家」，
 * 品牌标同步换成「管家铃」：铃 = 随叫随到的服务，底座 = 经营台面，星芒 = 词元 / AI。
 *
 * 为什么要有判据（不是「看一眼图就行」）：
 * 1. 图标是**图片资源**：改名/删文件/导错尺寸，编译期不报错，只有真机上白块 —— 必须有断言；
 * 2. 微信小程序头像要 144×144，登录页要 288 以内的清晰版；导出尺寸错了肉眼在电脑上看不出来；
 * 3. 配色必须留在设计令牌内（`#2e3d5c/#48618f/#faf7f2/#d48806`），否则「移动端统一到 PC」白做；
 * 4. 登录页曾经是**文字占位**（一个「米」字），换图最常见的回归是「只加了图没删占位」⇒ 两个标并排。
 */

import { readFileSync, existsSync } from 'fs'
import { join } from 'path'

const ASSETS = join(__dirname, '..', 'src', 'assets', 'brand')
const LOGIN_TSX = join(__dirname, '..', 'src', 'pages', 'auth', 'login', 'index.tsx')
const LOGIN_SCSS = join(__dirname, '..', 'src', 'pages', 'auth', 'login', 'index.scss')

/** 读 PNG 头里的宽高（IHDR 在第 16..23 字节），不引第三方依赖 */
function pngSize(file: string): { width: number; height: number } {
  const buf = readFileSync(file)
  expect(buf.subarray(1, 4).toString('ascii')).toBe('PNG')
  return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) }
}

describe('生意管家品牌标（issue #9121）', () => {
  it('① 素材齐全：矢量源 + 微信头像 144 + 登录页 288', () => {
    for (const f of ['logo.svg', 'logo-144.png', 'logo-288.png']) {
      expect(existsSync(join(ASSETS, f))).toBe(true)
    }
  })

  it('② 尺寸正确：144 是微信要求的头像尺寸，288 是登录页 2x', () => {
    expect(pngSize(join(ASSETS, 'logo-144.png'))).toEqual({ width: 144, height: 144 })
    expect(pngSize(join(ASSETS, 'logo-288.png'))).toEqual({ width: 288, height: 288 })
  })

  it('③ 矢量源用的是设计令牌里的颜色，且是新的管家铃（不是旧的取景角 / 帘成 M）', () => {
    const svg = readFileSync(join(ASSETS, 'logo.svg'), 'utf8').toLowerCase()
    // 背景渐变 = primary-500 → primary-700
    expect(svg).toContain('#48618f')
    expect(svg).toContain('#2e3d5c')
    // 底座 = 织物米白；铃身 = 织金
    expect(svg).toContain('#faf7f2')
    expect(svg).toContain('#d48806')
    // 旧标的特征：取景角 / 帘成 M 的波浪底摆 —— 一个都不许回来
    expect(svg).not.toContain('取景角')
    expect(svg).not.toContain('C35.2 33.4 32.8 29.8 30.2 30.4')
  })

  it('④ 登录页真的挂了这张图，且占位字已删（两个标并排 = 回归）', () => {
    const tsx = readFileSync(LOGIN_TSX, 'utf8')
    expect(tsx).toContain("from '../../../assets/brand/logo-144.png'")
    expect(tsx).toMatch(/<Image[^>]*className='login-brand__icon-img'[^>]*src=\{brandLogo\}/)
    expect(tsx).not.toContain('login-brand__icon-text')
    expect(tsx).not.toMatch(/<Text className='login-brand__icon-text'>米<\/Text>/)
    expect(tsx).toContain('生意管家')
  })

  it('⑤ 样式里有对应的尺寸，否则图按 0 高渲染（真机白块）', () => {
    const scss = readFileSync(LOGIN_SCSS, 'utf8')
    expect(scss).toContain('&__icon-img')
    expect(scss).toMatch(/&__icon-img\s*\{[^}]*width:\s*128px/)
    expect(scss).toMatch(/&__icon-img\s*\{[^}]*height:\s*128px/)
  })
})
