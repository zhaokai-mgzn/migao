// @vitest-environment jsdom
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import Input from '@/components/ui/Input'

describe('Input Component', () => {
  it('renders input element', () => {
    render(<Input placeholder="Enter name" />)
    expect(screen.getByPlaceholderText('Enter name')).toBeInTheDocument()
  })

  it('renders with value', () => {
    render(<Input value="Hello" readOnly />)
    expect(screen.getByDisplayValue('Hello')).toBeInTheDocument()
  })

  it('calls onChange when typing', () => {
    const onChange = vi.fn()
    render(<Input placeholder="Type here" onChange={onChange} />)
    fireEvent.change(screen.getByPlaceholderText('Type here'), { target: { value: 'new value' } })
    expect(onChange).toHaveBeenCalledTimes(1)
  })

  it('renders label', () => {
    render(<Input label="Name" />)
    expect(screen.getByText('Name')).toBeInTheDocument()
  })

  it('shows required asterisk when required', () => {
    render(<Input label="Name" required />)
    expect(screen.getByText('*')).toBeInTheDocument()
  })

  it('renders error message', () => {
    render(<Input label="Email" error="Invalid email" />)
    expect(screen.getByText('Invalid email')).toBeInTheDocument()
  })

  it('applies error border styles when error exists', () => {
    render(<Input error="Required" />)
    const input = screen.getByRole('textbox')
    expect(input.className).toContain('border-red-500')
  })

  it('renders disabled state', () => {
    render(<Input disabled />)
    expect(screen.getByRole('textbox')).toBeDisabled()
  })

  it('renders placeholder text', () => {
    render(<Input placeholder="Search..." />)
    expect(screen.getByPlaceholderText('Search...')).toBeInTheDocument()
  })

  it('merges className', () => {
    render(<Input className="extra-class" />)
    const input = screen.getByRole('textbox')
    expect(input.className).toContain('extra-class')
  })

  it('passes through HTML input attributes', () => {
    render(<Input type="email" maxLength={50} data-testid="email-input" />)
    const input = screen.getByTestId('email-input')
    expect(input).toHaveAttribute('type', 'email')
    expect(input).toHaveAttribute('maxLength', '50')
  })
})
