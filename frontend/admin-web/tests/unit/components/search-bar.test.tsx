import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// Mock lucide-react
vi.mock('lucide-react', () => {
  const stub = (name: string) => (props: any) => <span data-testid={`icon-${name}`} {...props} />
  return {
    Search: stub('search'),
    X: stub('x'),
  }
})

// Mock UI sub-components
vi.mock('@/components/ui/Button', () => ({
  default: ({ children, onClick, loading, ...props }: any) => (
    <button onClick={onClick} disabled={loading} {...props}>{children}</button>
  ),
}))

vi.mock('@/components/ui/Input', () => ({
  default: ({ label, value, onChange, onKeyDown, ...props }: any) => (
    <div>
      <label htmlFor={`sb-${label}`}>{label}</label>
      <input id={`sb-${label}`} value={value} onChange={onChange} onKeyDown={onKeyDown} {...props} />
    </div>
  ),
}))

vi.mock('@/components/ui/Select', () => ({
  default: ({ label, options, value, onChange, ...props }: any) => (
    <div>
      <label htmlFor={`sb-sel-${label}`}>{label}</label>
      <select id={`sb-sel-${label}`} value={value} onChange={onChange}>
        {options?.map((o: any) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  ),
}))

import SearchBar from '@/components/ui/SearchBar'
import type { SearchField } from '@/components/ui/SearchBar'

describe('SearchBar Component', () => {
  const user = userEvent.setup()

  const fields: SearchField[] = [
    { key: 'keyword', label: '关键词', type: 'input', placeholder: '请输入关键词' },
    {
      key: 'status',
      label: '状态',
      type: 'select',
      options: [
        { value: '', label: '全部' },
        { value: 'active', label: '激活' },
        { value: 'inactive', label: '停用' },
      ],
    },
  ]

  it('should render input fields', () => {
    render(<SearchBar fields={fields} onSearch={vi.fn()} />)
    expect(screen.getByText('关键词')).toBeInTheDocument()
    expect(screen.getByText('状态')).toBeInTheDocument()
  })

  it('should render search and reset buttons', () => {
    render(<SearchBar fields={fields} onSearch={vi.fn()} onReset={vi.fn()} />)
    expect(screen.getByText('搜索')).toBeInTheDocument()
    expect(screen.getByText('重置')).toBeInTheDocument()
  })

  it('should call onSearch when search button is clicked', async () => {
    const onSearch = vi.fn()
    render(<SearchBar fields={fields} onSearch={onSearch} />)
    await user.click(screen.getByText('搜索'))
    expect(onSearch).toHaveBeenCalledWith({})
  })

  it('should call onSearch with field values', async () => {
    const onSearch = vi.fn()
    render(<SearchBar fields={fields} onSearch={onSearch} />)
    const input = screen.getByLabelText('关键词')
    await user.type(input, '窗帘')
    await user.click(screen.getByText('搜索'))
    expect(onSearch).toHaveBeenCalledWith(
      expect.objectContaining({ keyword: '窗帘' })
    )
  })

  it('should call onReset when reset button is clicked', async () => {
    const onReset = vi.fn()
    render(<SearchBar fields={fields} onSearch={vi.fn()} onReset={onReset} />)
    await user.click(screen.getByText('重置'))
    expect(onReset).toHaveBeenCalled()
  })

  it('should trigger search on Enter key', async () => {
    const onSearch = vi.fn()
    render(<SearchBar fields={fields} onSearch={onSearch} />)
    const input = screen.getByLabelText('关键词')
    await user.type(input, '窗帘{enter}')
    expect(onSearch).toHaveBeenCalled()
  })

  it('should render select fields with options', () => {
    render(<SearchBar fields={fields} onSearch={vi.fn()} />)
    expect(screen.getByText('全部')).toBeInTheDocument()
    expect(screen.getByText('激活')).toBeInTheDocument()
    expect(screen.getByText('停用')).toBeInTheDocument()
  })

  it('should handle select change', async () => {
    const onSearch = vi.fn()
    render(<SearchBar fields={fields} onSearch={onSearch} />)
    const select = screen.getByLabelText('状态')
    await user.selectOptions(select, 'active')
    await user.click(screen.getByText('搜索'))
    expect(onSearch).toHaveBeenCalledWith(
      expect.objectContaining({ status: 'active' })
    )
  })
})
