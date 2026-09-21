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
 */
vi.mock('@/lib/api', () => ({
  autoFeaturesApi: {
    preview: (p: { width: number; height: number; fabric_width?: number; cutting_mode?: string }) => {
      const side = 0.3
      const hem = 0.3
      const fullness = 2.0
      const round = (v: number) => Number(v.toFixed(3))
      const door = p.fabric_width ?? 0
      const features: Array<{ name: string; source: string; reason: string }> = []
      if (p.cutting_mode === '定宽买高') {
        const product = (p.width + side) * fullness
        if (product > door) {
          features.push({
            name: '超宽',
            source: '推算',
            reason: `成品宽 ${p.width} + 左右余量 ${side} = ${round(p.width + side)} 米 × 褶倍 ${fullness} = ${round(product)} 米 > 门幅 ${door} 米`,
          })
        }
        features.push({ name: '倒幅', source: '推算', reason: '加工类型 = 定宽买高' })
      } else if (p.height + hem > door) {
        features.push({
          name: '超高',
          source: '推算',
          reason: `成品高 ${p.height} + 上下卷边 ${hem} = ${round(p.height + hem)} 米 > 门幅 ${door} 米`,
        })
      }
      return Promise.resolve({
        data: { data: { auto_features: features, notices: [], door_width: door, fullness_used: fullness, notice: '' } },
      })
    },
  },
}))
import { CALC_SCALAR_KEYS, glossaryAnchorOf } from '@/lib/craft-calc-glossary'
import type { CraftCalcConfig } from '@/types'

/** 引擎默认配置（测试替身；逐值写死 = 「后端会回什么」） */
const CONFIG: CraftCalcConfig = {
  per_fold_single: 0.25,
  per_fold_mixed_times: { '1': 0.65, '2': 1.2 },
  margin_single: 0.2,
  margin_multi: 0.3,
  min_fullness: 1.5,
  tiers: { standard: { fullness: 2.0, label: '标准工艺' }, economy: { fullness: 1.8, label: '经济工艺' } },
  default_formula: 'pleat',
  side_margin: 0.3,
  hem_margin: 0.3,
  meters_rounding_step: 0.1,
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

  it('参数值取自配置对象（不是写死的数）', () => {
    const changed: CraftCalcConfig = { ...CONFIG, per_fold_single: 0.31, side_margin: 0.42 }
    render(<CraftCalcGlossary config={changed} />)
    // 注入：把渲染值写死成默认值 ⇒ 两条都红
    expect(screen.getByTestId('glossary-value-per_fold_single')).toHaveTextContent('0.31')
    expect(screen.getByTestId('glossary-value-side_margin')).toHaveTextContent('0.42')
  })

  it('三个自动推算特征各有一条**带真实数字**的算例（依据来自服务端 —— #5036 包 2a）', async () => {
    render(<CraftCalcGlossary config={CONFIG} />)
    for (const name of ['超高', '超宽', '倒幅']) {
      // 算例是**异步**取的（服务端判定）⇒ 必须 await；注入：算例行改成只写定义、不带依据 ⇒ 红
      const row = await screen.findByTestId(`glossary-example-${name}`)
      expect(row).toHaveTextContent('门幅')
    }
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
