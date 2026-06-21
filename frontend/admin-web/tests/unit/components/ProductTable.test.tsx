/**
 * ProductTable 组件测试
 * 覆盖：#646 移除 in_warehouse — 状态徽章映射无仓库中、操作按钮正确
 */
import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import ProductTable from '@/components/products/ProductTable'
import type { Product, ProductStatus } from '@/types'
import { ProductStatusLabels } from '@/types'

// Mock next/image
vi.mock('next/image', () => ({
  default: (props: any) => {
    const React = require('react')
    return React.createElement('img', { ...props, src: props.src || '' })
  },
}))

const baseProduct: Product = {
  id: 'p001',
  name: '北欧简约遮光窗帘',
  skuCode: 'CL-GY-001',
  images: [],
  colorCount: 3,
  stock: 500,
  salesCount: 120,
  salesAmount: 36000,
  status: 'on_sale',
  createdAt: '2026-06-15T10:00:00Z',
  price: 299,
  unit: '米',
  categoryId: 'c1',
}

const defaultProps = {
  products: [baseProduct],
  loading: false,
  total: 1,
  page: 1,
  pageSize: 20,
  selectedIds: [] as string[],
  onPageChange: vi.fn(),
  onPageSizeChange: vi.fn(),
  onSelectChange: vi.fn(),
  onSortChange: vi.fn(),
  onView: vi.fn(),
  onEdit: vi.fn(),
  onPutOnShelf: vi.fn(),
  onTakeOffShelf: vi.fn(),
  onDelete: vi.fn(),
}

describe('ProductTable (#646 — 移除 in_warehouse)', () => {
  it('应渲染商品名称', () => {
    render(<ProductTable {...defaultProps} />)
    expect(screen.getByText('北欧简约遮光窗帘')).toBeTruthy()
  })

  it('应渲染商品货号', () => {
    render(<ProductTable {...defaultProps} />)
    expect(screen.getByText('CL-GY-001')).toBeTruthy()
  })

  it('空列表显示"暂无数据"', () => {
    render(<ProductTable {...defaultProps} products={[]} total={0} />)
    expect(screen.getByText('暂无数据')).toBeTruthy()
  })

  it('加载中显示"加载中…"', () => {
    render(<ProductTable {...defaultProps} products={[]} loading={true} />)
    expect(screen.getByText('加载中...')).toBeTruthy()
  })

  describe('状态徽章映射 — 无 in_warehouse', () => {
    const statusLabels: [ProductStatus, string][] = [
      ['on_sale', '出售中'],
      ['off_sale', '已下架'],
      ['draft', '草稿'],
      ['under_review', '审核中'],
    ]

    for (const [status, label] of statusLabels) {
      it(`status="${status}" 显示「${label}」`, () => {
        const product = { ...baseProduct, status }
        render(<ProductTable {...defaultProps} products={[product]} />)
        expect(screen.getByText(label)).toBeTruthy()
      })
    }

    it('不显示「仓库中」', () => {
      // 四种状态都不应该渲染「仓库中」
      const products: Product[] = [
        { ...baseProduct, id: 'p1', status: 'on_sale' },
        { ...baseProduct, id: 'p2', status: 'off_sale' },
        { ...baseProduct, id: 'p3', status: 'draft' },
        { ...baseProduct, id: 'p4', status: 'under_review' },
      ]
      render(<ProductTable {...defaultProps} products={products} total={4} />)
      expect(screen.queryByText('仓库中')).toBeNull()
    })
  })

  describe('操作按钮 — 按状态', () => {
    it('on_sale 显示：查看 编辑 下架 删除', () => {
      render(<ProductTable {...defaultProps} />)
      expect(screen.getByText('查看')).toBeTruthy()
      expect(screen.getByText('编辑')).toBeTruthy()
      expect(screen.getByText('下架')).toBeTruthy()
      expect(screen.getByText('删除')).toBeTruthy()
    })

    it('off_sale 显示：查看 编辑 上架 删除', () => {
      const product = { ...baseProduct, status: 'off_sale' as const }
      render(<ProductTable {...defaultProps} products={[product]} />)
      expect(screen.getByText('查看')).toBeTruthy()
      expect(screen.getByText('编辑')).toBeTruthy()
      expect(screen.getByText('上架')).toBeTruthy()
      expect(screen.getByText('删除')).toBeTruthy()
      expect(screen.queryByText('下架')).toBeNull()
    })

    it('under_review 仅显示查看', () => {
      const product = { ...baseProduct, status: 'under_review' as const }
      render(<ProductTable {...defaultProps} products={[product]} />)
      expect(screen.getByText('查看')).toBeTruthy()
      // 审核中无编辑/上下架/删除按钮
      expect(screen.queryByText('编辑')).toBeNull()
      expect(screen.queryByText('上架')).toBeNull()
      expect(screen.queryByText('下架')).toBeNull()
      expect(screen.queryByText('删除')).toBeNull()
    })

    it('draft 显示：编辑 删除', () => {
      const product = { ...baseProduct, status: 'draft' as const }
      render(<ProductTable {...defaultProps} products={[product]} />)
      expect(screen.getByText('编辑')).toBeTruthy()
      expect(screen.getByText('删除')).toBeTruthy()
      expect(screen.queryByText('查看')).toBeNull()
      expect(screen.queryByText('上架')).toBeNull()
    })
  })

  describe('ProductStatusLabels — 无 in_warehouse', () => {
    it('只有 4 个状态标签', () => {
      const keys = Object.keys(ProductStatusLabels)
      expect(keys).toHaveLength(4)
    })

    it('不包含 in_warehouse', () => {
      expect(ProductStatusLabels).not.toHaveProperty('in_warehouse')
      expect((ProductStatusLabels as any)['in_warehouse']).toBeUndefined()
    })

    it('四个标签值正确', () => {
      expect(ProductStatusLabels.on_sale).toBe('出售中')
      expect(ProductStatusLabels.off_sale).toBe('已下架')
      expect(ProductStatusLabels.draft).toBe('草稿')
      expect(ProductStatusLabels.under_review).toBe('审核中')
    })
  })
})
