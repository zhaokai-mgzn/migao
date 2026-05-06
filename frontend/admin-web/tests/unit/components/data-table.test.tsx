import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// Mock lucide-react
vi.mock('lucide-react', () => {
  const stub = (name: string) => (props: any) => <span data-testid={`icon-${name}`} {...props} />
  return {
    ChevronUp: stub('chevron-up'),
    ChevronDown: stub('chevron-down'),
  }
})

import Table from '@/components/ui/Table'
import type { TableColumn } from '@/components/ui/Table'

interface TestRecord {
  id: string
  name: string
  price: number
  status: string
}

const testColumns: TableColumn<TestRecord>[] = [
  { key: 'name', title: '名称', dataIndex: 'name' },
  { key: 'price', title: '价格', dataIndex: 'price', align: 'right' },
  { key: 'status', title: '状态', render: (record) => <span data-testid={`status-${record.id}`}>{record.status}</span> },
]

const testData: TestRecord[] = [
  { id: '1', name: '商品A', price: 199, status: 'on_sale' },
  { id: '2', name: '商品B', price: 299, status: 'off_sale' },
  { id: '3', name: '商品C', price: 99, status: 'draft' },
]

describe('Table Component', () => {
  const user = userEvent.setup()

  it('should render table headers', () => {
    render(<Table columns={testColumns} dataSource={testData} rowKey="id" />)
    expect(screen.getByText('名称')).toBeInTheDocument()
    expect(screen.getByText('价格')).toBeInTheDocument()
    expect(screen.getByText('状态')).toBeInTheDocument()
  })

  it('should render table data', () => {
    render(<Table columns={testColumns} dataSource={testData} rowKey="id" />)
    expect(screen.getByText('商品A')).toBeInTheDocument()
    expect(screen.getByText('商品B')).toBeInTheDocument()
    expect(screen.getByText('商品C')).toBeInTheDocument()
  })

  it('should render data using dataIndex', () => {
    render(<Table columns={testColumns} dataSource={testData} rowKey="id" />)
    expect(screen.getByText('199')).toBeInTheDocument()
    expect(screen.getByText('299')).toBeInTheDocument()
  })

  it('should render data using custom render function', () => {
    render(<Table columns={testColumns} dataSource={testData} rowKey="id" />)
    expect(screen.getByTestId('status-1')).toHaveTextContent('on_sale')
    expect(screen.getByTestId('status-2')).toHaveTextContent('off_sale')
  })

  it('should show loading state', () => {
    render(<Table columns={testColumns} dataSource={[]} rowKey="id" loading={true} />)
    expect(screen.getByText('加载中...')).toBeInTheDocument()
  })

  it('should show empty text when no data', () => {
    render(<Table columns={testColumns} dataSource={[]} rowKey="id" />)
    expect(screen.getByText('暂无数据')).toBeInTheDocument()
  })

  it('should show custom empty text', () => {
    render(<Table columns={testColumns} dataSource={[]} rowKey="id" emptyText="没有找到商品" />)
    expect(screen.getByText('没有找到商品')).toBeInTheDocument()
  })

  it('should handle row click', async () => {
    const onRowClick = vi.fn()
    render(<Table columns={testColumns} dataSource={testData} rowKey="id" onRowClick={onRowClick} />)
    await user.click(screen.getByText('商品A'))
    expect(onRowClick).toHaveBeenCalledWith(testData[0])
  })

  it('should support function rowKey', () => {
    render(
      <Table
        columns={testColumns}
        dataSource={testData}
        rowKey={(record) => `key-${record.id}`}
      />
    )
    expect(screen.getByText('商品A')).toBeInTheDocument()
  })

  it('should render sortable column headers', () => {
    const sortableColumns: TableColumn<TestRecord>[] = [
      { key: 'name', title: '名称', dataIndex: 'name', sortable: true },
      { key: 'price', title: '价格', dataIndex: 'price' },
    ]
    render(<Table columns={sortableColumns} dataSource={testData} rowKey="id" />)
    // Sort icons should be present for sortable columns
    expect(screen.getByTestId('icon-chevron-up')).toBeInTheDocument()
    expect(screen.getByTestId('icon-chevron-down')).toBeInTheDocument()
  })

  it('should call onSort when sortable header is clicked', async () => {
    const onSort = vi.fn()
    const sortableColumns: TableColumn<TestRecord>[] = [
      { key: 'name', title: '名称', dataIndex: 'name', sortable: true },
    ]
    render(<Table columns={sortableColumns} dataSource={testData} rowKey="id" onSort={onSort} />)
    await user.click(screen.getByText('名称'))
    expect(onSort).toHaveBeenCalledWith('name')
  })

  it('should handle empty dataSource gracefully', () => {
    render(<Table columns={testColumns} dataSource={[]} rowKey="id" />)
    expect(screen.getByText('暂无数据')).toBeInTheDocument()
  })

  it('should apply correct alignment classes', () => {
    const alignColumns: TableColumn<TestRecord>[] = [
      { key: 'name', title: '名称', dataIndex: 'name', align: 'left' },
      { key: 'price', title: '价格', dataIndex: 'price', align: 'right' },
      { key: 'status', title: '状态', dataIndex: 'status', align: 'center' },
    ]
    render(<Table columns={alignColumns} dataSource={testData} rowKey="id" />)
    // Verify center-aligned header: the th element should contain text-center
    const statusHeader = screen.getByText('状态').closest('th')
    expect(statusHeader?.className).toContain('text-center')
  })
})
