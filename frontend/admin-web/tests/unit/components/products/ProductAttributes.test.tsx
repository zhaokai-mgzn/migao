/**
 * ProductAttributes 组件测试
 * 覆盖：#563 — 货号/品牌/计价单位 + 规格属性字段渲染
 */
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import ProductAttributes from '@/components/products/ProductAttributes'

// Mock @/lib/utils (cn)
vi.mock('@/lib/utils', () => ({
  cn: (...args: any[]) => args.filter(Boolean).join(' '),
  resolveImageUrl: (url: string) => url,
}))

const defaultProps = {
  value: {
    skuCode: '',
    brand: '',
    unit: '',
    specifications: {} as Record<string, string>,
  },
  onChange: vi.fn(),
}

describe('ProductAttributes (#563)', () => {
  it('渲染货号输入框', () => {
    render(<ProductAttributes {...defaultProps} />)
    expect(screen.getByText('货号')).toBeTruthy()
    expect(screen.getByPlaceholderText('请输入商品货号')).toBeTruthy()
  })

  it('渲染品牌选择器', () => {
    render(<ProductAttributes {...defaultProps} />)
    expect(screen.getByText('品牌')).toBeTruthy()
  })

  it('渲染计价单位选择器', () => {
    render(<ProductAttributes {...defaultProps} />)
    expect(screen.getByText('计价单位')).toBeTruthy()
  })

  it('渲染克重选择器', () => {
    render(<ProductAttributes {...defaultProps} />)
    expect(screen.getByText('克重')).toBeTruthy()
  })

  it('渲染材质选择器', () => {
    render(<ProductAttributes {...defaultProps} />)
    expect(screen.getByText('材质')).toBeTruthy()
  })

  it('渲染功能选择器', () => {
    render(<ProductAttributes {...defaultProps} />)
    expect(screen.getByText('功能')).toBeTruthy()
  })

  it('渲染工艺选择器', () => {
    render(<ProductAttributes {...defaultProps} />)
    expect(screen.getByText('工艺')).toBeTruthy()
  })

  it('渲染风格选择器', () => {
    render(<ProductAttributes {...defaultProps} />)
    expect(screen.getByText('风格')).toBeTruthy()
  })

  it('渲染图案选择器', () => {
    render(<ProductAttributes {...defaultProps} />)
    expect(screen.getByText('图案')).toBeTruthy()
  })

  it('货号输入触发 onChange', () => {
    const onChange = vi.fn()
    render(<ProductAttributes {...defaultProps} onChange={onChange} />)
    const input = screen.getByPlaceholderText('请输入商品货号')
    fireEvent.change(input, { target: { value: 'CL-001' } })
    expect(onChange).toHaveBeenCalledWith({ skuCode: 'CL-001' })
  })

  it('显示货号错误信息', () => {
    render(
      <ProductAttributes
        {...defaultProps}
        errors={{ skuCode: '请输入货号' }}
      />
    )
    expect(screen.getByText('请输入货号')).toBeTruthy()
  })

  it('显示计价单位错误信息', () => {
    render(
      <ProductAttributes
        {...defaultProps}
        errors={{ unit: '请选择计价单位' }}
      />
    )
    expect(screen.getByText('请选择计价单位')).toBeTruthy()
  })

  it('有预填值时正确显示', () => {
    render(
      <ProductAttributes
        value={{
          skuCode: 'CL-RED-001',
          brand: '米高',
          unit: '米',
          specifications: {
            weight: '200-300g',
            material: '涤纶',
            function: '遮光',
            craft: '提花',
            style: '现代简约',
            pattern: '纯色',
          },
        }}
        onChange={vi.fn()}
      />
    )
    expect(screen.getByDisplayValue('CL-RED-001')).toBeTruthy()
  })
})
