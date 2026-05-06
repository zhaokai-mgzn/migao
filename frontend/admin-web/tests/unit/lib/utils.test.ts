import { describe, it, expect } from 'vitest'
import { cn } from '@/lib/utils'

describe('cn (classnames utility)', () => {
  it('should merge single class string', () => {
    expect(cn('text-red-500')).toBe('text-red-500')
  })

  it('should merge multiple class strings', () => {
    expect(cn('text-red-500', 'bg-blue-500')).toBe('text-red-500 bg-blue-500')
  })

  it('should handle conditional classes', () => {
    expect(cn('base', false && 'hidden', 'visible')).toBe('base visible')
  })

  it('should handle undefined and null values', () => {
    expect(cn('base', undefined, null, 'end')).toBe('base end')
  })

  it('should handle empty string', () => {
    expect(cn('')).toBe('')
  })

  it('should handle no arguments', () => {
    expect(cn()).toBe('')
  })

  it('should merge conflicting Tailwind classes (last wins)', () => {
    expect(cn('text-red-500', 'text-blue-500')).toBe('text-blue-500')
  })

  it('should merge conflicting padding classes', () => {
    expect(cn('p-4', 'p-2')).toBe('p-2')
  })

  it('should handle object syntax from clsx', () => {
    expect(cn({ 'text-red-500': true, 'bg-blue-500': false })).toBe('text-red-500')
  })

  it('should handle array syntax', () => {
    expect(cn(['text-red-500', 'bg-blue-500'])).toBe('text-red-500 bg-blue-500')
  })

  it('should handle mixed types', () => {
    const result = cn('base', { active: true, disabled: false }, ['extra'])
    expect(result).toBe('base active extra')
  })
})
