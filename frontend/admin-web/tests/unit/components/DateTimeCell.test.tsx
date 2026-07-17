// @vitest-environment jsdom
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import DateTimeCell from '@/components/common/DateTimeCell'

describe('DateTimeCell Component', () => {
  it('renders ISO date string in 2-line format: YYYY-MM-DD + HH:mm', () => {
    const { container } = render(<DateTimeCell value="2026-01-15T14:30:00.000Z" />)
    const outerDiv = container.firstChild as HTMLElement
    expect(outerDiv.tagName).toBe('DIV')
    expect(outerDiv.childNodes.length).toBe(2)
    expect(outerDiv.textContent).toMatch(/2026-01-\d{2}/)
    expect(outerDiv.textContent).toMatch(/\d{2}:\d{2}/)
  })

  it('renders date in first child and time in second child', () => {
    render(<DateTimeCell value="2026-07-16T09:05:00+08:00" />)
    expect(screen.getByText(/2026-07-16/)).toBeInTheDocument()
    expect(screen.getByText(/09:05/)).toBeInTheDocument()
  })

  it('renders two-line layout: date div above time div', () => {
    const { container } = render(<DateTimeCell value="2026-06-01T12:00:00+08:00" />)
    const outerDiv = container.firstChild as HTMLElement
    expect(outerDiv.textContent).toMatch(/2026-06-01/)
    expect(outerDiv.textContent).toMatch(/12:00/)
  })

  it('displays "-" when value is undefined', () => {
    render(<DateTimeCell value={undefined} />)
    expect(screen.getByText('-')).toBeInTheDocument()
  })

  it('displays "-" when value is null', () => {
    render(<DateTimeCell value={null as any} />)
    expect(screen.getByText('-')).toBeInTheDocument()
  })

  it('displays "-" when value is an empty string', () => {
    render(<DateTimeCell value="" />)
    expect(screen.getByText('-')).toBeInTheDocument()
  })

  it('displays original string when value is an invalid date string', () => {
    render(<DateTimeCell value="not-a-date" />)
    expect(screen.getByText('not-a-date')).toBeInTheDocument()
  })

  it('renders correctly with midnight time (00:00)', () => {
    render(<DateTimeCell value="2026-07-16T00:00:00+08:00" />)
    expect(screen.getByText(/00:00/)).toBeInTheDocument()
  })

  it('renders same date+time pattern for different times of day', () => {
    const { container: c1 } = render(<DateTimeCell value="2026-01-01T08:00:00+08:00" />)
    const text1 = (c1.firstChild as HTMLElement).textContent || ''

    const { container: c2 } = render(<DateTimeCell value="2026-12-31T23:59:00+08:00" />)
    const text2 = (c2.firstChild as HTMLElement).textContent || ''

    const datePattern = /\d{4}-\d{2}-\d{2}/
    const timePattern = /\d{2}:\d{2}/
    expect(text1).toMatch(datePattern)
    expect(text1).toMatch(timePattern)
    expect(text2).toMatch(datePattern)
    expect(text2).toMatch(timePattern)
  })

  it('handles +08:00 offset ISO strings', () => {
    const { container } = render(<DateTimeCell value="2026-03-15T16:45:00+08:00" />)
    const text = (container.firstChild as HTMLElement).textContent || ''
    expect(text).toMatch(/2026-03-15/)
    expect(text).toMatch(/16:45/)
  })
})
