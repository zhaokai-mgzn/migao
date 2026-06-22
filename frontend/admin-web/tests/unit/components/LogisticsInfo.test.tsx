import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import LogisticsInfo from '@/components/orders/LogisticsInfo'

describe('LogisticsInfo — #686 logisticsCompany 字段名修复', () => {
  it('truth_1: 物流公司 + 运单号同时渲染', () => {
    const logistics = {
      logisticsCompany: '顺丰速运',
      trackingNo: 'SF1234567890',
    }

    render(<LogisticsInfo logistics={logistics} />)

    // 物流公司应该显示
    expect(screen.getByText('顺丰速运')).toBeInTheDocument()
    // 运单号应该显示
    expect(screen.getByText('SF1234567890')).toBeInTheDocument()
    // 标签存在
    expect(screen.getByText('物流公司')).toBeInTheDocument()
    expect(screen.getByText('运单号')).toBeInTheDocument()
  })

  it('truth_2: 仅改物流公司（运单号留空）→ 物流公司显示', () => {
    const logistics = {
      logisticsCompany: '中通快递',
      trackingNo: '',
    }

    render(<LogisticsInfo logistics={logistics} />)

    // 物流公司应该显示
    expect(screen.getByText('中通快递')).toBeInTheDocument()
    // 运单号不应显示（empty string）
    expect(screen.queryByText('运单号')).not.toBeInTheDocument()
  })

  it('shows empty state when logistics is undefined', () => {
    render(<LogisticsInfo logistics={undefined} />)

    expect(screen.getByText('物流信息')).toBeInTheDocument()
    expect(screen.getByText('暂无物流信息')).toBeInTheDocument()
  })

  it('shows empty state when both logisticsCompany and trackingNo are empty', () => {
    const logistics = {
      logisticsCompany: '',
      trackingNo: '',
    }

    render(<LogisticsInfo logistics={logistics} />)

    expect(screen.getByText('暂无物流信息')).toBeInTheDocument()
  })
})
