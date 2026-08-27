// @vitest-environment jsdom
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import Button from '@/components/ui/Button'

describe('Button Component', () => {
  it('renders children', () => {
    render(<Button>Submit</Button>)
    expect(screen.getByText('Submit')).toBeInTheDocument()
  })

  it('applies primary variant styles by default', () => {
    render(<Button>Primary</Button>)
    const btn = screen.getByText('Primary')
    expect(btn.className).toContain('bg-primary-600')
    expect(btn.className).toContain('text-white')
  })

  it('applies secondary variant styles', () => {
    render(<Button variant="secondary">Secondary</Button>)
    const btn = screen.getByText('Secondary')
    expect(btn.className).toContain('bg-white')
    expect(btn.className).toContain('border-gray-300')
  })

  it('applies danger variant styles', () => {
    render(<Button variant="danger">Danger</Button>)
    const btn = screen.getByText('Danger')
    expect(btn.className).toContain('text-red-600')
  })

  it('applies ghost variant styles', () => {
    render(<Button variant="ghost">Ghost</Button>)
    const btn = screen.getByText('Ghost')
    expect(btn.className).toContain('bg-transparent')
  })

  it('applies sm size styles', () => {
    render(<Button size="sm">Small</Button>)
    const btn = screen.getByText('Small')
    expect(btn.className).toContain('h-8')
  })

  it('applies md size styles by default', () => {
    render(<Button>Medium</Button>)
    const btn = screen.getByText('Medium')
    expect(btn.className).toContain('h-9')
  })

  it('applies lg size styles', () => {
    render(<Button size="lg">Large</Button>)
    const btn = screen.getByText('Large')
    expect(btn.className).toContain('h-10')
  })

  it('shows Loader2 spinner when loading', () => {
    render(<Button loading>Loading Button</Button>)
    // Loader2 is mocked as span[data-testid="icon-loader2"]
    expect(screen.getByTestId('icon-loader2')).toBeInTheDocument()
  })

  it('becomes disabled when loading', () => {
    render(<Button loading>Loading</Button>)
    expect(screen.getByText('Loading')).toBeDisabled()
  })

  it('becomes disabled when disabled prop is true', () => {
    render(<Button disabled>Disabled</Button>)
    expect(screen.getByText('Disabled')).toBeDisabled()
  })

  it('calls onClick handler when clicked', () => {
    const onClick = vi.fn()
    render(<Button onClick={onClick}>Click Me</Button>)
    fireEvent.click(screen.getByText('Click Me'))
    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it('does not call onClick when disabled', () => {
    const onClick = vi.fn()
    render(<Button disabled onClick={onClick}>Click Me</Button>)
    fireEvent.click(screen.getByText('Click Me'))
    expect(onClick).not.toHaveBeenCalled()
  })

  it('does not call onClick when loading', () => {
    const onClick = vi.fn()
    render(<Button loading onClick={onClick}>Click Me</Button>)
    fireEvent.click(screen.getByText('Click Me'))
    expect(onClick).not.toHaveBeenCalled()
  })

  it('merges className', () => {
    render(<Button className="extra-class">Merged</Button>)
    const btn = screen.getByText('Merged')
    expect(btn.className).toContain('extra-class')
  })

  it('passes through HTML button attributes', () => {
    render(<Button type="submit" data-testid="my-btn">Submit</Button>)
    const btn = screen.getByTestId('my-btn')
    expect(btn).toHaveAttribute('type', 'submit')
  })
})
