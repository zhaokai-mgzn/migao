// case_ids: BM-030
/**
 * B 端 H5 底部 tabBar 的**图标唯一性**（issue #5759）
 *
 * ## 治的形态
 *
 * `frontend/bmini-app/src/app.config.ts` 里「问米宝」与「坐席」**指向同一张图**
 * （`assets/tabbar/chat.png` / `chat-active.png`）⇒ 线上四个 tab 只有三张不同图标，
 * 用户看到两个一模一样的入口（headless 实测：两处 `img.src` 的 base64 完全相同）。
 * 这类缺陷**不会让任何东西变红**：路由对、点击对、只是「看起来不对」。
 *
 * ## 判据（三条，都能在构建前拦住）
 *
 * 1. tabBar 的 `iconPath` / `selectedIconPath` **两两不同**（同一 tab 的未选/选中不同是正常的，跨 tab 相同即红）；
 * 2. 每个路径指向的文件**真的存在**（声明了不存在的图 ⇒ 真机上是空白格）；
 * 3. 每张图都是 81×81（本仓图标家族规格；只读 PNG 头，不依赖图像库）。
 *
 * ⚠️ 边界：本文件只判**规格与唯一性**，不判「画得像不像/美不美」（那是设计的事）。
 * 渲染面（DOM 里真的四张不同）由 e2e 腿 `tests/e2e/specs/bmini/bmini-tabbar.spec.ts` 判。
 */
import fs from 'fs'
import path from 'path'

const SRC = path.resolve(__dirname, '..', 'src')
const APP_CONFIG = path.join(SRC, 'app.config.ts')
const TABBAR_DIR = path.join(SRC, 'assets', 'tabbar')

/** 从 `app.config.ts` 的**文本**里取 tabBar 的四组图标路径（`defineAppConfig` 是构建期全局，jest 里不能直接 import） */
function tabBarIconPaths(configText: string): { icon: string[]; active: string[] } {
  const icon = [...configText.matchAll(/iconPath:\s*'([^']+)'/g)].map((m) => m[1])
  const active = [...configText.matchAll(/selectedIconPath:\s*'([^']+)'/g)].map((m) => m[1])
  return { icon, active }
}

/** 读 PNG 头（IHDR 的宽高在固定偏移上）—— 只为拿尺寸，不解码像素 */
function pngSize(file: string): { width: number; height: number } {
  const buf = fs.readFileSync(file)
  const isPng = buf.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))
  expect(isPng).toBe(true)
  return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) }
}

describe('B 端 tabBar 图标唯一性（issue #5759）', () => {
  const configText = fs.existsSync(APP_CONFIG) ? fs.readFileSync(APP_CONFIG, 'utf-8') : ''
  const { icon, active } = tabBarIconPaths(configText)

  it('前置：确实读到了四个 tab 的图标声明（读不到 = 判红，不许空跑成「0 命中 = 通过」）', () => {
    expect(fs.existsSync(APP_CONFIG)).toBe(true)
    expect(icon).toHaveLength(4)
    expect(active).toHaveLength(4)
  })

  it('🔴 四个 tab 的未选图标两两不同（问米宝与坐席曾共用 chat.png）', () => {
    expect(new Set(icon).size).toBe(icon.length)
  })

  it('🔴 四个 tab 的选中图标两两不同', () => {
    expect(new Set(active).size).toBe(active.length)
  })

  it('每个图标文件都存在，且是 81×81（本仓图标家族规格）', () => {
    for (const rel of [...icon, ...active]) {
      const file = path.join(SRC, rel)
      expect({ file: rel, exists: fs.existsSync(file) }).toEqual({ file: rel, exists: true })
      expect({ file: rel, size: pngSize(file) }).toEqual({ file: rel, size: { width: 81, height: 81 } })
    }
  })

  it('类级：`assets/tabbar` 里不留**零引用**的图标（换图标时旧的要么删、要么仍被引用）', () => {
    const used = new Set([...icon, ...active].map((rel) => path.basename(rel)))
    const unused = fs
      .readdirSync(TABBAR_DIR)
      .filter((f) => f.endsWith('.png') && !used.has(f))
    expect(unused).toEqual([])
  })
})
