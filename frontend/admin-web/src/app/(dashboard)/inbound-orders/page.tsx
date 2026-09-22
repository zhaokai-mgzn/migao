'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Plus, RotateCcw, Search, Send, Ban, PackageOpen, Layers } from 'lucide-react'
import { toast } from 'sonner'
import { inboundOrderApi, productApi } from '@/lib/api'
import { Modal, Button, Input, Select } from '@/components/ui'
import type {
  InboundOrder,
  InboundOrderLine,
  InboundOrderStatus,
  Product,
  ProductSku,
} from '@/types'
import { cn } from '@/lib/utils'
import { checkStockQuantity, formatStockQuantity } from '@/lib/stock-quantity'

// ============================================================
// 入库单（V111，issue #5034）—— 商品布料入库
// ============================================================
// 三件标准能力（对应后端 InboundOrderService）：
//   ① 建单（草稿，**不动库存**）—— 仓库按送货单录单；
//   ② 过账 —— 服务端**自动生成批次号** + **自动加库存** + 落库存台账 + 按移动加权平均算成本；
//   ③ 作废（仅草稿）—— 已过账的库存已进台账，冲销须另开单据。
// 批次粒度 = **一个 SKU 行 = 一个批次**（用户裁定 2026-09-23）。
// 数量口径（issue #5063）：库存米数**小数化**，0.1 米粒度 ⇒ 数量「≥1 且最多 1 位小数」，
//   与后端 admin-api 同一判据；超 1 位小数**显式拒绝**（不静默取整），见 lib/stock-quantity.ts。

const STATUS_OPTIONS: { value: InboundOrderStatus | ''; label: string }[] = [
  { value: '', label: '全部状态' },
  { value: 'draft', label: '草稿' },
  { value: 'posted', label: '已过账' },
  { value: 'cancelled', label: '已作废' },
]

const STATUS_LABEL: Record<InboundOrderStatus, string> = {
  draft: '草稿',
  posted: '已过账',
  cancelled: '已作废',
}

const STATUS_CLASS: Record<InboundOrderStatus, string> = {
  draft: 'bg-neutral-100 text-neutral-700 border-neutral-200',
  posted: 'bg-green-50 text-green-700 border-green-200',
  cancelled: 'bg-red-50 text-red-600 border-red-200',
}

/** 建单弹窗里的一行（含 SKU 的展示快照，提交时只取 productId/skuId/quantity/unitCost/dyeLot/rollLengthM） */
interface DraftLine {
  productId: string
  skuId: number
  label: string
  stock: number
  quantity: string
  unitCost: string
  dyeLot: string
  rollLengthM: string
}

export default function InboundOrdersPage() {
  const [keyword, setKeyword] = useState('')
  const [status, setStatus] = useState<InboundOrderStatus | ''>('')
  const [rows, setRows] = useState<InboundOrderLine[]>([])
  const [loading, setLoading] = useState(false)

  // 建单弹窗
  const [createOpen, setCreateOpen] = useState(false)
  const [productKeyword, setProductKeyword] = useState('')
  const [productOptions, setProductOptions] = useState<Product[]>([])
  const [pickedProduct, setPickedProduct] = useState<Product | null>(null)
  const [productSkus, setProductSkus] = useState<ProductSku[]>([])
  const [skuLoading, setSkuLoading] = useState(false)
  const [draftLines, setDraftLines] = useState<DraftLine[]>([])
  const [form, setForm] = useState({
    supplier: '',
    supplierDocNo: '',
    warehouse: '',
    inboundDate: '',
    remark: '',
  })
  const [submitting, setSubmitting] = useState(false)

  // 详情弹窗
  const [detailOpen, setDetailOpen] = useState(false)
  const [detail, setDetail] = useState<InboundOrder | null>(null)
  const [acting, setActing] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await inboundOrderApi.list({ keyword: keyword || undefined, status })
      setRows(res.data.data ?? [])
    } catch {
      // request 拦截器已 toast；此处只需不留下半截数据
      setRows([])
    } finally {
      setLoading(false)
    }
  }, [keyword, status])

  useEffect(() => {
    void load()
  }, [load])

  // ---- 建单：商品搜索（防抖） ----
  useEffect(() => {
    if (!createOpen) return
    const t = setTimeout(async () => {
      try {
        const res = await productApi.getProducts({
          keyword: productKeyword || undefined,
          page: 1,
          size: 20,
        })
        setProductOptions(res.data.data?.items ?? [])
      } catch {
        setProductOptions([])
      }
    }, 300)
    return () => clearTimeout(t)
  }, [productKeyword, createOpen])

  const pickProduct = async (p: Product) => {
    setPickedProduct(p)
    setSkuLoading(true)
    try {
      const res = await productApi.getProduct(p.id)
      setProductSkus(res.data.data?.skus ?? [])
    } catch {
      setProductSkus([])
    } finally {
      setSkuLoading(false)
    }
  }

  const resetCreate = () => {
    setProductKeyword('')
    setProductOptions([])
    setPickedProduct(null)
    setProductSkus([])
    setDraftLines([])
    setForm({ supplier: '', supplierDocNo: '', warehouse: '', inboundDate: '', remark: '' })
  }

  /** 勾选 SKU ⇒ 加入/移出草稿行（保留已填的数量/单价/缸号） */
  const toggleSku = (sku: ProductSku) => {
    if (!pickedProduct) return
    setDraftLines((prev) => {
      const exists = prev.some((l) => l.skuId === Number(sku.id))
      if (exists) {
        return prev.filter((l) => l.skuId !== Number(sku.id))
      }
      return [
        ...prev,
        {
          productId: pickedProduct.id,
          skuId: Number(sku.id),
          label: `${pickedProduct.name} / ${sku.colorName || '默认色'} / ${sku.doorWidth || '默认门幅'}`,
          stock: sku.stock ?? 0,
          quantity: '1',
          unitCost: '',
          dyeLot: '',
          rollLengthM: '',
        },
      ]
    })
  }

  const patchLine = (skuId: number, patch: Partial<DraftLine>) => {
    setDraftLines((prev) => prev.map((l) => (l.skuId === skuId ? { ...l, ...patch } : l)))
  }

  const draftTotal = useMemo(
    () =>
      draftLines.reduce((sum, l) => {
        const q = Number(l.quantity)
        const c = Number(l.unitCost)
        if (!Number.isFinite(q) || !Number.isFinite(c) || l.unitCost === '') return sum
        return sum + q * c
      }, 0),
    [draftLines],
  )

  const submitCreate = async () => {
    if (draftLines.length === 0) {
      toast.error('请至少勾选一个 SKU 作为入库明细')
      return
    }
    // 数量必须 ≥1 且**最多 1 位小数**（0.1 米粒度）—— 与后端同一判据。
    // 超 1 位小数**显式拒绝**，绝不静默取整/截断（账面库存要照米数对得上）。
    for (const l of draftLines) {
      const reason = checkStockQuantity(l.quantity)
      if (reason) {
        toast.error(`「${l.label}」的${reason}`)
        return
      }
      if (l.unitCost !== '' && !(Number(l.unitCost) > 0)) {
        toast.error(`「${l.label}」的入库单价必须大于 0（不记单价请留空）`)
        return
      }
    }
    setSubmitting(true)
    try {
      await inboundOrderApi.create({
        supplier: form.supplier || null,
        supplierDocNo: form.supplierDocNo || null,
        warehouse: form.warehouse || null,
        inboundDate: form.inboundDate || null,
        remark: form.remark || null,
        items: draftLines.map((l) => ({
          productId: l.productId,
          skuId: l.skuId,
          quantity: Number(l.quantity),
          unitCost: l.unitCost === '' ? null : Number(l.unitCost),
          dyeLot: l.dyeLot || null,
          rollLengthM: l.rollLengthM === '' ? null : Number(l.rollLengthM),
        })),
      })
      toast.success('入库单已建（草稿，未动库存）—— 核对无误后请过账')
      setCreateOpen(false)
      resetCreate()
      await load()
    } catch {
      // 拦截器已提示
    } finally {
      setSubmitting(false)
    }
  }

  const openDetail = async (id: string) => {
    try {
      const res = await inboundOrderApi.detail(id)
      setDetail(res.data.data ?? null)
      setDetailOpen(true)
    } catch {
      // 拦截器已提示
    }
  }

  const doPost = async () => {
    if (!detail) return
    setActing(true)
    try {
      const res = await inboundOrderApi.post(detail.id)
      setDetail(res.data.data ?? detail)
      toast.success('已过账：批次号已生成、库存已加、成本已按移动加权平均重算')
      await load()
    } catch {
      // 拦截器已提示
    } finally {
      setActing(false)
    }
  }

  const doCancel = async () => {
    if (!detail) return
    setActing(true)
    try {
      const res = await inboundOrderApi.cancel(detail.id, '页面作废')
      setDetail(res.data.data ?? detail)
      toast.success('入库单已作废')
      await load()
    } catch {
      // 拦截器已提示
    } finally {
      setActing(false)
    }
  }

  return (
    <div className="p-6 space-y-4">
      {/* 页头 */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-neutral-900 flex items-center gap-2">
            <PackageOpen className="w-5 h-5 text-primary-600" />
            入库单
          </h1>
          <p className="text-sm text-neutral-500 mt-1">
            商品布料入库：建单（草稿）→ 过账（自动生成批次号 + 自动加库存 + 移动加权平均成本）→ 批次可追溯
          </p>
        </div>
        <Button onClick={() => setCreateOpen(true)}>
          <Plus className="w-4 h-4 mr-1.5" />
          新建入库单
        </Button>
      </div>

      {/* 筛选 */}
      <div className="flex items-center gap-3 bg-white border border-neutral-200 rounded-lg p-3">
        <Input
          placeholder="入库单号 / 供应商 / 送货单号"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          className="max-w-xs"
        />
        <Select
          value={status}
          onChange={(e) => setStatus(e.target.value as InboundOrderStatus | '')}
          options={STATUS_OPTIONS}
          className="max-w-[160px]"
        />
        <Button variant="secondary" onClick={() => void load()}>
          <Search className="w-4 h-4 mr-1.5" />
          查询
        </Button>
        <Button
          variant="ghost"
          onClick={() => {
            setKeyword('')
            setStatus('')
          }}
        >
          <RotateCcw className="w-4 h-4 mr-1.5" />
          重置
        </Button>
      </div>

      {/* 列表 */}
      <div className="bg-white border border-neutral-200 rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-neutral-50 text-neutral-600">
            <tr>
              <th className="text-left px-4 py-2.5 font-medium">入库单号</th>
              <th className="text-left px-4 py-2.5 font-medium">入库日期</th>
              <th className="text-left px-4 py-2.5 font-medium">供应商</th>
              <th className="text-left px-4 py-2.5 font-medium">仓库</th>
              <th className="text-right px-4 py-2.5 font-medium">行数 / 总数量</th>
              <th className="text-right px-4 py-2.5 font-medium">金额</th>
              <th className="text-left px-4 py-2.5 font-medium">状态</th>
              <th className="text-right px-4 py-2.5 font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} className="border-t border-neutral-100 hover:bg-neutral-50">
                <td className="px-4 py-2.5 font-mono text-neutral-900">{row.inboundNo}</td>
                <td className="px-4 py-2.5 text-neutral-600">{row.inboundDate}</td>
                <td className="px-4 py-2.5 text-neutral-600">{row.supplier || '-'}</td>
                <td className="px-4 py-2.5 text-neutral-600">{row.warehouse || '-'}</td>
                <td className="px-4 py-2.5 text-right text-neutral-600">
                  {row.itemCount} / {formatStockQuantity(row.totalQuantity)}
                </td>
                <td className="px-4 py-2.5 text-right text-neutral-900">
                  {row.totalAmount != null ? `¥${Number(row.totalAmount).toFixed(2)}` : '-'}
                </td>
                <td className="px-4 py-2.5">
                  <span
                    className={cn(
                      'inline-flex items-center rounded-full border px-2 py-0.5 text-xs',
                      STATUS_CLASS[row.status],
                    )}
                  >
                    {STATUS_LABEL[row.status]}
                  </span>
                </td>
                <td className="px-4 py-2.5 text-right">
                  <Button variant="ghost" size="sm" onClick={() => void openDetail(row.id)}>
                    详情
                  </Button>
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={8} className="px-4 py-10 text-center text-neutral-400">
                  {loading ? '加载中…' : '暂无入库单'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* 建单弹窗 */}
      <Modal
        open={createOpen}
        onClose={() => {
          setCreateOpen(false)
          resetCreate()
        }}
        title="新建入库单"
        width={960}
        footer={
          <div className="flex items-center justify-between w-full">
            <span className="text-sm text-neutral-600">
              合计金额：<span className="font-medium text-neutral-900">¥{draftTotal.toFixed(2)}</span>
            </span>
            <div className="flex gap-2">
              <Button
                variant="secondary"
                onClick={() => {
                  setCreateOpen(false)
                  resetCreate()
                }}
              >
                取消
              </Button>
              <Button onClick={() => void submitCreate()} loading={submitting}>
                保存为草稿
              </Button>
            </div>
          </div>
        }
      >
        <div className="space-y-4">
          <p className="text-xs text-neutral-500 bg-neutral-50 border border-neutral-200 rounded p-2">
            保存为草稿<strong>不会改动库存</strong>；批次号在<strong>过账</strong>时由系统自动生成，
            库存与成本也在过账时一次性写入（可核对后再过账）。
          </p>

          <div className="grid grid-cols-2 gap-3">
            <Input
              label="供应商"
              value={form.supplier}
              onChange={(e) => setForm({ ...form, supplier: e.target.value })}
              placeholder="如：柯桥××布行"
            />
            <Input
              label="供应商送货单号"
              value={form.supplierDocNo}
              onChange={(e) => setForm({ ...form, supplierDocNo: e.target.value })}
            />
            <Input
              label="仓库 / 仓位"
              value={form.warehouse}
              onChange={(e) => setForm({ ...form, warehouse: e.target.value })}
            />
            <Input
              label="入库日期"
              type="date"
              value={form.inboundDate}
              onChange={(e) => setForm({ ...form, inboundDate: e.target.value })}
            />
          </div>
          <Input
            label="备注"
            value={form.remark}
            onChange={(e) => setForm({ ...form, remark: e.target.value })}
          />

          <div className="border-t border-neutral-200 pt-4">
            <div className="flex items-center gap-3">
              <Input
                label="搜索商品"
                value={productKeyword}
                onChange={(e) => setProductKeyword(e.target.value)}
                placeholder="商品名称 / 货号"
              />
            </div>
            <div className="mt-2 max-h-40 overflow-auto border border-neutral-200 rounded">
              {productOptions.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => void pickProduct(p)}
                  className={cn(
                    'w-full text-left px-3 py-2 text-sm border-b border-neutral-100 last:border-0 hover:bg-neutral-50',
                    pickedProduct?.id === p.id && 'bg-primary-50',
                  )}
                >
                  {p.name}
                  {p.skuCode ? <span className="text-neutral-400 ml-2">({p.skuCode})</span> : null}
                </button>
              ))}
              {productOptions.length === 0 && (
                <div className="px-3 py-4 text-sm text-neutral-400 text-center">输入关键词搜索商品</div>
              )}
            </div>
          </div>

          {pickedProduct && (
            <div className="border-t border-neutral-200 pt-4">
              <div className="text-sm font-medium text-neutral-700 mb-2 flex items-center gap-1.5">
                <Layers className="w-4 h-4" />
                选择入库 SKU（勾选即加入明细，一行 = 一个批次）
              </div>
              <div className="max-h-40 overflow-auto border border-neutral-200 rounded">
                {productSkus.map((sku) => {
                  const checked = draftLines.some((l) => l.skuId === Number(sku.id))
                  return (
                    <label
                      key={sku.id}
                      className="flex items-center gap-3 px-3 py-2 text-sm border-b border-neutral-100 last:border-0 hover:bg-neutral-50 cursor-pointer"
                    >
                      <input type="checkbox" checked={checked} onChange={() => toggleSku(sku)} />
                      <span className="flex-1">
                        {sku.colorName || '默认色'} / {sku.doorWidth || '默认门幅'}
                      </span>
                      <span className="text-neutral-500">
                        当前库存 {formatStockQuantity(sku.stock ?? 0)}
                      </span>
                    </label>
                  )
                })}
                {!skuLoading && productSkus.length === 0 && (
                  <div className="px-3 py-4 text-sm text-neutral-400 text-center">
                    该商品还没有 SKU，请先在商品详情维护 SKU
                  </div>
                )}
                {skuLoading && (
                  <div className="px-3 py-4 text-sm text-neutral-400 text-center">加载中…</div>
                )}
              </div>
            </div>
          )}

          {draftLines.length > 0 && (
            <div className="border-t border-neutral-200 pt-4">
              <div className="text-sm font-medium text-neutral-700 mb-2">入库明细</div>
              <table className="w-full text-sm">
                <thead className="bg-neutral-50 text-neutral-600">
                  <tr>
                    <th className="text-left px-2 py-2 font-medium">SKU</th>
                    <th className="text-right px-2 py-2 font-medium w-24">数量*</th>
                    <th className="text-right px-2 py-2 font-medium w-28">单价(元)</th>
                    <th className="text-left px-2 py-2 font-medium w-32">缸号</th>
                    <th className="text-right px-2 py-2 font-medium w-24">卷长(米)</th>
                    <th className="w-10" />
                  </tr>
                </thead>
                <tbody>
                  {draftLines.map((l) => (
                    <tr key={l.skuId} className="border-t border-neutral-100">
                      <td className="px-2 py-1.5 text-neutral-700">{l.label}</td>
                      <td className="px-2 py-1.5">
                        <input
                          type="number"
                          min={1}
                          step={0.1}
                          aria-label={`${l.label} 数量`}
                          value={l.quantity}
                          onChange={(e) => patchLine(l.skuId, { quantity: e.target.value })}
                          className="w-full h-8 px-2 border border-neutral-300 rounded text-right"
                        />
                      </td>
                      <td className="px-2 py-1.5">
                        <input
                          type="number"
                          min={0}
                          step="0.01"
                          aria-label={`${l.label} 单价`}
                          value={l.unitCost}
                          onChange={(e) => patchLine(l.skuId, { unitCost: e.target.value })}
                          className="w-full h-8 px-2 border border-neutral-300 rounded text-right"
                        />
                      </td>
                      <td className="px-2 py-1.5">
                        <input
                          aria-label={`${l.label} 缸号`}
                          value={l.dyeLot}
                          onChange={(e) => patchLine(l.skuId, { dyeLot: e.target.value })}
                          className="w-full h-8 px-2 border border-neutral-300 rounded"
                        />
                      </td>
                      <td className="px-2 py-1.5">
                        <input
                          type="number"
                          min={0}
                          step="0.01"
                          aria-label={`${l.label} 卷长`}
                          value={l.rollLengthM}
                          onChange={(e) => patchLine(l.skuId, { rollLengthM: e.target.value })}
                          className="w-full h-8 px-2 border border-neutral-300 rounded text-right"
                        />
                      </td>
                      <td className="px-2 py-1.5 text-right">
                        <button
                          type="button"
                          aria-label={`移除 ${l.label}`}
                          onClick={() => toggleSku({ id: String(l.skuId) } as ProductSku)}
                          className="text-neutral-400 hover:text-red-600"
                        >
                          ×
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="text-xs text-neutral-400 mt-2">
                数量按 0.1 米粒度（如 60.5 米），最多 1 位小数 —— 超 1 位小数会被拒绝，不会四舍五入；
                单价留空 = 只加数量、不算成本（均价保持原值）；缸号是供应商给的外部事实，与系统批次号是两件事。
              </p>
            </div>
          )}
        </div>
      </Modal>

      {/* 详情弹窗 */}
      <Modal
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
        title={detail ? `入库单 ${detail.inboundNo}` : '入库单'}
        width={860}
        footer={
          detail ? (
            <div className="flex items-center justify-between w-full">
              <span className="text-sm text-neutral-500">
                {detail.status === 'draft'
                  ? '草稿：库存尚未变动'
                  : detail.status === 'posted'
                    ? `已过账：${detail.postedBy || '-'} 于 ${detail.postedAt || '-'}`
                    : `已作废：${detail.cancelledReason || '-'}`}
              </span>
              <div className="flex gap-2">
                {detail.status === 'draft' && (
                  <>
                    <Button variant="danger" onClick={() => void doCancel()} loading={acting}>
                      <Ban className="w-4 h-4 mr-1.5" />
                      作废
                    </Button>
                    <Button onClick={() => void doPost()} loading={acting}>
                      <Send className="w-4 h-4 mr-1.5" />
                      过账（生成批次号并加库存）
                    </Button>
                  </>
                )}
                <Button variant="secondary" onClick={() => setDetailOpen(false)}>
                  关闭
                </Button>
              </div>
            </div>
          ) : null
        }
      >
        {detail && (
          <div className="space-y-4">
            <div className="grid grid-cols-3 gap-3 text-sm">
              <div>
                <div className="text-neutral-500">入库日期</div>
                <div className="text-neutral-900">{detail.inboundDate}</div>
              </div>
              <div>
                <div className="text-neutral-500">供应商</div>
                <div className="text-neutral-900">{detail.supplier || '-'}</div>
              </div>
              <div>
                <div className="text-neutral-500">仓库</div>
                <div className="text-neutral-900">{detail.warehouse || '-'}</div>
              </div>
              <div>
                <div className="text-neutral-500">供应商送货单号</div>
                <div className="text-neutral-900">{detail.supplierDocNo || '-'}</div>
              </div>
              <div>
                <div className="text-neutral-500">金额合计</div>
                <div className="text-neutral-900">¥{Number(detail.totalAmount ?? 0).toFixed(2)}</div>
              </div>
              <div>
                <div className="text-neutral-500">状态</div>
                <div className="text-neutral-900">{STATUS_LABEL[detail.status]}</div>
              </div>
            </div>

            <table className="w-full text-sm border border-neutral-200 rounded overflow-hidden">
              <thead className="bg-neutral-50 text-neutral-600">
                <tr>
                  <th className="text-left px-3 py-2 font-medium">货号 / 颜色 / 门幅</th>
                  <th className="text-right px-3 py-2 font-medium">数量</th>
                  <th className="text-right px-3 py-2 font-medium">单价</th>
                  <th className="text-right px-3 py-2 font-medium">金额</th>
                  <th className="text-left px-3 py-2 font-medium">批次号</th>
                  <th className="text-left px-3 py-2 font-medium">缸号</th>
                </tr>
              </thead>
              <tbody>
                {detail.items?.map((it) => (
                  <tr key={it.id} className="border-t border-neutral-100">
                    <td className="px-3 py-2 text-neutral-700">
                      {it.skuCode || '-'} / {it.colorName || '-'} / {it.doorWidth || '-'}
                    </td>
                    <td className="px-3 py-2 text-right">{formatStockQuantity(it.quantity)}</td>
                    <td className="px-3 py-2 text-right">
                      {it.unitCost != null ? `¥${Number(it.unitCost).toFixed(2)}` : '未记'}
                    </td>
                    <td className="px-3 py-2 text-right">
                      {it.amount != null ? `¥${Number(it.amount).toFixed(2)}` : '-'}
                    </td>
                    <td className="px-3 py-2 font-mono text-neutral-900">{it.batchNo || '过账后生成'}</td>
                    <td className="px-3 py-2 text-neutral-600">{it.dyeLot || '-'}</td>
                  </tr>
                ))}
                {(!detail.items || detail.items.length === 0) && (
                  <tr>
                    <td colSpan={6} className="px-3 py-6 text-center text-neutral-400">
                      无明细
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </Modal>
    </div>
  )
}
