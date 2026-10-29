// case_ids: CH-008, UI-024
/**
 * `LogisticsCard`（C 端 / B 端共用的物流卡）—— issue #6664 第 5 条。
 *
 * 缺陷形态：服务端下发的是内部键（`in_transit`），卡头**原样**把它印成状态胶囊
 * ⇒ 商家用户读不懂，且一眼看出是给谁做的。
 *
 * 判据形态（**带判别力自证**）：已知枚举 ⇒ 中文人话；**未知枚举 ⇒ 人话兜底且不出现原值**；
 * 已是中文的展示值（服务端历史上两种口径都下发过）⇒ 原样放行、不吞。
 */
import React from 'react'
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import LogisticsCard, { logisticsStatusLabel } from '@/components/chat/LogisticsCard'

describe('LogisticsCard 物流状态：内部键 → 人话（issue #6664 第 5 条）', () => {
  it('① 已知枚举 in_transit ⇒ 「运输中」，**不出现**英文原值', () => {
    render(<LogisticsCard data={{ tracking_info: { trackingNo: 'SF1', company: '顺丰', status: 'in_transit' } }} />)
    expect(screen.getByText('运输中')).toBeInTheDocument()
    expect(screen.getByText('SF1', { exact: false })).toBeInTheDocument()
    expect(screen.queryByText('in_transit')).toBeNull()
  })

  it('② 判别力自证：**未知**枚举 ⇒ 人话兜底「状态待确认」，**不出现**原值', () => {
    render(<LogisticsCard data={{ tracking_info: { trackingNo: 'SF1', status: 'weird_new_state' } }} />)
    expect(screen.getByText('状态待确认')).toBeInTheDocument()
    expect(screen.queryByText('weird_new_state')).toBeNull()
  })

  it('③ 已是中文的展示值原样放行（服务端两种口径都下发过，不吞）', () => {
    render(<LogisticsCard data={{ company: '京东物流', status: '派送中', tracks: [{ description: '快递员正在派送', time: '2025-01-01' }] }} />)
    expect(screen.getByText('派送中')).toBeInTheDocument()
    expect(screen.queryByText('状态待确认')).toBeNull()
  })

  it('④ 纯函数口径逐值可判（不给渲染留模糊空间）', () => {
    expect(logisticsStatusLabel('in_transit')).toBe('运输中')
    expect(logisticsStatusLabel('weird_new_state')).toBe('状态待确认')
    expect(logisticsStatusLabel('派送中')).toBe('派送中')
    expect(logisticsStatusLabel('')).toBe('')
  })
})

describe('LogisticsCard 物流类型：追单时看得出是快递还是专线（issue #8080）', () => {
  it('⑤ 有类型 ⇒ 印中文；两种键名（snake 卡载荷 / camel 详情读面）都认', () => {
    const { unmount } = render(
      <LogisticsCard data={{ tracking_no: 'SJA001', company: '四季安', logistics_type: 'logistics' }} />,
    )
    expect(screen.getByTestId('logistics-type').textContent).toBe('物流类型：物流/专线')
    unmount()

    render(
      <LogisticsCard data={{ tracking_info: { trackingNo: 'SF1', company: '顺丰', logisticsType: 'express' } }} />,
    )
    expect(screen.getByTestId('logistics-type').textContent).toBe('物流类型：快递')
  })

  it('⑥ 未采集 ⇒ **整行不印**（负控：换成 logisticsTypeLabel() 回退「快递」⇒ 红）', () => {
    render(<LogisticsCard data={{ tracking_info: { trackingNo: 'SF1', company: '顺丰', status: 'in_transit' } }} />)
    expect(screen.queryByTestId('logistics-type')).toBeNull()
    expect(screen.queryByText('快递')).toBeNull()
    expect(screen.queryByText('物流类型：', { exact: false })).toBeNull()
  })
})
