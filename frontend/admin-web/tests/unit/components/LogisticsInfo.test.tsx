// @vitest-environment jsdom
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
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

  // ===== 增强测试：物流状态、轨迹、编辑回调、className =====

  it('shows logistics status when provided', () => {
    const logistics = {
      logisticsCompany: '顺丰速运',
      trackingNo: 'SF1234567890',
      status: '运输中',
    }

    render(<LogisticsInfo logistics={logistics} />)

    expect(screen.getByText('当前状态: 运输中')).toBeInTheDocument()
  })

  it('does not show status section when status is empty', () => {
    const logistics = {
      logisticsCompany: '顺丰速运',
      trackingNo: 'SF1234567890',
    }

    render(<LogisticsInfo logistics={logistics} />)

    expect(screen.queryByText(/当前状态:/)).not.toBeInTheDocument()
  })

  it('renders logistics tracks when provided', () => {
    const logistics = {
      logisticsCompany: '顺丰速运',
      trackingNo: 'SF1234567890',
      tracks: [
        { time: '2025-06-20T10:00:00Z', description: '快件已签收' },
        { time: '2025-06-19T08:00:00Z', description: '快件在运输中' },
      ],
    }

    render(<LogisticsInfo logistics={logistics} />)

    expect(screen.getByText('物流轨迹')).toBeInTheDocument()
    expect(screen.getByText('快件已签收')).toBeInTheDocument()
    expect(screen.getByText('快件在运输中')).toBeInTheDocument()
  })

  it('renders track times formatted', () => {
    const logistics = {
      logisticsCompany: '顺丰速运',
      trackingNo: 'SF1234567890',
      tracks: [
        { time: '2025-06-20T10:30:00Z', description: '已签收' },
      ],
    }

    render(<LogisticsInfo logistics={logistics} />)

    expect(screen.getByText('2025-06-20 18:30:00')).toBeInTheDocument()
  })

  it('does not render tracks section when tracks is empty array', () => {
    const logistics = {
      logisticsCompany: '顺丰速运',
      trackingNo: 'SF1234567890',
      tracks: [],
    }

    render(<LogisticsInfo logistics={logistics} />)

    expect(screen.queryByText('物流轨迹')).not.toBeInTheDocument()
  })

  it('highlights first track with blue dot', () => {
    const logistics = {
      logisticsCompany: '顺丰速运',
      trackingNo: 'SF1234567890',
      tracks: [
        { time: '2025-06-20T10:00:00Z', description: '最新状态' },
        { time: '2025-06-19T08:00:00Z', description: '历史状态' },
      ],
    }

    const { container } = render(<LogisticsInfo logistics={logistics} />)

    // First track dot should have blue-500 class
    const dots = container.querySelectorAll('.rounded-full')
    const firstDot = dots[0]
    expect(firstDot.className).toContain('bg-blue-500')
  })

  describe('onEdit callback', () => {
    it('shows "录入物流" button when onEdit is provided and no logistics data', () => {
      const onEdit = vi.fn()
      render(<LogisticsInfo logistics={undefined} onEdit={onEdit} />)

      expect(screen.getByText('录入物流')).toBeInTheDocument()
    })

    it('shows "更新物流" button when onEdit is provided and logistics data exists', () => {
      const onEdit = vi.fn()
      const logistics = {
        logisticsCompany: '顺丰速运',
        trackingNo: 'SF1234567890',
      }

      render(<LogisticsInfo logistics={logistics} onEdit={onEdit} />)

      expect(screen.getByText('更新物流')).toBeInTheDocument()
    })

    it('calls onEdit when "录入物流" button is clicked', () => {
      const onEdit = vi.fn()
      render(<LogisticsInfo logistics={undefined} onEdit={onEdit} />)

      fireEvent.click(screen.getByText('录入物流'))
      expect(onEdit).toHaveBeenCalledTimes(1)
    })

    it('calls onEdit when "更新物流" button is clicked', () => {
      const onEdit = vi.fn()
      const logistics = {
        logisticsCompany: '顺丰速运',
        trackingNo: 'SF1234567890',
      }

      render(<LogisticsInfo logistics={logistics} onEdit={onEdit} />)

      fireEvent.click(screen.getByText('更新物流'))
      expect(onEdit).toHaveBeenCalledTimes(1)
    })

    it('does not show edit button when onEdit is not provided', () => {
      const logistics = {
        logisticsCompany: '顺丰速运',
        trackingNo: 'SF1234567890',
      }

      render(<LogisticsInfo logistics={logistics} />)

      expect(screen.queryByText('更新物流')).not.toBeInTheDocument()
    })
  })

  describe('className prop', () => {
    it('applies custom className when logistics exist', () => {
      const logistics = {
        logisticsCompany: '顺丰速运',
        trackingNo: 'SF1234567890',
      }

      const { container } = render(
        <LogisticsInfo logistics={logistics} className="custom-class" />
      )
      expect(container.firstChild).toHaveClass('custom-class')
    })

    it('applies custom className in empty state', () => {
      const { container } = render(
        <LogisticsInfo logistics={undefined} className="custom-class" />
      )
      expect(container.firstChild).toHaveClass('custom-class')
    })
  })
})
