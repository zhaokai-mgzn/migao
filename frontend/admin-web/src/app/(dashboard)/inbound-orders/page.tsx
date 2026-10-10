'use client'

import { useCallback, useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Plus, RotateCcw, Search, Send, Ban, PackageOpen, Upload, Download } from 'lucide-react'
import { toast } from 'sonner'
import { inboundOrderApi } from '@/lib/api'
import { Modal, Button, Input, Select, Badge } from '@/components/ui'
import type { InboundOrder, InboundOrderLine, InboundOrderStatus, OpeningImportReport } from '@/types'
import { cn } from '@/lib/utils'
import { formatStockQuantity } from '@/lib/stock-quantity'
import { usePermission } from '@/lib/permission'

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
// 建账入口（V118 / issue #5153）：① 独立整页 `/inbound-orders/new`（issue #5844）里把来源选成
//   「期初建账」即可单条录入（可填旧系统批次号）；② 页头「期初建账导入」= Excel 批量（模板 +
//   逐行校验报告 + 可重跑，幂等键 `importRunId` 必填 —— 重跑同一标识不会重复建账、不会重复加库存）。
//
// 建单入口（issue #5844，用户 2026-10-01 裁定）：**独立整页** `/inbound-orders/new`
//   —— 与 `/orders/new`、`/products/new` 同构；本页**不再有建单弹窗**（版式件与全站不同族）。
// 批次号可见化（issue #5844，**只做可见、不改生成时机**）：列表列「批次号」= 该单过账后
//   **逐行**生成的 `PC-yyyyMMdd-NNNN` 聚合（草稿未过账 ⇒ 「过账后生成」，作废 ⇒ 「-」）。

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

/**
 * 状态 → 共享原语 `Badge` 的 variant / 形状（`Badge` 自带 `whitespace-nowrap`，且落在 UI-056 的元守卫面内）。
 *
 * `rounded-full` 与草稿底色是**有意覆盖**：`Badge` 默认 `rounded` + `bg-neutral-50`，而 neutral-50
 * **与本页行的 hover 底色同值**（`hover:bg-neutral-50`）⇒ 直接复用会让草稿药丸在鼠标悬停那一行时
 * 「消失」（填充与行底色完全相同、只剩 1px 边框）。这里覆盖回改前的胶囊形状 + neutral-100。
 */
const STATUS_BADGE: Record<InboundOrderStatus, { variant: 'default' | 'success' | 'error'; className: string }> = {
  draft: { variant: 'default', className: 'rounded-full bg-neutral-100 text-neutral-700' },
  posted: { variant: 'success', className: 'rounded-full' },
  cancelled: { variant: 'error', className: 'rounded-full' },
}

/**
 * 列表的「批次号」单元格（issue #5844，**只做可见**）。
 *
 * 一个入库单过账后**逐行**生成批次号（一行 = 一个批次）⇒ 列表里只能是**聚合**展示：
 * 单个直接显示；多个显示「首个 等 N 个」（完整清单在详情弹窗里逐行可查）。
 * 草稿**未过账**（批次号 = 「真的收货了」的标识，草稿不发号）⇒ 「过账后生成」；
 * 已作废的单永远不会过账 ⇒ 「-」（不谎报成「过账后生成」）。
 */
function batchCell(row: InboundOrderLine): string {
  const nos = (row.batchNos || '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
  if (nos.length === 0) {
    return row.status === 'draft' ? '过账后生成' : '-'
  }
  return nos.length === 1 ? nos[0] : `${nos[0]} 等 ${nos.length} 个`
}

/** 每次「开始一次批量导入」的运行标识（幂等键）：重跑同一份文件时**不要改**它 */
function newImportRunId(): string {
  const day = new Date().toISOString().slice(0, 10).replace(/-/g, '')
  return `opening-${day}-${Date.now().toString(36)}`
}

export default function InboundOrdersPage() {
  const router = useRouter()
  // issue #5983：列表页**写按钮随权限显隐** —— 与员工页同范式。页面守卫是**读**码 `inbound:view`，
  // 建单入口 `/inbound-orders/new` 的提交要 `inbound:create` ⇒ 无码时按钮不渲染（不再"白点一下"）。
  const { has: hasPermission } = usePermission()
  const canWrite = hasPermission('inbound:create')
  const [keyword, setKeyword] = useState('')
  const [status, setStatus] = useState<InboundOrderStatus | ''>('')
  const [rows, setRows] = useState<InboundOrderLine[]>([])
  const [loading, setLoading] = useState(false)
  /**
   * 读面失败（issue #6691）：与「暂无入库单」**互斥** —— 故障不是业务事实。
   * 改前 catch 只 `setRows([])` ⇒ 商家以为「我的入库单全不见了」（真实报障形态）。
   */
  const [loadError, setLoadError] = useState(false)

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
    setLoadError(false)
    try {
      const res = await inboundOrderApi.list({ keyword: keyword || undefined, status })
      setRows(res.data.data ?? [])
    } catch {
      // request 拦截器已 toast；此处只**标失败态**（不清零、不说空）—— 读面故障 ≠「没有入库单」（issue #6691）
      setLoadError(true)
    } finally {
      setLoading(false)
    }
  }, [keyword, status])

  useEffect(() => {
    void load()
  }, [load])

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
      toast.error('导入标识不能为空 —— 同一个标识只建一次账，重跑同一份文件不会重复建单、不会重复加库存')
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
        toast.success('这次导入已经建过账了（同一个标识只建一次，没有重复加库存）')
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
          <p className="text-sm text-neutral-500 mt-1">登记布料到货、过账后加库存 —— <strong>过账前不改动库存</strong>，可以先核对再确认。<strong>期初建账</strong>可按实物把在库批次登记进来</p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={openImport}>
            <Upload className="w-4 h-4 mr-1.5" />
            期初建账导入
          </Button>
          {canWrite && (
            <Button onClick={() => router.push('/inbound-orders/new')}>
              <Plus className="w-4 h-4 mr-1.5" />
              新建入库单
            </Button>
          )}
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
        {/* issue #6398：`w-full` 会把列压到 CJK min-content（一个汉字）⇒ 必须给横向逃逸口 +
            `whitespace-nowrap`（否则表头折行、状态药丸竖排）。同省料看板 / 工艺路线的既有范式。 */}
        <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-neutral-50 text-neutral-600">
            <tr>
              <th className="text-left px-3 py-2.5 font-medium whitespace-nowrap">入库单号</th>
              <th className="text-left px-3 py-2.5 font-medium whitespace-nowrap">入库日期</th>
              <th className="text-left px-3 py-2.5 font-medium whitespace-nowrap">供应商</th>
              <th className="text-left px-3 py-2.5 font-medium whitespace-nowrap">仓库</th>
              <th className="text-right px-3 py-2.5 font-medium whitespace-nowrap">行数 / 总数量</th>
              <th className="text-left px-3 py-2.5 font-medium whitespace-nowrap">批次号</th>
              <th className="text-right px-3 py-2.5 font-medium whitespace-nowrap">金额</th>
              <th className="text-left px-3 py-2.5 font-medium whitespace-nowrap">状态</th>
              {/* 操作（issue #6717）：右缘冻结 —— 改前 1280×800 实测本列表头 left = 1317
                  （容器右缘 1280）⇒ 出屏，「详情」按钮够不到。`bg-neutral-50` 与 `thead` 同色
                  （不透明，横向滚过的内容不会穿透）；数据格用 `bg-inherit` 随 `<tr>` 的 hover 变色。 */}
              <th className="sticky right-0 z-20 border-l border-neutral-200 bg-neutral-50 text-right px-3 py-2.5 font-medium whitespace-nowrap">操作</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              // issue #6717：行背景**显式**声明（`bg-white` + hover）—— `bg-inherit` 的 sticky 格
              // 只认 `<tr>` 自己声明的背景；靠祖先链上的白底会继承成**透明** ⇒ 穿透。
              <tr key={row.id} className="border-t border-neutral-100 bg-white hover:bg-neutral-50">
                <td className="px-3 py-2.5 font-mono text-neutral-900 whitespace-nowrap">{row.inboundNo}</td>
                <td className="px-3 py-2.5 text-neutral-600 whitespace-nowrap">{row.inboundDate}</td>
                <td className="px-3 py-2.5 text-neutral-600 whitespace-nowrap">{row.supplier || '-'}</td>
                <td className="px-3 py-2.5 text-neutral-600 whitespace-nowrap">{row.warehouse || '-'}</td>
                <td className="px-3 py-2.5 text-right text-neutral-600 whitespace-nowrap">
                  {row.itemCount} / {formatStockQuantity(row.totalQuantity)}
                </td>
                <td
                  data-testid="inbound-batch-nos"
                  className="px-3 py-2.5 font-mono text-xs text-neutral-600 whitespace-nowrap"
                >
                  {batchCell(row)}
                </td>
                <td className="px-3 py-2.5 text-right text-neutral-900 whitespace-nowrap">
                  {row.totalAmount != null ? `¥${Number(row.totalAmount).toFixed(2)}` : '-'}
                </td>
                <td className="px-3 py-2.5 whitespace-nowrap">
                  <Badge
                    variant={STATUS_BADGE[row.status].variant}
                    className={STATUS_BADGE[row.status].className}
                  >
                    {STATUS_LABEL[row.status]}
                  </Badge>
                </td>
                {/* 操作（issue #6717）：右缘冻结（背景随 `<tr>`，见行上的注释） */}
                <td className="sticky right-0 z-10 border-l border-neutral-100 bg-inherit px-3 py-2.5 text-right whitespace-nowrap">
                  <Button variant="ghost" size="sm" onClick={() => void openDetail(row.id)}>
                    详情
                  </Button>
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={9} className="px-3 py-10 text-center text-neutral-400">
                  {loading ? (
                    '加载中…'
                  ) : loadError ? (
                    // 失败态与空态**分离**（issue #6691）：说清「没读到」+ 重试出口
                    <span data-testid="inbound-load-error" role="alert" className="inline-flex items-center gap-3">
                      <span className="text-neutral-600">入库单加载失败 —— 没读到数据，请检查网络后重试</span>
                      <Button variant="secondary" size="sm" data-testid="inbound-load-retry" onClick={() => void load()}>
                        重新加载
                      </Button>
                    </span>
                  ) : (
                    '暂无入库单'
                  )}
                </td>
              </tr>
            )}
          </tbody>
        </table>
        </div>
      </div>

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
            尾料不足整米也能如实登记，<strong>系统不会四舍五入替你改</strong>。
          </p>

          <div className="grid grid-cols-2 gap-3">
            <Input
              label="导入标识"
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
                  <th className="text-right px-3 py-2 font-medium">卷长(米)</th>
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
                    {/* 卷长「1 卷 = 多少米」：**原值直读**（`NUMERIC(8,2)`）。
                        ⚠️ 刻意**不用** `formatStockQuantity` —— 那是**库存米数**的 0.1 米粒度格式化器，
                        拿它渲染卷长会把 58.55 静默变成 58.6（两个不同的量各有自己的精度）。
                        未填 ⇒ 「-」（不写 0：0 米一卷不是「没填」的意思）。 */}
                    <td className="px-3 py-2 text-right text-neutral-600">
                      {it.rollLengthM != null ? String(it.rollLengthM) : '-'}
                    </td>
                    <td className="px-3 py-2 font-mono text-neutral-600">{it.legacyBatchNo || '-'}</td>
                  </tr>
                ))}
                {(!detail.items || detail.items.length === 0) && (
                  <tr>
                    <td colSpan={8} className="px-3 py-6 text-center text-neutral-400">
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
