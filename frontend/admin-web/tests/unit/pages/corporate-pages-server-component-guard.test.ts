// case_ids: UI-082
//
// 类级元守卫：**`(corporate)` 下的页面必须是服务端组件**（issue #6307）。
//
// ## 病根（为什么这一类必须钉住）
//
// 根 layout `frontend/admin-web/src/app/layout.tsx` 把客户端组件 AuthProvider 套在**全部**页面上，
// 而它的 `isReady` 初值 `false`、置 `true` 只发生在 `useEffect` 里
// （`frontend/admin-web/src/components/providers/AuthProvider.tsx`）⇒ **SSR 阶段必然返回 loading 骨架**。
// 于是：
//   · 服务端组件页面的正文由 SSR 渲染进 RSC（__next_f）载荷 ⇒ 初始 HTML 里能读到（SEO / 无 JS 能读）；
//   · **客户端组件页面**在 SSR 阶段**整段不渲染** ⇒ 初始 HTML 里**没有正文**。
//
// 实测（2026-10-04 生产 `www.migaozn.com`，issue #6307）：`/contact`（当时首行 `'use client'`）
// 初始 HTML 22768 字节、__next_f 分片 3、`给我们留言` 字面量与 \uXXXX 转义**都是 0**、只剩「加载中」骨架；
// 而 `/`（98854 字节 / 分片 7）与 `/services`、`/about` 都能读到正文。`(corporate)` 下当时**只有** contact
// 声明了 `'use client'` —— 与「只有 /contact 缺正文」逐条吻合。
//
// **为什么是类级而不是只钉 contact**：这个缺陷的形态与具体页面无关 ——
// **任何**公开营销页只要加上 `'use client'`，正文就会立刻退出初始 HTML，而且**用户可见面毫无异常**
// （浏览器里页面完全正常，没有任何东西会变红）。⇒ 钉住**这一类**（目录下全部 `page.tsx`），
// 而不是钉住某一个文件的某个写法。
//
// ## 豁免
//
// 当前豁免清单为**空**（`EXEMPT`，只许缩短：真需要豁免时必须写明理由 + issue 号）。
// `(corporate)` 是公开营销页目录：正文进初始 HTML 是它的**功能要求**，不是风格偏好 ⇒ 理应长期为空。
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'fs'
import { join, relative } from 'path'

/** `(corporate)` 目录（相对 admin-web 包根 —— vitest 的 cwd 就是包根，同 tailwind.config.test.ts 口径）。 */
const CORPORATE_DIR = join(process.cwd(), 'src/app/(corporate)')

/**
 * 客户端组件指令：`'use client'` / `"use client"`（可带分号）。
 *
 * 口径 = **文件头**的指令（去掉前导空行，允许其前有注释行）：Next.js 只认「文件顶部」的这条指令，
 * 所以判据也只认它 —— 判据口径与机制口径对齐，不做"全文出现即红"的宽松匹配。
 */
const CLIENT_DIRECTIVE_RE = /^\s*['"]use client['"]\s*;?\s*$/

/** 豁免台账（**只许缩短**；每条必须写明理由 + issue 号）。当前为空。 */
const EXEMPT: string[] = []

/** 该源码是否为客户端组件（去掉 BOM，跳过前导空行与注释行后看第一条语句）。 */
export function declaresUseClient(source: string): boolean {
  const lines = source.replace(/^\uFEFF/, '').split(/\r?\n/)
  for (const line of lines) {
    if (line.trim() === '') continue
    if (/^\s*(\/\/|\/\*|\*)/.test(line)) continue
    return CLIENT_DIRECTIVE_RE.test(line)
  }
  return false
}

/** `(corporate)` 下全部 `page.tsx` 的包内相对路径（递归：加子路由时自动进面）。 */
function corporatePageFiles(dir: string = CORPORATE_DIR): string[] {
  const found: string[] = []
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) {
      found.push(...corporatePageFiles(full))
    } else if (name === 'page.tsx') {
      found.push(relative(process.cwd(), full))
    }
  }
  return found.sort()
}

describe('公开营销页必须留在初始 HTML 里（(corporate) 页面不得声明 \'use client\'，issue #6307）', () => {
  it("(corporate) 目录下的 page.tsx 不得声明 'use client'（否则正文进不了初始 HTML）", () => {
    const pages = corporatePageFiles()

    // 前提自证（不弱化判定）：面不能是空的 —— 目录改名 / 页面被搬走时"零命中"会伪装成绿。
    expect(
      pages.length,
      `前提失效：(corporate) 下一个 page.tsx 都没找到（现取 ${pages.length} 个）—— ` +
        `说明被测对象不在预期位置，本判据此刻没有判别力，必须先修判据的坐标`,
    ).toBeGreaterThan(0)

    const offenders = pages.filter(
      (rel) => !EXEMPT.includes(rel) && declaresUseClient(readFileSync(join(process.cwd(), rel), 'utf-8')),
    )

    // 断言消息 = 理由 + 实测读数 + 可执行出口（判红必须可归因）
    expect(
      offenders,
      `公开营销页必须是服务端组件：声明 'use client' 会让该页在 SSR 阶段整段不渲染，` +
        `正文进不了初始 HTML（SEO 与无 JS 环境读到空壳，而浏览器里看起来完全正常 —— 没有任何用户可见异常会提醒你）。` +
        `实测（issue #6307）：/contact 曾因首行 'use client' 导致初始 HTML 的正文命中数为 0（只剩「加载中」骨架）。` +
        `修法：把交互部分（表单 / 状态）抽成同目录下的客户端子组件，page.tsx 退回服务端组件。` +
        `命中文件：${offenders.join(', ')}（本面共 ${pages.length} 个 page.tsx）`,
    ).toEqual([])
  })

  it('判别力自证：检测器对注入的客户端组件真的会红（否则本守卫是空断言）', () => {
    // ① 正样本：与线上缺陷形态逐字相同的文件头 ⇒ 必须判为客户端组件
    expect(declaresUseClient("'use client'\n\nimport { useState } from 'react'\n")).toBe(true)
    expect(declaresUseClient('/* 版权头 */\n\n"use client";\nexport default function P() {}\n')).toBe(true)
    // ② 反样本：服务端组件（含"注释里提到 use client"的形态 —— 注解是读数不是指令）
    expect(declaresUseClient("import type { Metadata } from 'next'\nexport const metadata: Metadata = {}\n")).toBe(false)
    expect(declaresUseClient('// 注意：本页不要加 use client（否则正文进不了初始 HTML）\nimport Link from "next/link"\n')).toBe(false)
  })

  it('面自证：contact 页在面内（本判据确实覆盖了这次出问题的那个页面）', () => {
    expect(corporatePageFiles()).toEqual(
      expect.arrayContaining([join('src/app/(corporate)', 'contact', 'page.tsx')]),
    )
  })
})
