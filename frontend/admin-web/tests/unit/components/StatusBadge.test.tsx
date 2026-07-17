// @vitest-environment jsdom
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import StatusBadge from '@/components/ui/StatusBadge'

describe('StatusBadge Component', () => {
  it('renders label text', () => {
    render(<StatusBadge label="出售中" color="bg-green-50 text-green-700 border-green-200" />)
    expect(screen.getByText('出售中')).toBeInTheDocument()
  })

  it('renders with whitespace-nowrap and truncate classes for single-line display', () => {
    render(<StatusBadge label="出售中" color="bg-green-50 text-green-700 border-green-200" />)
    const badge = screen.getByText('出售中')
    expect(badge.className).toMatch(/\bwhitespace-nowrap\b/)
    expect(badge.className).toMatch(/\btruncate\b/)
  })

  it('sets title attribute for hover tooltip on long text', () => {
    render(<StatusBadge label="这是一个非常长的状态文本需要截断显示" color="bg-gray-50 text-gray-700 border-gray-200" />)
    const badge = screen.getByText('这是一个非常长的状态文本需要截断显示')
    expect(badge.getAttribute('title')).toBe('这是一个非常长的状态文本需要截断显示')
  })

  it('renders dot indicator when dot=true', () => {
    render(<StatusBadge label="待付款" color="bg-amber-50 text-amber-700 border-amber-200" dot />)
    const dot = document.querySelector('.rounded-full')
    expect(dot).toBeInTheDocument()
    expect(dot?.className).toContain('w-1.5')
    expect(dot?.className).toContain('h-1.5')
  })

  it('does not render dot when dot=false', () => {
    render(<StatusBadge label="出售中" color="bg-green-50 text-green-700 border-green-200" />)
    const dot = document.querySelector('.rounded-full')
    expect(dot).toBeNull()
  })

  it('applies color classes to the badge', () => {
    render(<StatusBadge label="已完成" color="bg-green-50 text-green-700 border-green-200" />)
    const badge = screen.getByText('已完成')
    expect(badge.className).toContain('bg-green-50')
    expect(badge.className).toContain('text-green-700')
    expect(badge.className).toContain('border-green-200')
  })

  it('calls onClick when clicked', () => {
    const onClick = vi.fn()
    render(<StatusBadge label="待处理" color="bg-amber-50 text-amber-700 border-amber-200" onClick={onClick} />)
    fireEvent.click(screen.getByText('待处理'))
    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it('has cursor-pointer when onClick is provided', () => {
    render(<StatusBadge label="待处理" color="bg-amber-50 text-amber-700 border-amber-200" onClick={vi.fn()} />)
    const badge = screen.getByText('待处理')
    expect(badge.className).toContain('cursor-pointer')
  })

  it('does not have cursor-pointer when no onClick', () => {
    render(<StatusBadge label="已完成" color="bg-green-50 text-green-700 border-green-200" />)
    const badge = screen.getByText('已完成')
    expect(badge.className).not.toContain('cursor-pointer')
  })

  it('merges custom className', () => {
    render(<StatusBadge label="测试" color="bg-gray-50 text-gray-700 border-gray-200" className="extra-class" />)
    expect(screen.getByText('测试').className).toContain('extra-class')
  })

  it('renders inline-flex for proper badge display', () => {
    render(<StatusBadge label="出售中" color="bg-green-50 text-green-700 border-green-200" />)
    const badge = screen.getByText('出售中')
    expect(badge.className).toContain('inline-flex')
  })
})
