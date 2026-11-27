// case_ids: UI-082
//
// 判据：**站点域名的唯一读取点**（issue #8941）—— `src/lib/site-domain.ts` 的同名单测。
//
// 缺省值（不配置 `NEXT_PUBLIC_SITE_DOMAIN`）下派生值与改前**逐字相同** —— 唯一例外是**公开面
// origin**，按 issue #8968 收成 **apex**（www 会 308 跳 apex，写进 sitemap / canonical 就是假落点）；
// 生产值（`cytda.com`）必须让五个派生值全部跟着走（商家登录 / canonical / sitemap /
// robots / proxy 的 host 分流都从这里取）。
// 端到端落点（next.config 的 www→apex 308 / proxy 分流 / metadata / route 形式）在
// `tests/unit/pages/site-domain.test.ts`，本文件只钉派生值这一层。
import { describe, it, expect, vi, afterEach } from 'vitest'

import {
  DEFAULT_SITE_DOMAIN,
  merchantHost,
  merchantLoginUrl,
  siteDomain,
  siteOrigin,
  wwwHost,
} from '@/lib/site-domain'

afterEach(() => {
  vi.unstubAllEnvs()
})

describe('缺省值（不配置 NEXT_PUBLIC_SITE_DOMAIN）⇒ 与改前逐字相同（公开面 origin 除外，issue #8968 收成 apex）', () => {
  it('apex / www / merchant / 公开面 origin(apex) / 商家登录地址', () => {
    vi.stubEnv('NEXT_PUBLIC_SITE_DOMAIN', '')
    expect(DEFAULT_SITE_DOMAIN).toBe('migaozn.com')
    expect(siteDomain()).toBe('migaozn.com')
    expect(wwwHost()).toBe('www.migaozn.com')
    expect(merchantHost()).toBe('merchant.migaozn.com')
    expect(siteOrigin()).toBe('https://migaozn.com')
    expect(merchantLoginUrl()).toBe('https://merchant.migaozn.com/login')
  })

  it('未设置（undefined）与空串同义 —— 都落到缺省域', () => {
    vi.stubEnv('NEXT_PUBLIC_SITE_DOMAIN', '')
    expect(merchantLoginUrl()).toBe('https://merchant.migaozn.com/login')
  })
})

describe('NEXT_PUBLIC_SITE_DOMAIN=cytda.com ⇒ 全部派生值跟着走', () => {
  it('apex / www / merchant / origin / 商家登录地址', () => {
    vi.stubEnv('NEXT_PUBLIC_SITE_DOMAIN', 'cytda.com')
    expect(siteDomain()).toBe('cytda.com')
    expect(wwwHost()).toBe('www.cytda.com')
    expect(merchantHost()).toBe('merchant.cytda.com')
    expect(siteOrigin()).toBe('https://cytda.com')
    expect(merchantLoginUrl()).toBe('https://merchant.cytda.com/login')
  })

  it('归一化：整条 origin / 末尾斜杠 / 大小写 / 首尾空白都收成 host', () => {
    vi.stubEnv('NEXT_PUBLIC_SITE_DOMAIN', '  HTTPS://Cytda.COM/  ')
    expect(siteDomain()).toBe('cytda.com')
    expect(merchantLoginUrl()).toBe('https://merchant.cytda.com/login')
  })

  it('判别力自证：换域名后不残留测试域（五个派生值里一处 migaozn 都没有）', () => {
    vi.stubEnv('NEXT_PUBLIC_SITE_DOMAIN', 'cytda.com')
    const derived = [
      siteDomain(),
      wwwHost(),
      merchantHost(),
      siteOrigin(),
      merchantLoginUrl(),
    ]
    expect(derived.filter((value) => value.includes('migaozn'))).toEqual([])
  })
})
