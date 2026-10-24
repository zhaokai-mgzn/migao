'use client'

// ============================================================
// SKU 选择器（公共件，issue #7567）
// ============================================================
// 用户 2026-10-23 逐字：「这种选择SKU的组件应该作为sku的公共组件，你新增的采购单和作业单中的
// sku 输入框是不能作为生产系统使用的，需要优化」（复核确认第二处是**价格本**）。
//
// 为什么必须是公共件：SKU id 是**雪花号字符串**（实测 ≈2.1e18，远超 JS 安全整数 9.007e15）——
// 让商家手打它既不可能也不该发生（#5904 实证：`Number()` 一转换就吞末位 ⇒ 服务端查不到该 SKU）。
// 想要一个 SKU，只能**从真实数据里选**。三处消费（入库单 / 采购单 / 价格本）共用这一份，
// 避免「同一件事三套实现各自漂移」（改一处形态要改三遍 = 迟早只剩一处是新的）。
//
// 交互**照搬**入库单 `/inbound-orders/new` 已验证的两栏形态（左搜商品 → 右勾 SKU；两栏各自滚动）：
//   ① 左栏搜索防抖 300ms，读 `GET /api/admin/products`；
//   ② 点商品 → 读该商品规格 `GET /api/admin/products/{id}`（SKU 在详情里）；
//   ③ 右栏逐行勾选，勾选态由**调用方**给的 `selectedSkuIds` 决定（受控，组件不存一份影子状态）。
//
// 🔴 两条「失败 ≠ 空态」的纪律（issue #6691，入库单那一版就是这么修的）：
//   搜索失败 ⇒ 说「没读到数据」+ 重试按钮，**不许**显示「输入关键词搜索商品」；
//   规格读取失败 ⇒ 说「没读到这个商品的规格」+ 重试按钮，**不许**显示「该商品还没有 SKU」
//   —— 后者是**数据事实**，拿读故障冒充它会让商家去商品详情白找一遍。
//
// 判据：tests/unit/components/SkuPicker.test.tsx（会红）
// 类级守卫：tests/unit/sku-id-input-guard.test.ts（任何页面再手拼 SKU 文本输入 ⇒ 红）

import { useCallback, useEffect, useId, useState } from 'react'
import { Layers, Search } from 'lucide-react'
import { productApi } from '@/lib/api'
import { formatStockQuantity } from '@/lib/stock-quantity'
import { cn } from '@/lib/utils'
import type { Product, ProductSku } from '@/types'

/** 勾选结果：**商品 + SKU 一起给**，调用方拿得到展示名（货号 / 颜色 / 门幅），不必回查。 */
export interface SkuPickerChoice {
  product: Product
  sku: ProductSku
}

interface SkuPickerProps {
  /** 已选 SKU id（受控）。入库单 / 采购单传数组，价格本传 `[当前 skuId]`。 */
  selectedSkuIds: readonly string[]
  /** 勾选 / 取消勾选都走它 —— 组件不判断「加还是删」，由页面按自己的明细语义决定。 */
  onToggle: (choice: SkuPickerChoice) => void
  /**
   * `multiple` = 勾选（复选框，入库单 / 采购单）；
   * `single` = 单选（单选框，价格本：一个 SKU 一页维护三层价）。
   */
  mode?: 'multiple' | 'single'
  /** 右栏标题：说清「勾了会发生什么」由各页自己写（同一件组件在不同页后果不同）。 */
  title?: string
  /** testid 前缀：`<prefix>-product-search-error` / `<prefix>-sku-error` 等（各页保留自己的既有 testid）。 */
  testIdPrefix?: string
  className?: string
}

/** 派生：一行 SKU 的展示名（颜色 / 门幅）—— 缺值给「默认」而不是空白（空行读起来像坏了）。 */
export function skuDisplayName(sku: Pick<ProductSku, 'colorName' | 'doorWidth'>): string {
  return `${sku.colorName || '默认色'} / ${sku.doorWidth || '默认门幅'}`
}

/** 派生：一行完整展示名（商品 / 颜色 / 门幅）—— 明细表与收货面共用同一份口径。 */
export function skuLineLabel(
  product: Pick<Product, 'name'>,
  sku: Pick<ProductSku, 'colorName' | 'doorWidth'>,
): string {
  return `${product.name} / ${skuDisplayName(sku)}`
}

export default function SkuPicker({
  selectedSkuIds,
  onToggle,
  mode = 'multiple',
  title = '勾选 SKU（勾选即加入明细）',
  testIdPrefix = 'sku-picker',
  className,
}: SkuPickerProps) {
  const [keyword, setKeyword] = useState('')
  const [options, setOptions] = useState<Product[]>([])
  /** 商品搜索读失败：与「输入关键词搜索商品」空态**互斥**（issue #6691） */
  const [searchFailed, setSearchFailed] = useState(false)
  const [picked, setPicked] = useState<Product | null>(null)
  const [skus, setSkus] = useState<ProductSku[]>([])
  const [skuLoading, setSkuLoading] = useState(false)
  /** 规格明细读失败：与「该商品还没有 SKU」空态**互斥**（issue #6691） */
  const [skuLoadFailed, setSkuLoadFailed] = useState(false)
  const groupName = useId()

  const search = useCallback(async () => {
    try {
      const res = await productApi.getProducts({
        keyword: keyword || undefined,
        page: 1,
        size: 20,
      })
      setOptions(res.data.data?.items ?? [])
      setSearchFailed(false)
    } catch {
      // 拦截器已 toast；此处只标失败态（列表保持不清零 —— 故障不冒充「搜不到」）
      setSearchFailed(true)
    }
  }, [keyword])

  useEffect(() => {
    const timer = setTimeout(() => void search(), 300)
    return () => clearTimeout(timer)
  }, [search])

  const loadSkus = useCallback(async (product: Product) => {
    setSkuLoading(true)
    try {
      const res = await productApi.getProduct(product.id)
      setSkus(res.data.data?.skus ?? [])
      setSkuLoadFailed(false)
    } catch {
      // 拦截器已 toast；只标失败态（不冒充「没有规格」）
      setSkuLoadFailed(true)
    } finally {
      setSkuLoading(false)
    }
  }, [])

  const pickProduct = async (product: Product) => {
    setPicked(product)
    await loadSkus(product)
  }

  return (
    <div className={cn('grid grid-cols-1 lg:grid-cols-2 gap-4', className)}>
      {/* 左：搜商品 */}
      <div className="rounded-lg border border-neutral-200 overflow-hidden">
        <div className="flex items-center gap-2 px-3 h-10 border-b border-neutral-100 bg-neutral-50/60">
          <Search className="w-4 h-4 text-neutral-400 shrink-0" />
          <input
            aria-label="搜索商品"
            placeholder="商品名称 / 货号"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            className="flex-1 min-w-0 bg-transparent text-sm focus:outline-none placeholder:text-neutral-400"
          />
        </div>
        <div className="max-h-72 min-h-[7rem] overflow-auto">
          {options.map((product) => (
            <button
              key={product.id}
              type="button"
              onClick={() => void pickProduct(product)}
              className={cn(
                'w-full text-left px-3 py-2 text-sm border-b border-neutral-100 last:border-0 hover:bg-neutral-50',
                picked?.id === product.id && 'bg-primary-50',
              )}
            >
              {product.name}
              {product.skuCode ? (
                <span className="text-neutral-400 ml-2">({product.skuCode})</span>
              ) : null}
            </button>
          ))}
          {searchFailed ? (
            <div
              data-testid={`${testIdPrefix}-product-search-error`}
              role="alert"
              className="px-3 py-6 text-sm text-center text-neutral-600"
            >
              商品搜索失败 —— 没读到数据，请检查网络后重试
              <button
                type="button"
                data-testid={`${testIdPrefix}-product-search-retry`}
                onClick={() => void search()}
                className="ml-2 text-primary-600 underline"
              >
                重试
              </button>
            </div>
          ) : (
            options.length === 0 && (
              <div className="px-3 py-6 text-sm text-neutral-400 text-center">
                输入关键词搜索商品
              </div>
            )
          )}
        </div>
      </div>

      {/* 右：勾 SKU */}
      <div className="rounded-lg border border-neutral-200 overflow-hidden">
        <div className="flex items-center gap-2 px-3 h-10 border-b border-neutral-100 bg-neutral-50/60">
          <Layers className="w-4 h-4 text-neutral-400 shrink-0" />
          <span className="text-sm text-neutral-600">{title}</span>
        </div>
        <div className="max-h-72 min-h-[7rem] overflow-auto">
          {!picked && (
            <div className="px-3 py-6 text-sm text-neutral-400 text-center">
              先在左侧选一个商品
            </div>
          )}
          {picked &&
            skus.map((sku) => {
              const checked = selectedSkuIds.includes(sku.id)
              return (
                <label
                  key={sku.id}
                  className="flex items-center gap-3 px-3 py-2 text-sm border-b border-neutral-100 last:border-0 hover:bg-neutral-50 cursor-pointer"
                >
                  <input
                    type={mode === 'single' ? 'radio' : 'checkbox'}
                    name={groupName}
                    checked={checked}
                    onChange={() => onToggle({ product: picked, sku })}
                  />
                  <span className="flex-1 min-w-0">{skuDisplayName(sku)}</span>
                  <span className="text-neutral-500 shrink-0">
                    当前库存 {formatStockQuantity(sku.stock ?? 0)}
                  </span>
                </label>
              )
            })}
          {picked && !skuLoading && skuLoadFailed && (
            <div
              data-testid={`${testIdPrefix}-sku-error`}
              role="alert"
              className="px-3 py-6 text-sm text-center text-neutral-600"
            >
              规格读取失败 —— 没读到这个商品的规格，请检查网络后重试
              <button
                type="button"
                data-testid={`${testIdPrefix}-sku-retry`}
                onClick={() => picked && void loadSkus(picked)}
                className="ml-2 text-primary-600 underline"
              >
                重试
              </button>
            </div>
          )}
          {picked && !skuLoading && !skuLoadFailed && skus.length === 0 && (
            <div className="px-3 py-6 text-sm text-neutral-400 text-center">
              该商品还没有 SKU，请先在商品详情维护 SKU
            </div>
          )}
          {picked && skuLoading && (
            <div className="px-3 py-6 text-sm text-neutral-400 text-center">加载中…</div>
          )}
        </div>
      </div>
    </div>
  )
}
