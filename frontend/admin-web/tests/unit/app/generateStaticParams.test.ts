import { describe, it, expect, vi } from 'vitest'

// Mock component imports that the page modules reference.
// These mocks must be declared before any dynamic import of the page modules.
vi.mock('@/app/(dashboard)/orders/[id]/ship/ShipOrder', () => ({
  default: () => null,
}))
vi.mock('@/app/(dashboard)/orders/[id]/OrderDetail', () => ({
  default: () => null,
}))
vi.mock('@/app/(dashboard)/products/[id]/ProductDetail', () => ({
  default: () => null,
}))
vi.mock('@/app/(dashboard)/products/[id]/edit/EditProduct', () => ({
  default: () => null,
}))
vi.mock('@/app/(dashboard)/customers/[id]/CustomerDetail', () => ({
  default: () => null,
}))
vi.mock('@/app/(dashboard)/after-sales/[id]/AfterSalesDetail', () => ({
  default: () => null,
}))

const ROUTES = [
  {
    name: 'orders/[id]/ship',
    path: '@/app/(dashboard)/orders/[id]/ship/page',
  },
  {
    name: 'orders/[id]',
    path: '@/app/(dashboard)/orders/[id]/page',
  },
  {
    name: 'products/[id]',
    path: '@/app/(dashboard)/products/[id]/page',
  },
  {
    name: 'products/[id]/edit',
    path: '@/app/(dashboard)/products/[id]/edit/page',
  },
  {
    name: 'customers/[id]',
    path: '@/app/(dashboard)/customers/[id]/page',
  },
  {
    name: 'after-sales/[id]',
    path: '@/app/(dashboard)/after-sales/[id]/page',
  },
] as const

describe('generateStaticParams', () => {
  it.each(ROUTES)(
    '$name: generateStaticParams() returns [{id: "_"}] (not empty array)',
    async ({ path }) => {
      const mod = await import(path)
      const result = await mod.generateStaticParams()
      // return [] 会让 Next.js output:export 报 "missing generateStaticParams()"
      expect(result).toEqual([{ id: '_' }])
    }
  )

  it.each(ROUTES)(
    '$name: generateStaticParams() does NOT return empty array',
    async ({ path }) => {
      const mod = await import(path)
      const result = await mod.generateStaticParams()
      // 空数组在 output:export 下会导致编译失败
      expect(result).not.toEqual([])
    }
  )

  it.each(ROUTES)('$name: dynamicParams is true', async ({ path }) => {
    const mod = await import(path)
    expect(mod.dynamicParams).toBe(true)
  })
})
