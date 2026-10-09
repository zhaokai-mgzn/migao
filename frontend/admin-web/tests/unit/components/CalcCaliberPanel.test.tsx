// case_ids: UI-054
/**
 * 「算料口径」域面板（issue #6580）—— 从 `TenantParamsPanel` 抽出的算料域**读面 + 编辑面**。
 *
 * 本文件判的是抽取后**必须保持**的三件事（抽取的判据就是「行为一字不变」）：
 * 1. 有读数 ⇒ 每个标量参数都有一行（键 + 人话 + 「改它会怎样」），不是只显示名字；
 * 2. `calcError` ⇒ 显示**传进来的**那句分流话术（面板不自己编话术 —— 归因判据在页面里），
 *    且**不**渲染参数行（读失败时不许把值画成「没配」）；
 * 3. `loading` ⇒ 不出现「未配置」这类结论（三态不互画）。
 */
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import CalcCaliberPanel from '@/components/settings/CalcCaliberPanel'

/** 一条最小可用读数（键取引擎真值源里的 `per_fold_single`；值 = 0.3） */
const CALC = {
  config: { per_fold_single: 0.3, margin_single: 0.05, oversize_width_threshold: 2.8 },
  source: 'stored',
} as never

describe('算料口径域面板（issue #6580 抽取后的行为面）', () => {
  it('有读数 ⇒ 逐条参数成行（人话名 + 键 + 「改它会怎样」都在）', () => {
    render(<CalcCaliberPanel calc={CALC} calcError="" loading={false} />)
    expect(screen.getByTestId('param-per_fold_single')).toBeInTheDocument()
    // 🔴 §22 P3：键是**给实施/对账用**的，不许当成人话名 —— 两者必须同屏共存
    expect(screen.getByText('单色每折吃布（米）')).toBeInTheDocument()
    expect(screen.getAllByText(/改它会怎样/).length).toBeGreaterThan(0)
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
    // 值位是**中性**的「—」：不是 0、不是「未配置」、也不是空白
    expect(screen.getByTestId('param-value-per_fold_single')).toHaveTextContent('—')
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
