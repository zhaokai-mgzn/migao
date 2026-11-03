// case_ids: MC-147
/**
 * B 端移动会话卡：来源组说商家的话，**内部口径词零上屏**（issue #6461）。
 *
 * 本判据补的是 issue #6461「落地后补」清单里的前两条：
 * ① bmini-app 侧的**零内部口径词判据**（`user-copy-jargon-guard` 只扫 admin-web 的源码字面量，
 *    且判不了「服务端下发的字符串」这一面）；
 * ② 会话卡的来源组标题只许来自 `src/utils/cohort-groups.ts` 的映射表（**副本**，单一真值在
 *    admin-web 的 `src/lib/cohort-groups.ts`，两端逐项相等由
 *    `frontend/admin-web/tests/unit/lib/cohort-groups.test.ts` 判据 ⑤ 锁死）。
 *
 * ## 判据（每条都能单独变红）
 *
 * | # | 判据 | 红证 |
 * |---|---|---|
 * | 1 | 卡片把**机器键**交给映射表：渲染结果 = 映射文案，服务端标签（`切换后…` 之类）一个都不出现 | 把卡片改回渲染 `cohortLabel` ⇒ 红 |
 * | 2 | 认不出的键（服务端新增枚举 / 脏数据 / 缺值）⇒ 兜底话术，**不回显原值** | 删掉兜底 ⇒ 红（屏上会是空/原值） |
 * | 3 | 会话卡源码（`src/components/cards/**`，去注释）里**零**内部口径词 | 在任一张卡里写一句「存量导入…」⇒ 红 |
 *
 * ⚠️ 判据 3 的语料**排除本文件自己**（`migao-dev-flow` §23.8 B1：判据语料必须排除判据自身，否则
 * 断言里的词会把探针数成违规）。只扫自己的包，不读别的模块（bmini 是独立 npm 工程）。
 */
import React from 'react'
import { render, screen } from '@testing-library/react'
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import BatchStockCard from '../src/components/cards/BatchStockCard'
import { COHORT_GROUP_FALLBACK, COHORT_GROUP_TITLES, cohortGroupTitle } from '../src/utils/cohort-groups'

const CARDS_DIR = join(__dirname, '../src/components/cards')
/** 内部口径词（= 服务端 `SavingMetricViews#cohortLabel` 的取值形态）；本判据要抓的就是它们 */
const INTERNAL_WORDS = ['切换后', '存量导入', '来源未知']

function stripComments(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/[^\n]*/g, '$1')
}

/** 一个来源组（服务端 `CohortSummary` 的最小载荷；`cohortLabel` 故意保留内部口径词） */
function cohortRow(cohort: string) {
  return {
    cohort,
    cohortLabel: '切换后（采购入库）',
    opening: false,
    batchCount: 7,
    le0_2Count: 3,
    le0_2Share: 0.4286,
    remainingMeters: 4.8,
    savedMeters: 24.68,
    savedAmount: 113.45,
    lineCount: 2,
    unknownCostLines: 0,
    buckets: [{ key: 'le_0_2', label: '≤0.2 米', batchCount: 3, share: 0.4286 }],
  }
}

function renderBoard(cohorts: any[]) {
  return render(
    <BatchStockCard data={{ action: 'saving_board', granularity: 'month', cohorts, total: { savedMeters: 24.68, savedAmount: 113.45 } }} />,
  )
}

describe('bmini 会话卡来源组文案（issue #6461）', () => {
  it('判据 1：三个已知来源组都说商家话，服务端内部标签一个都不上屏', () => {
    const { container } = renderBoard([
      cohortRow('purchase'),
      cohortRow('opening'),
      cohortRow('unknown'),
    ])
    const text = container.textContent || ''
    for (const key of ['purchase', 'opening', 'unknown']) {
      expect(text).toContain(COHORT_GROUP_TITLES[key])
    }
    for (const word of INTERNAL_WORDS) {
      // 内部口径词被渲染 = 服务端标签逐字上屏
      expect(text).not.toContain(word)
    }
  })

  it('判据 2：认不出的键 / 缺值 ⇒ 兜底话术，不回显原值', () => {
    const { container } = renderBoard([cohortRow('switched'), cohortRow('')])
    const text = container.textContent || ''
    expect(text).toContain(COHORT_GROUP_FALLBACK)
    // 原始值（英文枚举）不许上屏
    expect(text).not.toContain('switched')
    // 对照组：兜底不是「恒回兜底」的假绿 —— 已知键仍走表
    expect(cohortGroupTitle('purchase')).toBe(COHORT_GROUP_TITLES.purchase)
  })

  it('判据 3：会话卡源码（去注释）里零内部口径词', () => {
    const files = readdirSync(CARDS_DIR).filter((f) => /\.tsx?$/.test(f))
    // 扫不到源码 = 本判据在扫空气（不是「没问题」）
    expect(files.length).toBeGreaterThanOrEqual(5)
    for (const file of files) {
      const code = stripComments(readFileSync(join(CARDS_DIR, file), 'utf8'))
      for (const word of INTERNAL_WORDS) {
        // 出现内部口径词 = 商家读不懂（issue #6459）
        if (code.includes(word)) throw new Error(`${file} 里出现内部口径词「${word}」`)
        expect(code).not.toContain(word)
      }
    }
  })
})
