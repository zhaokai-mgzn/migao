// case_ids: OR-040, OR-041
/**
 * 「算料口径与术语说明」区块（issue #4975）—— 渲染面。
 *
 * 分工：**跨源守卫**在 `tests/unit/lib/craft-calc-glossary.test.ts`（读 Python/TS 源比对），
 * 本文件只判**渲染**：折叠区块在、每个参数锚点真的存在（页面「说明」链接不指空）、
 * 参数值取自配置对象（而不是写死的数）、算例文案带真实数字。
 *
 * 复用既有用例（同 `OperationsProvenance.test.tsx` 先例，不新增用例 ID）：
 * OR-040（自动识别与余量语义）/ OR-041（算料公式与配置口径）。
 */
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { CraftCalcGlossary } from '@/components/production/CraftCalcGlossary'

/**
 * **服务端替身**（issue #5036 包 2a）：算例的判定依据由 `POST /api/admin/orders/auto-features` 给
 * ⇒ 本组件不再本地判，测试必须替身服务端（否则会打真实网络）。
 *
 * 🔴 **issue #5130 改判**：替身按**新**判据（净窗宽 / 净窗高 与**企业阈值**比；`倒幅` 只看加工类型）
 * 产出 —— 旧替身的「与门幅比 / 含褶倍 / 含左右余量」口径已随裁定退役。
 */
vi.mock('@/lib/api', () => ({
  autoFeaturesApi: {
    preview: (p: {
      width: number
      height: number
      cutting_mode?: string
      config?: { oversize_width_threshold?: number; oversize_height_threshold?: number }
    }) => {
      const wide = p.config?.oversize_width_threshold ?? 6
      const high = p.config?.oversize_height_threshold ?? 4
      const features: Array<{ name: string; source: string; reason: string }> = []
      if (p.width > wide) {
        features.push({
          name: '超宽',
          source: '推算',
          reason: `净窗宽 ${p.width} 米 > 超宽阈值 ${wide} 米`,
        })
      }
      if (p.height > high) {
        features.push({
          name: '超高',
          source: '推算',
          reason: `净窗高 ${p.height} 米 > 超高阈值 ${high} 米`,
        })
      }
      if (p.cutting_mode === '定宽买高') {
        features.push({ name: '倒幅', source: '推算', reason: '加工类型 = 定宽买高' })
      }
      return Promise.resolve({
        data: { data: { auto_features: features, notices: [], door_width: null } },
      })
    },
  },
}))
import { CALC_SCALAR_KEYS, glossaryAnchorOf } from '@/lib/craft-calc-glossary'
import type { CraftCalcConfig } from '@/types'

/** 引擎默认配置（测试替身；逐值写死 = 「后端会回什么」）—— 含 issue #5130 的两个企业阈值 */
const CONFIG: CraftCalcConfig = {
  per_fold_single: 0.25,
  per_fold_mixed_times: { '1': 0.65, '2': 1.2 },
  margin_single: 0.2,
  margin_multi: 0.3,
  min_fullness: 1.5,
  tiers: { standard: { fullness: 2.0, label: '标准工艺' }, economy: { fullness: 1.8, label: '经济工艺' } },
  default_formula: 'pleat',
  hem_margin: 0.3,
  meters_rounding_step: 0.1,
  oversize_width_threshold: 6,
  oversize_height_threshold: 4,
}

describe('算料口径与术语说明区块（issue #4975）', () => {
  it('两组说明都在：A 公式怎么算 / B 术语怎么判', () => {
    render(<CraftCalcGlossary config={CONFIG} />)
    // 注入：删掉任一 <details> ⇒ 对应断言红
    expect(screen.getByTestId('glossary-formula')).toHaveTextContent('公式怎么算')
    expect(screen.getByTestId('glossary-terms')).toHaveTextContent('术语怎么判')
  })

  it('每个参数锚点都渲染出来（页面「说明」链接不会指空）', () => {
    render(<CraftCalcGlossary config={CONFIG} />)
    for (const key of CALC_SCALAR_KEYS) {
      // 注入：把某个参数的条目漏渲染 ⇒ getElementById 返回 null ⇒ 红
      expect(document.getElementById(glossaryAnchorOf(key))).not.toBeNull()
    }
  })

  it('参数值取自配置对象（不是写死的数）；`side_margin` 已随 #5030 退场', () => {
    const changed: CraftCalcConfig = { ...CONFIG, per_fold_single: 0.31, hem_margin: 0.42 }
    render(<CraftCalcGlossary config={changed} />)
    // 注入：把渲染值写死成默认值 ⇒ 两条都红
    expect(screen.getByTestId('glossary-value-per_fold_single')).toHaveTextContent('0.31')
    expect(screen.getByTestId('glossary-value-hem_margin')).toHaveTextContent('0.42')
    // 🔴 #5030 改判：原判据钉 `glossary-value-side_margin` = 0.42 —— 该键已整体退场
    // ⇒ 改成**同强度的反向守卫**：值行与说明条目都不得再渲染出来（加回该键 ⇒ 红）
    expect(screen.queryByTestId('glossary-value-side_margin')).toBeNull()
    expect(document.getElementById('glossary-param-side_margin')).toBeNull()
    // 反向自证：同一张表**仍在场**的高方向值行必须能被看见（否则上面两条是空断言）
    expect(document.getElementById('glossary-param-hem_margin')).not.toBeNull()
  })

  it('三个自动推算特征各有一条**带真实数字**的算例（依据来自服务端 —— #5036 包 2a）', async () => {
    render(<CraftCalcGlossary config={CONFIG} />)
    // `超高` / `超宽` 的算例：依据文案 = 与**企业阈值**比
    // 🔴 issue #5130 改判：由「> 门幅 … 米」改为「> 超宽/超高阈值 … 米」（旧式「门幅」依据复活 ⇒ 红）
    for (const name of ['超高', '超宽']) {
      // 算例是**异步**取的（服务端判定）⇒ 必须 await；注入：算例行改成只写定义、不带依据 ⇒ 红
      const row = await screen.findByTestId(`glossary-example-${name}`)
      expect(row).toHaveTextContent('阈值')
      expect(row).not.toHaveTextContent('门幅')
    }
    // `倒幅` 的算例依据 = 加工类型（它本来就与阈值 / 门幅无关）
    expect(await screen.findByTestId('glossary-example-倒幅')).toHaveTextContent('定宽买高')
  })

  it('手选两项写明「系统不推算」+ 拼接的「不触发工序」边界可见（死亡条件绑 #4569）', () => {
    render(<CraftCalcGlossary config={CONFIG} />)
    expect(screen.getByTestId('glossary-term-拼接')).toHaveTextContent('不触发工序')
    expect(screen.getByTestId('glossary-term-接高')).toHaveTextContent('待查明')
  })

  it('特殊选项组：六个勾选项各一条（工序/锚点来自真值源；一分为二 无工序）', () => {
    render(<CraftCalcGlossary config={CONFIG} />)
    for (const name of ['拼1次', '拼2次', '拼3次', '接高', '双眼皮接高', '一分为二']) {
      // 注入：漏渲染任一项 ⇒ 红
      expect(screen.getByTestId(`glossary-option-${name}`)).toBeInTheDocument()
    }
    // 注入：给「一分为二」编一道工序 ⇒ 第一条红；删掉「待查明」⇒ 第二条红
    expect(screen.getByTestId('glossary-option-一分为二')).toHaveTextContent('不加工序')
    expect(screen.getByTestId('glossary-option-双眼皮接高')).toHaveTextContent('待查明')
    // 「接高」两组都有 ⇒ 锚点必须分开（否则跳错条目）
    expect(screen.getByTestId('glossary-term-接高')).toBeInTheDocument()
    expect(screen.getByTestId('glossary-option-接高')).toBeInTheDocument()
  })

  it('说明区块可键盘展开（原生 details，无自定义开关）', () => {
    const { container } = render(<CraftCalcGlossary config={CONFIG} />)
    const details = container.querySelectorAll('details')
    // 注入：改成受控 div + 自绘开关 ⇒ 红（键盘可达性随之丢失）
    expect(details.length).toBeGreaterThan(1)
    expect(container.querySelectorAll('summary').length).toBe(details.length)
  })
})
