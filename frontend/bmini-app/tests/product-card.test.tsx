// case_ids: PR-001, PR-003, OR-010, CH-030
/**
 * 商品卡片交互测试 — 瑞幸式商品卡（参考 C 端 agent 设计）
 *
 * 覆盖：商品名/价格/销量渲染、规格行（specifications/规格数组）、
 * 「预计到手」价（original_price 划线）与到手价展示、
 * 「查看」CTA 触发 onView（把商品名带进对话，让黄金策介绍商品；商家端不下单，issue #7264）。
 */
import React from 'react'
import fs from 'fs'
import path from 'path'
import '@testing-library/jest-dom'
import { render, screen, fireEvent } from '@testing-library/react'
import ProductCard from '../src/components/cards/ProductCard'

describe('ProductCard — 瑞幸式商品卡交互', () => {
  const baseProduct = {
    id: 'p-001',
    name: '遮光窗帘',
    price: 199,
  }

  afterEach(() => {
    jest.clearAllMocks()
  })

  it('渲染商品名、价格、销量', () => {
    render(
      <ProductCard data={{ ...baseProduct, price: 199, sales_count: 28 }} />
    )
    expect(screen.getByText('遮光窗帘')).toBeInTheDocument()
    expect(screen.getByText('199.00')).toBeInTheDocument()
    expect(screen.getByText(/已售 28 件/)).toBeInTheDocument()
  })

  it('渲染规格行（specifications 对象）', () => {
    render(
      <ProductCard
        data={{
          ...baseProduct,
          specifications: { colorName: '深灰', doorWidth: '2.8米', sellMethod: '整幅' },
        }}
      />
    )
    const spec = screen.getByText(/深灰/)
    expect(spec).toBeInTheDocument()
    expect(screen.getByText(/2.8米/)).toBeInTheDocument()
  })

  it('渲染「预计到手」价与划线原价', () => {
    render(<ProductCard data={{ ...baseProduct, price: 139, original_price: 199 }} />)
    // 到手价（当前价）与划线原价都可见
    expect(screen.getByText('预计到手')).toBeInTheDocument()
    expect(screen.getByText('139.00')).toBeInTheDocument()
    expect(screen.getByText('¥199.00')).toBeInTheDocument()
  })

  it('点击「查看」CTA 触发 onView（携带商品名）', () => {
    const onView = jest.fn()
    render(<ProductCard data={baseProduct} onView={onView} />)
    fireEvent.click(screen.getByText('查看'))
    expect(onView).toHaveBeenCalledTimes(1)
    expect(onView).toHaveBeenCalledWith('遮光窗帘')
  })

  it('无 original_price 时不显示划线原价', () => {
    render(<ProductCard data={baseProduct} />)
    expect(screen.queryByText('预计到手')).not.toBeInTheDocument()
  })
})

describe('ProductCard — 查看防连点锁（issue #3040 收尾）', () => {
  afterEach(() => {
    jest.clearAllMocks()
  })

  it('点「查看」后锁卡：第二次点击不再触发 onView（防重复发消息）', () => {
    const onView = jest.fn()
    render(<ProductCard data={{ id: 'p-001', name: '遮光窗帘', price: 199 }} onView={onView} />)
    fireEvent.click(screen.getByText('查看'))
    fireEvent.click(screen.getByText('查看'))
    expect(onView).toHaveBeenCalledTimes(1)
  })
})

describe('商品卡不摆「没做完」的入口（issue #6666 判据 3）', () => {
  const baseProduct = { id: 'p-001', name: '遮光窗帘', price: 199 }

  it('🔴 卡上不再有「查看详情」这条空入口（点它只弹一句「功能开发中」= 把没做完写在脸上）', () => {
    render(<ProductCard data={baseProduct} onView={jest.fn()} />)
    expect(screen.queryByText('查看详情')).toBeNull()
    // 卡片唯一动作 =「查看」（issue #7264：真发消息让黄金策介绍商品，不是空 Toast）
    expect(screen.getByText('查看')).toBeInTheDocument()
    // 商家端不下单：旧的「去下单」入口零残留
    expect(screen.queryByText('去下单')).toBeNull()
  })

  it('🔴 该文案在 bmini 源码里零出现（不留第二处占位入口）', () => {
    const hits: string[] = []
    const walk = (dir: string) => {
      for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
        const p = path.join(dir, e.name)
        if (e.isDirectory()) walk(p)
        else if (/\.(ts|tsx|js|jsx|scss)$/.test(p)) {
          if (fs.readFileSync(p, 'utf-8').includes('功能开发中')) hits.push(p)
        }
      }
    }
    walk(path.resolve(__dirname, '../src'))
    expect(hits).toEqual([])
  })
})
