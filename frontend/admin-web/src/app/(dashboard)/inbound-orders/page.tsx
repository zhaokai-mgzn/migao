'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Plus, RotateCcw, Search, Send, Ban, PackageOpen, Layers, Upload, Download } from 'lucide-react'
import { toast } from 'sonner'
import { inboundOrderApi, productApi } from '@/lib/api'
import { Modal, Button, Input, Select } from '@/components/ui'
import type {
  InboundOrder,
  InboundOrderLine,
  InboundOrderStatus,
  OpeningImportReport,
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
// 数量口径（issue #5063 + issue #5153）：库存米数**小数化**，0.1 米粒度 ⇒ 数量「**大于 0** 且最多
//   1 位小数」，与后端 admin-api **同一判据**；超 1 位小数**显式拒绝**（不静默取整），
//   见 lib/stock-quantity.ts。下限由「≥1 米」放宽（issue #5153 / GAP-12）—— 用户逐字说
//   「当前企业剩余了**大量的 0.5 米左右**的批次布料」，改前那些实物批次**连登记都进不来**。
//
// 建账入口（V118 / issue #5153）：① 「新建入库单」里把来源选成「期初建账」即可单条录入
//   （可填旧系统批次号）；② 页头「期初建账导入」= Excel 批量（模板 + 逐行校验报告 + 可重跑，
//   幂等键 `importRunId` 必填 —— 重跑同一标识不会重复建账、不会重复加库存）。

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

/** 单据来源（V117；`opening` = 期初建账/批次初始化） */
const SOURCE_OPTIONS: { value: 'purchase' | 'opening'; label: string }[] = [
  { value: 'purchase', label: '采购收货（正常入库）' },
  { value: 'opening', label: '期初建账（按实物登记在库批次）' },
]

/**
 * 建单弹窗里的一行（含 SKU 的展示快照，提交时只取
 * productId/skuId/quantity/unitCost/dyeLot/legacyBatchNo/rollLengthM）
 */
interface DraftLine {
  productId: string
  skuId: number
  label: string
  stock: number
  quantity: string
  unitCost: string
  dyeLot: string
  /** 旧系统批次号（只录入期建账时才提交；系统批次号由服务端生成，两者不得互相冒充） */
  legacyBatchNo: string
  rollLengthM: string
}

/** 每次「开始一次批量导入」的运行标识（幂等键）：重跑同一份文件时**不要改**它 */
function newImportRunId(): string {
  const day = new Date().toISOString().slice(0, 10).replace(/-/g, '')
  return `opening-${day}-${Date.now().toString(36)}`
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
    source: 'purchase' as 'purchase' | 'opening',
  })
  const [submitting, setSubmitting] = useState(false)

  // 期初建账批量导入弹窗（V118 / issue #5153）
  const [importOpen, setImportOpen] = useState(false)
  const [importRunId, setImportRunId] = useState('')
  const [importFile, setImportFile] = useState<File | null>(null)
  const [importing, setImporting] = useState(false)
  const [importReport, setImportReport] = useState<OpeningImportReport | null>(null)

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
    setForm({
      supplier: '',
      supplierDocNo: '',
      warehouse: '',
      inboundDate: '',
      remark: '',
      source: 'purchase',
    })
  }

  /** 勾选 SKU ⇒ 加入/移出草稿行（保留已填的数量/单价/缸号/旧系统批次号） */
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
          legacyBatchNo: '',
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
    // 数量必须**大于 0** 且**最多 1 位小数**（0.1 米粒度）—— 与后端同一判据。
    // 下限由「≥1 米」放宽（issue #5153）：0.5 米的尾料是**实物事实**，挡在门外 = 系统说谎。
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
        // 来源（V117 既有件）：期初建账与正常采购在库里可区分 —— 基线冻结点靠它
        source: form.source,
        items: draftLines.map((l) => ({
          productId: l.productId,
          skuId: l.skuId,
          quantity: Number(l.quantity),
          unitCost: l.unitCost === '' ? null : Number(l.unitCost),
          dyeLot: l.dyeLot || null,
          // 旧系统批次号**只在期初建账时提交**（采购入库填了后端会拒 —— 两列两义，不得互相冒充）
          legacyBatchNo: form.source === 'opening' ? l.legacyBatchNo || null : null,
          rollLengthM: l.rollLengthM === '' ? null : Number(l.rollLengthM),
        })),
      })
      toast.success(
        form.source === 'opening'
          ? '期初建账单已建（草稿，未动库存）—— 核对无误后请过账：过账即冻结基线'
          : '入库单已建（草稿，未动库存）—— 核对无误后请过账',
      )
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

  // ---- 期初建账：Excel 批量导入（V118 / issue #5153） ----

  /** 打开导入弹窗 = 开始**一次新的导入运行**（换一个幂等键；重跑同一份文件时不要改它） */
  const openImport = () => {
    setImportRunId(newImportRunId())
    setImportFile(null)
    setImportReport(null)
    setImportOpen(true)
  }

  const downloadTemplate = async () => {
    try {
      const res = await inboundOrderApi.openingTemplate()
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = '期初建账模板.xlsx'
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      // 拦截器已提示
    }
  }

  const submitImport = async () => {
    if (!importFile) {
      toast.error('请先选择要导入的 Excel 文件（.xlsx）')
      return
    }
    if (!importRunId.trim()) {
      toast.error('导入标识不能为空（它是幂等键：重跑同一标识不会重复建账）')
      return
    }
    setImporting(true)
    try {
      const res = await inboundOrderApi.openingImport(importFile, importRunId.trim())
      const report = res.data.data ?? null
      setImportReport(report)
      if (report?.created) {
        toast.success(`已建账并过账：${report.inboundNo}（共 ${report.total} 个批次）`)
        await load()
      } else if (report && report.failCount === 0 && !report.created && report.inboundNo) {
        // 幂等命中：这次运行早已建过账 —— 不是失败，但也**没有**再动库存
        toast.success('这次导入运行已经建过账（幂等命中，未重复加库存）')
      } else {
        toast.error('有明细行未通过校验，未建账（一行都没写）—— 请按报告修改后重跑')
      }
    } catch {
      // 拦截器已提示
    } finally {
      setImporting(false)
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
            商品布料入库：建单（草稿）→ 过账（自动生成批次号 + 自动加库存 + 移动加权平均成本）→ 批次可追溯；
            <strong>期初建账</strong>可按实物把在库批次（含 0.5 米级尾料）登记进来
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={openImport}>
            <Upload className="w-4 h-4 mr-1.5" />
            期初建账导入
          </Button>
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="w-4 h-4 mr-1.5" />
            新建入库单
          </Button>
        </div>
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
            <Select
              label="单据来源"
              aria-label="单据来源"
              value={form.source}
              onChange={(e) =>
                setForm({ ...form, source: e.target.value as 'purchase' | 'opening' })
              }
              options={SOURCE_OPTIONS}
            />
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
                    {form.source === 'opening' && (
                      <th className="text-left px-2 py-2 font-medium w-36">旧系统批次号</th>
                    )}
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
                          min={0.1}
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
                      {form.source === 'opening' && (
                        <td className="px-2 py-1.5">
                          <input
                            aria-label={`${l.label} 旧系统批次号`}
                            placeholder="旧系统的批次号"
                            value={l.legacyBatchNo}
                            onChange={(e) => patchLine(l.skuId, { legacyBatchNo: e.target.value })}
                            className="w-full h-8 px-2 border border-neutral-300 rounded"
                          />
                        </td>
                      )}
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
                数量按 0.1 米粒度、大于 0 即可（0.5 米的尾料能登记；0 与 2.755 会被拒绝；
                超 1 位小数不会四舍五入）；单价留空 = 只加数量、不算成本（均价保持原值）；
                缸号与旧系统批次号都是外部事实，与系统生成的批次号是三件不同的事。
              </p>
            </div>
          )}
        </div>
      </Modal>

      {/* 期初建账导入弹窗（V118 / issue #5153） */}
      <Modal
        open={importOpen}
        onClose={() => setImportOpen(false)}
        title="期初建账导入（Excel 批量）"
        width={920}
        footer={
          <div className="flex items-center justify-between w-full">
            <span className="text-sm text-neutral-500">
              一行 = 一个批次；整份文件全或无 —— 有 1 行不通过就一行都不建账
            </span>
            <div className="flex gap-2">
              <Button variant="secondary" onClick={() => setImportOpen(false)}>
                关闭
              </Button>
              <Button onClick={() => void submitImport()} loading={importing}>
                <Upload className="w-4 h-4 mr-1.5" />
                开始导入
              </Button>
            </div>
          </div>
        }
      >
        <div className="space-y-4">
          <p className="text-xs text-neutral-500 bg-neutral-50 border border-neutral-200 rounded p-2">
            导入会建一张<strong>期初建账</strong>入库单并<strong>直接过账</strong>：库存按登记的剩余米数增加、
            系统批次号自动生成、<strong>旧系统批次号原样登记</strong>。
            「剩余米数」填<strong>现在实物还剩多少米</strong>（不是当初进了多少米）——
            0.5 米这样的尾料也能如实登记（最多 1 位小数，不做静默取整）。
          </p>

          <div className="grid grid-cols-2 gap-3">
            <Input
              label="导入标识（幂等键）"
              aria-label="导入标识"
              value={importRunId}
              onChange={(e) => setImportRunId(e.target.value)}
            />
            <div className="flex items-end gap-2">
              <Button variant="secondary" onClick={() => void downloadTemplate()}>
                <Download className="w-4 h-4 mr-1.5" />
                下载模板
              </Button>
              <Button variant="ghost" onClick={() => setImportRunId(newImportRunId())}>
                换一次导入
              </Button>
            </div>
          </div>
          <p className="text-xs text-neutral-400 -mt-2">
            同一份文件<strong>重跑时不要改导入标识</strong>：同一标识只会建一次账
            （不会重复建单、不会重复加库存）。要登记新的一批，点「换一次导入」。
          </p>

          <div>
            <label className="block text-sm font-medium text-neutral-700 mb-1" htmlFor="opening-file">
              建账文件（.xlsx）
            </label>
            <input
              id="opening-file"
              type="file"
              accept=".xlsx"
              aria-label="选择建账文件"
              onChange={(e) => setImportFile(e.target.files?.[0] ?? null)}
              className="block w-full text-sm text-neutral-600 file:mr-3 file:py-1.5 file:px-3 file:rounded file:border file:border-neutral-300 file:bg-white file:text-sm"
            />
          </div>

          {importReport && (
            <div className="border-t border-neutral-200 pt-4 space-y-2">
              <div
                className={cn(
                  'text-sm rounded border p-2',
                  importReport.failCount > 0
                    ? 'bg-red-50 border-red-200 text-red-700'
                    : 'bg-green-50 border-green-200 text-green-700',
                )}
              >
                {importReport.message}
              </div>
              <table className="w-full text-sm">
                <thead className="bg-neutral-50 text-neutral-600">
                  <tr>
                    <th className="text-left px-2 py-2 font-medium w-16">行号</th>
                    <th className="text-left px-2 py-2 font-medium">货号</th>
                    <th className="text-right px-2 py-2 font-medium w-24">剩余米数</th>
                    <th className="text-left px-2 py-2 font-medium w-32">缸号</th>
                    <th className="text-left px-2 py-2 font-medium w-36">旧系统批次号</th>
                    <th className="text-left px-2 py-2 font-medium">校验结果</th>
                  </tr>
                </thead>
                <tbody>
                  {importReport.rows?.map((r) => (
                    <tr key={r.rowNo} className="border-t border-neutral-100">
                      <td className="px-2 py-1.5 text-neutral-500">{r.rowNo}</td>
                      <td className="px-2 py-1.5 text-neutral-700">{r.skuCode || '-'}</td>
                      <td className="px-2 py-1.5 text-right text-neutral-700">
                        {r.quantity != null ? formatStockQuantity(r.quantity) : '-'}
                      </td>
                      <td className="px-2 py-1.5 text-neutral-600">{r.dyeLot || '-'}</td>
                      <td className="px-2 py-1.5 font-mono text-neutral-600">
                        {r.legacyBatchNo || '-'}
                      </td>
                      <td
                        className={cn(
                          'px-2 py-1.5',
                          r.ok ? 'text-green-700' : 'text-red-600',
                        )}
                      >
                        {r.ok ? '通过' : r.message || '未通过'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
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
                  <th className="text-left px-3 py-2 font-medium">旧系统批次号</th>
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
                    <td className="px-3 py-2 font-mono text-neutral-600">{it.legacyBatchNo || '-'}</td>
                  </tr>
                ))}
                {(!detail.items || detail.items.length === 0) && (
                  <tr>
                    <td colSpan={7} className="px-3 py-6 text-center text-neutral-400">
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
