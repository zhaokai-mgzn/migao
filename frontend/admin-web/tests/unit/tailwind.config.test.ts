// case_ids: UI-001
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'fs'
import { join, relative } from 'path'
import config from '../../tailwind.config'

type ColorScale = Record<string, string>

const colors = (config.theme?.extend?.colors ?? {}) as Record<string, ColorScale>

const HEX = /^#[0-9a-fA-F]{6}$/

function* walkTsFiles(dir: string): Generator<string> {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) {
      yield* walkTsFiles(full)
    } else if (/\.(ts|tsx)$/.test(name)) {
      yield full
    }
  }
}

describe('tailwind.config 织物质感 token 定义 (#2534)', () => {
  it('primary[500]=#48618f 且 accent[500]=#c06a3e 且 neutral[50]=#faf7f2', () => {
    expect(colors.primary[500]).toBe('#48618f')
    expect(colors.accent[500]).toBe('#c06a3e')
    expect(colors.neutral[50]).toBe('#faf7f2')
  })

  it('primary/accent/neutral 三组各为完整 50-900 阶', () => {
    const steps = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900]
    for (const name of ['primary', 'accent', 'neutral'] as const) {
      const scale = colors[name]
      expect(scale).toBeTruthy()
      for (const step of steps) {
        expect(scale[String(step)], `${name}[${step}]`).toMatch(HEX)
      }
    }
  })

  it('primary 非默认蓝', () => {
    expect(colors.primary[500]).not.toBe('#3b82f6')
    expect(colors.primary[500]).not.toBe('#3B82F6')
  })
})

describe('src/ 无默认蓝 #3b82f6 字面量 (#2534)', () => {
  it('扫描 frontend/admin-web/src/**/*.{ts,tsx} 匹配计数 = 0', () => {
    const srcDir = join(process.cwd(), 'src')
    const hits: string[] = []
    let count = 0
    for (const file of walkTsFiles(srcDir)) {
      const content = readFileSync(file, 'utf-8')
      const matched = content.match(/#3b82f6/gi) ?? []
      if (matched.length > 0) {
        count += matched.length
        hits.push(relative(process.cwd(), file))
      }
    }
    expect(hits).toEqual([])
    expect(count).toBe(0)
  })
})

describe('token 单元测试覆盖 (#2534)', () => {
  it('tailwind.config token 断言可解析且 primary/accent/neutral 三值精确匹配', () => {
    expect(colors.primary[500]).toBe('#48618f')
    expect(colors.accent[500]).toBe('#c06a3e')
    expect(colors.neutral[50]).toBe('#faf7f2')
    expect(colors.primary[500]).not.toBe('#3b82f6')
  })
})

describe('线上修复：chips purge + 页面底色迁移（#2544）', () => {
  it('content globs 包含 src/lib — 防止 status-chip.ts 独有类（emerald/neutral）被 purge', () => {
    const content = (config.content ?? []) as string[]
    expect(content.some(g => g.includes('src/lib'))).toBe(true)
  })

  it('globals.css 页面底色迁移为米白 #faf7f2（250,247,242），移除旧平灰 245,245,245', () => {
    const css = readFileSync(join(process.cwd(), 'src/app/globals.css'), 'utf-8')
    expect(css).toContain('250, 247, 242')
    expect(css).not.toContain('245, 245, 245')
  })

  it('(dashboard) layout 页面容器使用 bg-neutral-50 暖中性底，不再使用 bg-gray-50', () => {
    const layout = readFileSync(join(process.cwd(), 'src/app/(dashboard)/layout.tsx'), 'utf-8')
    expect(layout).toContain('bg-neutral-50')
    expect(layout).not.toContain('bg-gray-50')
  })
})
