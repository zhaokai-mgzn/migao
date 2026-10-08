// case_ids: UI-054
/**
 * 「配置主线」条（`ConfigReadinessBar`）**渲染面**守卫（issue #6573）。
 *
 * 分工：
 * - 纯判据（三态怎么算）在 `frontend/admin-web/tests/unit/lib/config-readiness.test.ts`；
 * - 页面怎么取数 / 怎么把三态喂进来在 `frontend/admin-web/tests/unit/pages/settings-params.test.tsx`；
 * - **本文件只判这块常驻面自己**：折叠与展开的 DOM 事实、三态各自怎么说、摘要措辞、
 *   以及 `migao-dev-flow` §31 的三条形态纪律（P1 常驻面克制 / P2 信息不重复 / P3 不摆内部标识 / P4 语调）。
 *
 * 🔴 本组件是**展示组件**（props：`states` + `loading`，不取数、不判定）——
 * 所以这里的每条断言都能靠 props 精确驱动，不需要 mock `@/lib/api`，也没有竞态窗口。
 *
 * 红证形态（都在下面各条里）：
 * - 把 `{open && …}` 改成 CSS 隐藏 / `sr-only` ⇒ 判据 1 的 `toBeNull()` 必红（**折叠态 DOM 必须真的不存在**）；
 * - 把 `states[s.key] ?? 'unknown'` 改回 `?? 'todo'` ⇒ 判据 6 必红（缺键 = 读不到 ≠ 未配置）；
 * - 把 `loading` 分支删掉 ⇒ 判据 2 必红（加载中会按空 `states` 把五步全画成「待配置」）。
 */
import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConfigReadinessBar } from '@/components/settings/ConfigReadinessBar'
import { MAINLINE_STEPS, type ReadinessState } from '@/lib/config-readiness'

/** 五步全给同一个态（省得每条用例手写五遍） */
function allStates(state: ReadinessState): Record<string, ReadinessState> {
  return Object.fromEntries(MAINLINE_STEPS.map((s) => [s.key, state]))
}

function renderBar(states: Record<string, ReadinessState>, loading = false) {
  return render(<ConfigReadinessBar states={states} loading={loading} />)
}

describe('判据 1：常驻面克制（§31 P1）—— 折叠态只有一行摘要，逐项 DOM **不渲染**', () => {
  it('初始折叠：摘要与展开按钮在；`config-readiness-list` 与每个 `readiness-item-*` 均取不到', () => {
    renderBar(allStates('todo'))

    expect(screen.getByTestId('config-readiness')).toBeInTheDocument()
    expect(screen.getByTestId('config-readiness-toggle')).toHaveAttribute('aria-expanded', 'false')
    expect(screen.getByTestId('config-readiness-headline')).toBeInTheDocument()

    // 🔴 关键：**DOM 里没有**，不是「被 CSS 藏起来」——这条把「折叠」与「看不见」分开判
    expect(screen.queryByTestId('config-readiness-list')).toBeNull()
    for (const step of MAINLINE_STEPS) {
      expect(screen.queryByTestId(`readiness-item-${step.key}`)).toBeNull()
      expect(screen.queryByTestId(`readiness-goto-${step.key}`)).toBeNull()
    }
  })

  it('点开 ⇒ 五步逐项上屏（状态 + 去处）；再点收起 ⇒ 又取不到（不是单向副作用）', async () => {
    const user = userEvent.setup()
    renderBar(allStates('done'))

    await user.click(screen.getByTestId('config-readiness-toggle'))
    expect(screen.getByTestId('config-readiness-toggle')).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getAllByTestId(/^readiness-item-/)).toHaveLength(MAINLINE_STEPS.length)

    for (const step of MAINLINE_STEPS) {
      const item = screen.getByTestId(`readiness-item-${step.key}`)
      // 去处必须真的可点，且落在该步登记的 href 上（文案/页面漂移 ⇒ 红）
      expect(within(item).getByTestId(`readiness-goto-${step.key}`)).toHaveAttribute(
        'href',
        step.href,
      )
      expect(within(item).getByTestId(`readiness-state-${step.key}`)).toHaveTextContent('已配置')
      expect(within(item).getByText(step.label)).toBeInTheDocument()
    }

    await user.click(screen.getByTestId('config-readiness-toggle'))
    expect(screen.queryByTestId('config-readiness-list')).toBeNull()
    expect(screen.queryAllByTestId(/^readiness-item-/)).toHaveLength(0)
    // ⚠️ 用 `queryAllByTestId` 而不是 `getAllByTestId`：**零命中时后者抛错**，
    //    而「一条都不该有」正是本行要断言的事实（抛错与断言失败在报告里长得一样）。
  })
})

describe('判据 2：读数在路上 ⇒ 不谎报（加载中不说「未配置」）', () => {
  it('loading ⇒ 摘要说「读取中」，且**全屏**不出现「待配置」/「未配置」（states 还没到）', () => {
    renderBar({}, true)

    expect(screen.getByTestId('config-readiness-headline')).toHaveTextContent('配置主线读取中')
    expect(screen.queryByText(/未配置/)).toBeNull()
    expect(screen.queryByText(/待配置/)).toBeNull()
  })
})

describe('判据 3：三态各有各的说法，互不冒充', () => {
  it('全 done ⇒ 摘要「配置已完成 5/5」，且**不**出现「下一步」', () => {
    renderBar(allStates('done'))
    const headline = screen.getByTestId('config-readiness-headline')
    expect(headline).toHaveTextContent('配置已完成 5/5')
    expect(headline).not.toHaveTextContent('下一步')
    expect(headline).not.toHaveTextContent('未配置')
  })

  it('有 todo ⇒ 摘要给「几项未配置」+ 点名的下一步（= MAINLINE_STEPS 里第一个 todo 步）', () => {
    // 只把第 2 步（工艺路线）判 todo，其余 done ⇒ 下一步必须点名「工艺路线」
    renderBar({ ...allStates('done'), routings: 'todo' })
    const headline = screen.getByTestId('config-readiness-headline')
    expect(headline).toHaveTextContent('配置完成 4/5')
    expect(headline).toHaveTextContent('1 项未配置')
    expect(headline).toHaveTextContent('下一步「工艺路线」')
  })

  it('只有 unknown ⇒ 摘要说「读不到（刷新可重试）」，**不许**说成「未配置」', () => {
    renderBar(allStates('unknown'))
    const headline = screen.getByTestId('config-readiness-headline')
    expect(headline).toHaveTextContent('读不到')
    expect(headline).toHaveTextContent('刷新可重试')
    expect(headline).not.toHaveTextContent('未配置')
  })

  it('展开后逐项徽标逐字对应三态（done=已配置 / todo=待配置 / unknown=读不到）', async () => {
    const user = userEvent.setup()
    renderBar({ operations: 'done', routings: 'todo', 'default-route': 'unknown', 'fee-combinations': 'done', calc: 'unknown' })

    await user.click(screen.getByTestId('config-readiness-toggle'))
    expect(screen.getByTestId('readiness-state-operations')).toHaveTextContent('已配置')
    expect(screen.getByTestId('readiness-state-routings')).toHaveTextContent('待配置')
    expect(screen.getByTestId('readiness-state-default-route')).toHaveTextContent('读不到')
    expect(screen.getByTestId('readiness-state-calc')).toHaveTextContent('读不到')

    // 「不配会怎样」只在**没配好**的步出现；已配置的步不复述影响（P2 信息不重复）
    const doneItem = screen.getByTestId('readiness-item-operations')
    expect(within(doneItem).queryByText(/缺工序/)).toBeNull()
    const todoItem = screen.getByTestId('readiness-item-routings')
    expect(within(todoItem).getByText(/生成不了加工单/)).toBeInTheDocument()
  })
})

describe('判据 4：缺键 = 读不到（`?? unknown`，不是 `?? todo`）', () => {
  it('states = {} ⇒ 五步全「读不到」、一个「待配置」都没有（缺数据 ≠ 没配置）', async () => {
    const user = userEvent.setup()
    renderBar({})
    await user.click(screen.getByTestId('config-readiness-toggle'))

    for (const step of MAINLINE_STEPS) {
      expect(screen.getByTestId(`readiness-state-${step.key}`)).toHaveTextContent('读不到')
    }
    expect(screen.queryAllByText('待配置')).toHaveLength(0)
  })
})

describe('判据 5：不摆内部标识、语调不催促（§31 P3/P4）', () => {
  it('上屏文案里不出现权限码 / 端点 / 表名（内部标识只在代码里）', async () => {
    const user = userEvent.setup()
    renderBar(allStates('todo'))
    await user.click(screen.getByTestId('config-readiness-toggle'))

    const text = document.body.textContent ?? ''
    for (const leak of ['production:view', '/api/', 'craft_calc_configs', 'readiness-item']) {
      expect(text).not.toContain(leak)
    }
  })

  it('不催促：摘要与逐项文案里没有感叹号（只陈述事实 + 该做什么）', async () => {
    const user = userEvent.setup()
    renderBar(allStates('todo'))
    await user.click(screen.getByTestId('config-readiness-toggle'))

    const text = document.body.textContent ?? ''
    expect(text).not.toContain('!')
    expect(text).not.toContain('！')
  })
})
