import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

// Mock next/link
vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

import ActiveSessions from '@/components/dashboard/ActiveSessions'
import type { ActiveSession } from '@/types'

const mockSessions: ActiveSession[] = [
  {
    id: 'session-1',
    customerName: '王五',
    channel: 'wechat_mini',
    lastMessage: '我想要定制一套沙发套',
    duration: '5分钟',
    isAI: true,
    startedAt: '2025-01-15T10:30:00Z',
  },
  {
    id: 'session-2',
    customerName: '赵六',
    channel: 'h5',
    lastMessage: '怎么清洗窗帘布',
    duration: '12分钟',
    isAI: false,
    startedAt: '2025-01-15T10:18:00Z',
  },
  {
    id: 'session-3',
    customerName: '邓八',
    channel: 'unknown_channel',
    lastMessage: 'test message',
    duration: '1分钟',
    isAI: true,
    startedAt: '2025-01-15T09:00:00Z',
  },
]

describe('ActiveSessions', () => {
  // --- Rendering basics ---
  it('renders the title "活跃会话"', () => {
    render(<ActiveSessions sessions={[]} />)
    expect(screen.getByText('活跃会话')).toBeInTheDocument()
  })

  it('renders "查看全部" link pointing to /chat', () => {
    render(<ActiveSessions sessions={mockSessions} />)
    const link = screen.getByText('查看全部')
    expect(link.closest('a')).toHaveAttribute('href', '/chat')
  })

  // --- Loading state ---
  it('shows loading spinner when loading=true', () => {
    render(<ActiveSessions sessions={[]} loading={true} />)
    expect(document.querySelector('.animate-spin')).toBeInTheDocument()
  })

  it('hides loading spinner when loading=false', () => {
    render(<ActiveSessions sessions={mockSessions} loading={false} />)
    expect(document.querySelector('.animate-spin')).not.toBeInTheDocument()
  })

  // --- Empty state ---
  it('shows "暂无活跃会话" when sessions is empty and not loading', () => {
    render(<ActiveSessions sessions={[]} />)
    expect(screen.getByText('暂无活跃会话')).toBeInTheDocument()
  })

  it('does not show empty state when sessions exist', () => {
    render(<ActiveSessions sessions={mockSessions} />)
    expect(screen.queryByText('暂无活跃会话')).not.toBeInTheDocument()
  })

  // --- Session count in title ---
  it('shows session count in title when sessions > 0', () => {
    render(<ActiveSessions sessions={mockSessions} />)
    expect(screen.getByText('(3)')).toBeInTheDocument()
  })

  it('does not show count when sessions is empty', () => {
    render(<ActiveSessions sessions={[]} />)
    expect(screen.queryByText('(0)')).not.toBeInTheDocument()
  })

  // --- Customer names ---
  it('renders customer names in session cards', () => {
    render(<ActiveSessions sessions={mockSessions} />)
    expect(screen.getByText('王五')).toBeInTheDocument()
    expect(screen.getByText('赵六')).toBeInTheDocument()
    expect(screen.getByText('邓八')).toBeInTheDocument()
  })

  // --- AI vs Human session ---
  it('shows "AI" badge for AI-powered sessions', () => {
    render(<ActiveSessions sessions={mockSessions} />)
    const aiBadges = screen.getAllByText('AI')
    expect(aiBadges.length).toBe(2) // session-1 and session-3
  })

  it('shows "人工" badge for human sessions', () => {
    render(<ActiveSessions sessions={mockSessions} />)
    expect(screen.getByText('人工')).toBeInTheDocument()
  })

  it('shows Bot icon for AI sessions', () => {
    render(<ActiveSessions sessions={mockSessions} />)
    // Bot icons appear for AI sessions (session-1, session-3)
    expect(screen.getAllByTestId('icon-bot').length).toBe(2)
  })

  it('shows User icon for human sessions', () => {
    render(<ActiveSessions sessions={mockSessions} />)
    expect(screen.getByTestId('icon-user')).toBeInTheDocument()
  })

  // --- Last message ---
  it('renders last message text', () => {
    render(<ActiveSessions sessions={mockSessions} />)
    expect(screen.getByText('我想要定制一套沙发套')).toBeInTheDocument()
    expect(screen.getByText('怎么清洗窗帘布')).toBeInTheDocument()
  })

  // --- Channel labels ---
  it('shows known channel label for wechat_mini', () => {
    render(<ActiveSessions sessions={mockSessions} />)
    expect(screen.getByText('小程序')).toBeInTheDocument()
  })

  it('shows known channel label for H5', () => {
    render(<ActiveSessions sessions={mockSessions} />)
    expect(screen.getByText('H5')).toBeInTheDocument()
  })

  it('falls back to raw channel string for unknown channels', () => {
    render(<ActiveSessions sessions={mockSessions} />)
    expect(screen.getByText('unknown_channel')).toBeInTheDocument()
  })

  // --- Duration ---
  it('renders session duration', () => {
    render(<ActiveSessions sessions={mockSessions} />)
    expect(screen.getByText('5分钟')).toBeInTheDocument()
    expect(screen.getByText('12分钟')).toBeInTheDocument()
    expect(screen.getByText('1分钟')).toBeInTheDocument()
  })
})
