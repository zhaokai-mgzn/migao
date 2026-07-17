// @vitest-environment jsdom
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import Table, { TableColumn } from '@/components/ui/Table'

interface TestRecord {
  id: number
  name: string
  status: string
}

const columns: TableColumn<TestRecord>[] = [
  { key: 'id', title: '编号', dataIndex: 'id', width: '80px' },
  { key: 'name', title: '商品名称', dataIndex: 'name' },
  { key: 'status', title: '状态', dataIndex: 'status', align: 'center' },
  {
    key: 'long',
    title: '这是一个非常长的列标题需要验证不换行和截断行为',
    dataIndex: 'name',
    sortable: true,
  },
]

const dataSource: TestRecord[] = [
  { id: 1, name: '商品A', status: '出售中' },
  { id: 2, name: '商品B', status: '已售罄' },
]

describe('Table Component', () => {
  it('renders column headers with title attributes', () => {
    render(<Table columns={columns} dataSource={dataSource} rowKey="id" />)
    columns.forEach((col) => {
      const headerCell = screen.getByText(col.title)
      expect(headerCell).toBeInTheDocument()
      expect(headerCell.getAttribute('title')).toBe(col.title)
    })
  })

  it('applies whitespace-nowrap to <th> elements for single-line headers', () => {
    render(<Table columns={columns} dataSource={dataSource} rowKey="id" />)
    const thElements = document.querySelectorAll('th')
    thElements.forEach((th) => {
      expect(th.className).toMatch(/\bwhitespace-nowrap\b/)
    })
  })

  it('renders column title in a whitespace-nowrap truncate span', () => {
    render(<Table columns={columns} dataSource={dataSource} rowKey="id" />)
    const titleSpan = screen.getByText('商品名称')
    expect(titleSpan.className).toMatch(/\bwhitespace-nowrap\b/)
    expect(titleSpan.className).toMatch(/\btruncate\b/)
  })

  it('renders sort chevron wrapper with flex-shrink-0', () => {
    render(
      <Table columns={columns} dataSource={dataSource} rowKey="id" sortField="name" sortOrder="asc" />
    )
    const chevronContainer = document.querySelector('.flex-shrink-0')
    expect(chevronContainer).toBeInTheDocument()
  })

  it('calls onSort when sortable column header is clicked', () => {
    const onSort = vi.fn()
    render(<Table columns={columns} dataSource={dataSource} rowKey="id" onSort={onSort} />)
    const sortableHeader = screen.getByText('这是一个非常长的列标题需要验证不换行和截断行为')
    fireEvent.click(sortableHeader)
    expect(onSort).toHaveBeenCalledWith('long')
  })

  it('renders all data rows', () => {
    render(<Table columns={columns} dataSource={dataSource} rowKey="id" />)
    expect(screen.getAllByText('商品A').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('商品B').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('出售中')).toBeInTheDocument()
    expect(screen.getByText('已售罄')).toBeInTheDocument()
  })

  it('shows loading state', () => {
    render(<Table columns={columns} dataSource={[]} rowKey="id" loading />)
    expect(screen.getByText('加载中...')).toBeInTheDocument()
  })

  it('shows empty state when data is empty and not loading', () => {
    render(<Table columns={columns} dataSource={[]} rowKey="id" />)
    expect(screen.getByText('暂无数据')).toBeInTheDocument()
  })

  it('shows custom empty text', () => {
    render(<Table columns={columns} dataSource={[]} rowKey="id" emptyText="没有找到商品" />)
    expect(screen.getByText('没有找到商品')).toBeInTheDocument()
  })

  it('calls onRowClick when row is clicked', () => {
    const onRowClick = vi.fn()
    const simpleColumns: TableColumn<TestRecord>[] = [
      { key: 'id', title: '编号', dataIndex: 'id' },
      { key: 'name', title: '名称', dataIndex: 'name' },
    ]
    render(<Table columns={simpleColumns} dataSource={dataSource} rowKey="id" onRowClick={onRowClick} />)
    fireEvent.click(screen.getByText('商品A'))
    expect(onRowClick).toHaveBeenCalledWith(dataSource[0])
  })

  it('applies minWidth style when provided', () => {
    render(<Table columns={columns} dataSource={dataSource} rowKey="id" minWidth={800} />)
    const table = document.querySelector('table')
    expect(table?.style.minWidth).toBe('800px')
  })
})
