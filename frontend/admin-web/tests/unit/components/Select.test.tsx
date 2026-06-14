// @vitest-environment jsdom
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import Select from '@/components/ui/Select'

const defaultOptions = [
  { value: '1', label: 'Option 1' },
  { value: '2', label: 'Option 2' },
  { value: '3', label: 'Option 3' },
]

describe('Select Component', () => {
  it('renders all options', () => {
    render(<Select options={defaultOptions} />)
    expect(screen.getByText('Option 1')).toBeInTheDocument()
    expect(screen.getByText('Option 2')).toBeInTheDocument()
    expect(screen.getByText('Option 3')).toBeInTheDocument()
  })

  it('renders label', () => {
    render(<Select label="Category" options={defaultOptions} />)
    expect(screen.getByText('Category')).toBeInTheDocument()
  })

  it('renders placeholder option', () => {
    render(<Select placeholder="Please select" options={defaultOptions} />)
    expect(screen.getByText('Please select')).toBeInTheDocument()
  })

  it('shows required asterisk when required', () => {
    render(<Select label="Category" options={defaultOptions} required />)
    expect(screen.getByText('*')).toBeInTheDocument()
  })

  it('does not show asterisk when not required', () => {
    render(<Select label="Category" options={defaultOptions} />)
    expect(screen.queryByText('*')).not.toBeInTheDocument()
  })

  it('calls onChange when option selected', () => {
    const onChange = vi.fn()
    render(<Select options={defaultOptions} onChange={onChange} />)
    const select = screen.getByRole('combobox')
    fireEvent.change(select, { target: { value: '2' } })
    expect(onChange).toHaveBeenCalledTimes(1)
  })

  it('renders error message', () => {
    render(<Select options={defaultOptions} error="This field is required" />)
    expect(screen.getByText('This field is required')).toBeInTheDocument()
  })

  it('applies error border styles when error exists', () => {
    render(<Select options={defaultOptions} error="Error" />)
    const select = screen.getByRole('combobox')
    expect(select.className).toContain('border-red-500')
  })

  it('renders disabled state', () => {
    render(<Select options={defaultOptions} disabled />)
    expect(screen.getByRole('combobox')).toBeDisabled()
  })

  it('renders ChevronDown icon', () => {
    render(<Select options={defaultOptions} />)
    // ChevronDown is mocked in setup.ts
    expect(screen.getByTestId('icon-chevron-down')).toBeInTheDocument()
  })
})
