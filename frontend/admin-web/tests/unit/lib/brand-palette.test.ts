// case_ids: UI-082
//
// 判据：**品牌金色只有一份真值**（issue #6665 第 6 条）。
//
// 本文件守 `src/lib/brand-palette.ts` 本身；「页面不得再写死金色 hex」的扫面判据在
// `tests/unit/pages/corporate-visual-copy-guards.test.ts`。
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { join } from 'path'
import config from '../../../tailwind.config'
import { gold } from '@/lib/brand-palette'

describe('brand-palette：金色单一真值源（issue #6665）', () => {
  it('四个阶 = 被替换掉的那几个字面量（只收敛来源，不改观感）', () => {
    expect(gold).toEqual({
      300: '#f6d27a', // 首页 Hero 金色渐变起点
      400: '#ffc53d', // Logo 渐变起点
      500: '#e8b04b', // 星标 / 金色图标
      600: '#d48806', // 默认金色：柔光 / 导航细线
    })
  })

  it('tailwind.config.ts 直接接这份 palette（不是自己再抄一份 hex）', () => {
    const colors = (config.theme?.extend?.colors ?? {}) as Record<string, Record<string, string>>
    expect(colors.gold).toEqual({ ...gold })
    const configSrc = readFileSync(join(process.cwd(), 'tailwind.config.ts'), 'utf-8')
    expect(configSrc).toMatch(/import\s*\{\s*gold\s*\}\s*from\s*['"]\.\/src\/lib\/brand-palette['"]/)
    expect(
      [...configSrc.matchAll(/'(#(?:f6d27a|e8b04b|d48806|ffc53d))'/gi)].map((m) => m[1]),
      'tailwind.config.ts 里又抄了一份金色 hex',
    ).toEqual([])
  })

  it('判别力自证：本文件断的是具体色值，不是「对象非空」', () => {
    // 若有人把 gold 改成空对象 / 换掉某一阶，上面第一条会逐值红；这里给出反证读数
    expect(Object.keys(gold)).toHaveLength(4)
    expect(gold[400]).not.toBe(gold[600])
  })
})
