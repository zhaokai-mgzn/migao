/**
 * ImageUploader 组件测试
 * 覆盖：#563 — 上传按钮渲染、图片展示、最大数量限制
 */
import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import ImageUploader from '@/components/products/ImageUploader'

// Mock next/image
vi.mock('next/image', () => ({
  default: (props: any) => {
    const React = require('react')
    return React.createElement('img', { ...props, src: props.src || '' })
  },
}))

// Mock @/lib/utils
vi.mock('@/lib/utils', () => ({
  cn: (...args: any[]) => args.filter(Boolean).join(' '),
  resolveImageUrl: (url: string) => url,
}))

// Mock @/lib/api
vi.mock('@/lib/api', () => ({
  fileApi: {
    uploadFile: vi.fn(),
  },
}))

describe('ImageUploader (#563)', () => {
  it('渲染上传区域（无图片时）', () => {
    render(<ImageUploader value={[]} onChange={vi.fn()} />)
    expect(screen.getByText('上传图片')).toBeTruthy()
  })

  it('显示 hint 提示文字', () => {
    render(
      <ImageUploader
        value={[]}
        onChange={vi.fn()}
        hint="最多 5 张，可拖拽排序"
      />
    )
    expect(screen.getByText('最多 5 张，可拖拽排序')).toBeTruthy()
  })

  it('显示 label 标签', () => {
    render(
      <ImageUploader
        value={[]}
        onChange={vi.fn()}
        label="商品主图"
      />
    )
    expect(screen.getByText('商品主图')).toBeTruthy()
  })

  it('有图片时渲染图片和删除按钮', () => {
    render(
      <ImageUploader
        value={['https://example.com/img1.jpg']}
        onChange={vi.fn()}
      />
    )
    // 图片应渲染
    const img = document.querySelector('img')
    expect(img).toBeTruthy()
    // 删除按钮存在（X 图标 mock 为 icon-x）
    const deleteBtn = img?.parentElement?.querySelector('button')
    expect(deleteBtn).toBeTruthy()
  })

  it('达到 max 限制时不显示上传按钮', () => {
    render(
      <ImageUploader
        value={['https://example.com/img1.jpg']}
        onChange={vi.fn()}
        max={1}
      />
    )
    // 达到上限时不存在"上传图片"文字
    expect(screen.queryByText('上传图片')).toBeNull()
  })

  it('单图模式显示主图标识', () => {
    render(
      <ImageUploader
        value={['https://example.com/img1.jpg']}
        onChange={vi.fn()}
        multiple={false}
      />
    )
    expect(screen.getByText('主图')).toBeTruthy()
  })

  it('showOrderBadge 模式显示封面标识', () => {
    render(
      <ImageUploader
        value={['https://example.com/img1.jpg']}
        onChange={vi.fn()}
        multiple
        showOrderBadge
      />
    )
    expect(screen.getByText('1·封面')).toBeTruthy()
  })

  it('showOrderBadge 空值时显示上传封面', () => {
    render(
      <ImageUploader
        value={[]}
        onChange={vi.fn()}
        multiple
        showOrderBadge
        max={5}
      />
    )
    expect(screen.getByText('上传封面')).toBeTruthy()
  })

  it('多图 showOrderBadge 模式显示序号', () => {
    render(
      <ImageUploader
        value={[
          'https://example.com/cover.jpg',
          'https://example.com/img2.jpg',
        ]}
        onChange={vi.fn()}
        multiple
        showOrderBadge
        max={5}
      />
    )
    expect(screen.getByText('1·封面')).toBeTruthy()
    expect(screen.getByText('2')).toBeTruthy()
  })
})
