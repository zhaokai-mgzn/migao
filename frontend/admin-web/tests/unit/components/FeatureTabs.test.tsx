// case_ids: UI-082
import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { FeatureTabs } from '@/components/corporate/FeatureTabs'

describe('FeatureTabs（官网场景标签）', () => {
  const tabs = ['接待', '算料', '下单']
  const details = ['说明一', '说明二', '说明三']

  it('默认选中第一个标签并展示对应说明', () => {
    render(<FeatureTabs tabs={tabs} details={details} />)
    expect(screen.getByRole('tab', { name: '接待' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByText('说明一')).toBeInTheDocument()
  })

  it('点击标签切换说明与选中态', () => {
    render(<FeatureTabs tabs={tabs} details={details} />)
    fireEvent.click(screen.getByRole('tab', { name: '算料' }))
    expect(screen.getByRole('tab', { name: '算料' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: '接待' })).toHaveAttribute('aria-selected', 'false')
    expect(screen.getByText('说明二')).toBeInTheDocument()
    expect(screen.queryByText('说明一')).not.toBeInTheDocument()
  })
})
