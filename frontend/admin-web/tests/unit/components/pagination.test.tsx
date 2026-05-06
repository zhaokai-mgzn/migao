import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// Mock lucide-react
vi.mock('lucide-react', () => {
  const stub = (name: string) => (props: any) => <span data-testid={`icon-${name}`} {...props} />
  return {
    ChevronLeft: stub('chevron-left'),
    ChevronRight: stub('chevron-right'),
  }
})

// Mock Button component
vi.mock('@/components/ui/Button', () => ({
  default: ({ children, onClick, ...props }: any) => (
    <button onClick={onClick} {...props}>{children}</button>
  ),
}))

import Pagination from '@/components/ui/Pagination'

describe('Pagination Component', () => {
  const user = userEvent.setup()

  it('should render total record count', () => {
    render(<Pagination current={1} pageSize={10} total={100} onChange={vi.fn()} />)
    expect(screen.getByText('100')).toBeInTheDocument()
    expect(screen.getByText(/共/)).toBeInTheDocument()
  })

  it('should render current range info', () => {
    render(<Pagination current={1} pageSize={10} total={100} onChange={vi.fn()} />)
    expect(screen.getByText(/第 1-10 条/)).toBeInTheDocument()
  })

  it('should render correct range for page 2', () => {
    render(<Pagination current={2} pageSize={10} total={100} onChange={vi.fn()} />)
    expect(screen.getByText(/第 11-20 条/)).toBeInTheDocument()
  })

  it('should render correct range for last page', () => {
    render(<Pagination current={4} pageSize={10} total={35} onChange={vi.fn()} />)
    expect(screen.getByText(/第 31-35 条/)).toBeInTheDocument()
  })

  it('should render page number buttons', () => {
    render(<Pagination current={1} pageSize={10} total={50} onChange={vi.fn()} />)
    expect(screen.getByText('1')).toBeInTheDocument()
    expect(screen.getByText('5')).toBeInTheDocument()
  })

  it('should call onChange when page number is clicked', async () => {
    const onChange = vi.fn()
    render(<Pagination current={1} pageSize={10} total={50} onChange={onChange} />)
    await user.click(screen.getByText('3'))
    expect(onChange).toHaveBeenCalledWith(3)
  })

  it('should disable prev button on first page', () => {
    render(<Pagination current={1} pageSize={10} total={50} onChange={vi.fn()} />)
    const buttons = screen.getAllByRole('button')
    // First navigation button (prev) should be disabled
    const prevBtn = buttons.find(b => b.querySelector('[data-testid="icon-chevron-left"]'))
    expect(prevBtn).toBeDisabled()
  })

  it('should disable next button on last page', () => {
    render(<Pagination current={5} pageSize={10} total={50} onChange={vi.fn()} />)
    const buttons = screen.getAllByRole('button')
    const nextBtn = buttons.find(b => b.querySelector('[data-testid="icon-chevron-right"]'))
    expect(nextBtn).toBeDisabled()
  })

  it('should call onChange with prev page', async () => {
    const onChange = vi.fn()
    render(<Pagination current={3} pageSize={10} total={50} onChange={onChange} />)
    const buttons = screen.getAllByRole('button')
    const prevBtn = buttons.find(b => b.querySelector('[data-testid="icon-chevron-left"]'))
    await user.click(prevBtn!)
    expect(onChange).toHaveBeenCalledWith(2)
  })

  it('should call onChange with next page', async () => {
    const onChange = vi.fn()
    render(<Pagination current={3} pageSize={10} total={50} onChange={onChange} />)
    const buttons = screen.getAllByRole('button')
    const nextBtn = buttons.find(b => b.querySelector('[data-testid="icon-chevron-right"]'))
    await user.click(nextBtn!)
    expect(onChange).toHaveBeenCalledWith(4)
  })

  it('should render page size selector', () => {
    render(
      <Pagination
        current={1}
        pageSize={10}
        total={100}
        onChange={vi.fn()}
        onPageSizeChange={vi.fn()}
      />
    )
    expect(screen.getByText('每页')).toBeInTheDocument()
    expect(screen.getByText('条')).toBeInTheDocument()
  })

  it('should call onPageSizeChange when page size is changed', async () => {
    const onPageSizeChange = vi.fn()
    render(
      <Pagination
        current={1}
        pageSize={10}
        total={100}
        onChange={vi.fn()}
        onPageSizeChange={onPageSizeChange}
      />
    )
    const select = screen.getByDisplayValue('10')
    await user.selectOptions(select, '20')
    expect(onPageSizeChange).toHaveBeenCalledWith(20)
  })

  it('should show ellipsis for many pages', () => {
    render(<Pagination current={5} pageSize={10} total={200} onChange={vi.fn()} />)
    const ellipsis = screen.getAllByText('...')
    expect(ellipsis.length).toBeGreaterThan(0)
  })

  it('should highlight current page', () => {
    render(<Pagination current={3} pageSize={10} total={50} onChange={vi.fn()} />)
    const currentButton = screen.getByText('3')
    expect(currentButton.className).toContain('bg-primary-600')
  })

  it('should hide total when showTotal is false', () => {
    render(
      <Pagination
        current={1}
        pageSize={10}
        total={100}
        onChange={vi.fn()}
        showTotal={false}
      />
    )
    expect(screen.queryByText(/共/)).not.toBeInTheDocument()
  })
})
