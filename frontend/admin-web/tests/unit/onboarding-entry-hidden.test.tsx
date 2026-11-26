// case_ids: OB-008
/**
 * 内测期官网隐藏「自助入驻」入口（issue #9066，用例 OB-008）
 *
 * 口径（用户 2026-11-23 裁定）：
 * - **只隐藏官网公开入口**：导航 / 页脚 / 首页 / 关于 / 产品服务 / 联系页不再露出
 *   「商家入驻 / 免费开通 / 立即入驻 / 提交入驻申请」；
 * - `/register` 页面与 `POST /api/auth/register` **原样保留** —— 内测期内部入口 = 直接访问 URL；
 * - 开关单一来源 = `src/config/onboarding.ts` 的 `SELF_SERVICE_ONBOARDING_OPEN`，
 *   内测结束改回 `true` 即整体恢复（届时本文件与各页 CTA 断言需一起改）。
 *
 * 第三组是**类级元守卫**：官网面（`app/(corporate)/**` + `components/corporate/**`）
 * 任何 `/register` 出处都必须引用开关 —— 以后有人把入口加回导航 / 页脚 / CTA 却忘了走开关，
 * 这里会红；注入式自证保证它不是空断言。
 */
import { describe, it, expect, vi } from 'vitest'
import { render } from '@testing-library/react'
import { readFileSync, readdirSync, statSync } from 'fs'
import { join } from 'path'
import type { ComponentType } from 'react'

vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

vi.mock('@/components/ui/Logo', () => ({
  default: () => <div data-testid="logo">Logo</div>,
}))

import { SELF_SERVICE_ONBOARDING_OPEN } from '@/config/onboarding'
import CorporateNav from '@/components/corporate/CorporateNav'
import CorporateFooter from '@/components/corporate/CorporateFooter'
import HomePage from '@/app/(corporate)/page'
import AboutPage from '@/app/(corporate)/about/page'
import ServicesPage from '@/app/(corporate)/services/page'
import ContactPage from '@/app/(corporate)/contact/page'

const ONBOARDING_ENTRY_TEXTS = ['商家入驻', '免费开通', '立即入驻', '提交入驻申请']

const SURFACES: Array<[string, ComponentType]> = [
  ['官网导航', CorporateNav],
  ['官网页脚', CorporateFooter],
  ['官网首页', HomePage],
  ['关于我们', AboutPage],
  ['产品服务', ServicesPage],
  ['联系方式', ContactPage],
]

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    return statSync(path).isDirectory() ? walk(path) : [path]
  })
}

describe('内测期官网隐藏自助入驻入口（OB-008）', () => {
  it('开关是单一来源且内测期关闭', () => {
    expect(SELF_SERVICE_ONBOARDING_OPEN).toBe(false)
  })

  for (const [name, Page] of SURFACES) {
    it(`${name}：没有 /register 链接，也没有入驻入口文案`, () => {
      const { container } = render(<Page />)
      expect(container.querySelector('a[href="/register"]'), `${name} 仍有 /register 链接`).toBeNull()
      for (const text of ONBOARDING_ENTRY_TEXTS) {
        expect(container.textContent?.includes(text), `${name} 仍露出「${text}」`).toBe(false)
      }
    })
  }

  it('内部入口保留：/register 页面与提交调用未被删改', () => {
    const source = readFileSync(join(process.cwd(), 'src/app/register/page.tsx'), 'utf-8')
    expect(source).toContain('authApi.submitRegistration')
    expect(source).toContain('企业入驻申请')
  })

  it('类级元守卫：官网面每个 /register 出处都必须由开关守卫（注入式自证）', () => {
    // 判定实现：出现 /register 但整份文件没有引用开关 ⇒ 未守卫
    const isUnguarded = (source: string) =>
      source.includes('/register') && !source.includes('SELF_SERVICE_ONBOARDING_OPEN')

    // 判别力自证：未守卫样本必须判红、已守卫样本必须判绿（否则本判据是空断言）
    expect(isUnguarded('<Link href="/register">商家入驻</Link>')).toBe(true)
    expect(
      isUnguarded('{SELF_SERVICE_ONBOARDING_OPEN && (<Link href="/register">商家入驻</Link>)}'),
    ).toBe(false)

    const roots = [
      join(process.cwd(), 'src/app/(corporate)'),
      join(process.cwd(), 'src/components/corporate'),
    ]
    const offenders = roots
      .flatMap(walk)
      .filter((file) => /\.(ts|tsx)$/.test(file))
      .filter((file) => isUnguarded(readFileSync(file, 'utf-8')))
      .map((file) => file.replace(`${process.cwd()}/`, ''))
    expect(offenders, `这些官网面文件露出 /register 却没走开关：${offenders.join('、')}`).toEqual([])
  })
})
