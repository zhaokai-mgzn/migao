// case_ids: UI-054, UI-057
/**
 * 「算料口径」域面板（issue #6580）—— 从 `TenantParamsPanel` 抽出的算料域**读面 + 编辑面**。
 *
 * 本文件判的是抽取后**必须保持**的三件事（抽取的判据就是「行为一字不变」）：
 * 1. 有读数 ⇒ 每个标量参数都有一行（人话 + 「改它会怎样」），不是只显示名字；
 * 2. `calcError` ⇒ 显示**传进来的**那句分流话术（面板不自己编话术 —— 归因判据在页面里），
 *    且**不**渲染参数行（读失败时不许把值画成「没配」）；
 * 3. `loading` ⇒ 不出现「未配置」这类结论（三态不互画）。
 *
 * ## 2026-10-10 改判（issue #6663，判据面**只收紧不放宽**）
 *
 * 真机截图实证同一次读面失败在**一屏之内渲染了四处重复信号**（§31 P1 常驻面克制 / P2 信息不重复）。
 * 本面板的处置：**只留一条失败行**，并撤掉两处重复与一处冒充：
 * - 撤：参数数值位的 `—`（改判为**不渲染参数卡** —— 一排 `—` 看着像「这些参数是空的」）；
 * - 撤：键名那一行（`per_fold_single` 等 6 个键名原样上屏，§31 P3 不摆内部标识）；
 * - 留：失败行 + **一个**「重试」出口（失败态必须给出口）。
 * 旧断言（值位 `—`、"键是给人看的两者必须同屏共存"）是**病灶本身**，按新口径改判。
 */
import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import CalcCaliberPanel from '@/components/settings/CalcCaliberPanel'

/** 一条最小可用读数（键取引擎真值源里的 `per_fold_single`；值 = 0.3） */
const CALC = {
  config: { per_fold_single: 0.3, margin_single: 0.05, oversize_width_threshold: 2.8 },
  source: 'stored',
} as never

describe('算料口径域面板（issue #6580 抽取后的行为面）', () => {
  it('有读数 ⇒ 逐条参数成行（人话名 + 「改它会怎样」都在）', () => {
    render(<CalcCaliberPanel calc={CALC} calcError="" loading={false} />)
    expect(screen.getByTestId('param-per_fold_single')).toBeInTheDocument()
    expect(screen.getByText('单色每折吃布（米）')).toBeInTheDocument()
    expect(screen.getAllByText(/改它会怎样/).length).toBeGreaterThan(0)
  })

  it('🔴 引擎键名不上屏（§31 P3）—— 但机器锚点 `param-<key>` / `param-value-<key>` 全部保留', () => {
    render(<CalcCaliberPanel calc={CALC} calcError="" loading={false} />)
    // 展示面：键名一个字都不许出现（改前 6 个键名原样印在数值位下方）
    for (const key of ['per_fold_single', 'margin_single', 'oversize_width_threshold']) {
      expect(screen.queryByText(key)).toBeNull()
    }
    // 机器锚点在（判据依赖它们，删了就是把判据一起删了）
    expect(screen.getByTestId('param-per_fold_single')).toBeInTheDocument()
    expect(screen.getByTestId('param-value-per_fold_single')).toHaveTextContent('0.3')
  })

  it('🔴 读失败 ⇒ 显示**页面给的那句**归因话术（面板不自己编），且**不把「读不到」画成「未配置」**', () => {
    const copy = '算料口径暂时读不到（读数服务暂时不可用，不是你的权限问题）—— 请稍后重试'
    render(<CalcCaliberPanel calc={null} calcError={copy} loading={false} />)
    expect(screen.getByTestId('param-calc-error')).toHaveTextContent(copy)

    // 关键判据（三态不互画）：读失败时**不许**说「本企业尚未保存过算料口径」
    expect(screen.queryByTestId('param-calc-using-default')).toBeNull()
    expect(screen.queryByText(/正在用引擎默认值/)).toBeNull()
    // 也不许给参数打「未配置」徽标（那是读成功才知道的事）
    expect(screen.queryByTestId('param-unset-per_fold_single')).toBeNull()
  })

  it('🔴 读失败 ⇒ **不画参数卡**（不用一排 `—` 冒充读数），且失败行带重试出口（issue #6663）', () => {
    const onRetry = vi.fn()
    render(<CalcCaliberPanel calc={null} calcError="读不到" loading={false} onRetry={onRetry} />)

    // ① 一个参数卡都不渲染 —— 更不会有 `—`（改前的形态：一屏 6 个 `—`，像「这些参数是空的」）
    expect(screen.queryByTestId('param-per_fold_single')).toBeNull()
    expect(screen.queryByTestId('param-value-per_fold_single')).toBeNull()
    expect(screen.queryByText('—')).toBeNull()
    // ② 失败态有出口（真可点）
    fireEvent.click(screen.getByTestId('param-calc-retry'))
    expect(onRetry).toHaveBeenCalledTimes(1)
    // ③ 一处失败只留一行（本面板里失败类文案恰好一条）
    expect(screen.getAllByText(/读不到/)).toHaveLength(1)
  })

  it('加载中 ⇒ 不出现「未配置（正在用引擎默认值）」这类结论（三态不互画）', () => {
    render(<CalcCaliberPanel calc={null} calcError="" loading />)
    expect(screen.queryByText(/未配置/)).toBeNull()
    expect(screen.queryByText(/引擎默认/)).toBeNull()
  })
})

/**
 * 🔴 v2（issue #6585）：算料域**自己就是编辑面** ⇒ 面板不许再挂「去算料配置」那种**跳出本页**的外链。
 *
 * 缺陷形态：改前它渲染 `PARAM_DOMAINS.calc.edit` = `{ href: '/production/routings?tab=calc', label: '去算料配置' }`
 * —— 用户点过去，落到的却是**旧路由**（v2 已把那个 tab 拆掉）⇒ 同一份配置两个入口 + 死路。
 */
it('不再挂「去算料配置」外链（域自己就是编辑面，不许把人送出页面）', () => {
  render(<CalcCaliberPanel calc={null} calcError="" loading={false} />)
  expect(screen.queryByTestId('param-edit-calc')).toBeNull()
  expect(screen.queryByText(/去算料配置/)).toBeNull()
})
