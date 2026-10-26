'use client'

import { InlineMarkdown } from '@/lib/inline-markdown'
import { displayEnum } from '@/lib/enum-display'
import { SALE_FORM_FABRIC } from '@/lib/sale-form'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { PackageMinus, Plus, RefreshCw, Search } from 'lucide-react'
import { toast } from 'sonner'
import { Button, EmptyState, Input, Modal, PageCard, PageHeader, Select, Table } from '@/components/ui'
import ListLoadError from '@/components/common/ListLoadError'
import WarehouseLocationPanel from '@/components/stock/WarehouseLocationPanel'
import SkuPicker, { type SkuPickerChoice, skuLineLabel } from '@/components/products/SkuPicker'
import { finishedGoodsApi, outboundOrderApi, warehouseApi } from '@/lib/api'
import { usePermission } from '@/lib/permission'
import { checkStockQuantity, formatStockQuantity } from '@/lib/stock-quantity'
import type { FinishedGoods, OutboundOrder } from '@/types'
import type { Warehouse } from '@/types/stocktake'

/**
 * 出库单 `/outbound-orders`（V194，issue #7750）。
 *
 * ## 它是什么
 *
 * 与「入库单」**对称**的出口单据，一套单据两种业务类别：
 * - `fabric` 布料手工出库：商家建单 ⇒ **建单即过账**（原子扣 SKU 米数库存 + 落库存台账）；
 * - `finished` 成品发货出库：**由发货动作自动建单**（不在本页手建 —— 手建一张成品出库单
 *   等于绕过发货流程把货发走）。
 *
 * ## 为什么没有「草稿 / 过账」两态
 *
 * 用户 2026-10-25 逐字：「做成入库即过账，不要单独再点击过账了」。出库是**对称**的物理动作
 * （货已经拉走了才来登记），留草稿只多一个「谁忘了过账」的坑。服务端 DB CHECK 也把状态锁成
 * `posted` 一个取值 —— 本页因此没有过账按钮，也没有草稿筛选。
 *
 * ## 第二个页签 = 成品库存（带**仓位号**）
 *
 * 打包时会自动给每个成品行分配成品仓的仓位号（`A-01`…），成品发货后释放。
 * 仓管问「A-03 上那件是谁的」时，答案就在这里 —— 而不是去翻入库单。
 *
 * ## 第三个页签 = 仓位管理（issue #7785）
 *
 * 仓位号此前只能由打包动作自动生成，商家清不掉废号、也没法按现场货架预置仓号。
 * 这个页签把仓位当主数据来管：新建 / 编辑 / 启停 / 删除；占用中的仓位不能改号或删除。
 * 自动分配口径不变：优先复用最小空闲号，全占满才新增。
 *
 * ## 边界（照实登记）
 *
 * - 不做「移库」（把在库成品从 A-01 挪到 A-02）：仓位随打包分配、随发货释放；
 * - 不做「成品手工出库」：成品出库只发生在发货（`source=ship`）；
 * - 出库单**不可作废**：冲销须另开入库单（与「已过账不得作废」同一条留痕口径）。
 */

const BIZ_LABEL: Record<string, string> = {
  // 「布料」字面量的唯一家在 `lib/sale-form.ts`（类级守卫：该字面量只许出现在那与下单页）
  fabric: SALE_FORM_FABRIC,
  finished: '成品',
}

const SOURCE_LABEL: Record<string, string> = {
  manual: '手工出库',
  ship: '发货出库',
}

const FINISHED_STATUS_LABEL: Record<string, string> = {
  in_stock: '在库',
  shipped: '已发货',
  unpacked: '已撤销打包',
}

interface DraftLine {
  skuId: string
  label: string
  quantity: string
}

export default function OutboundOrdersPage() {
  const { has: hasPermission } = usePermission()
  const canWrite = hasPermission('inbound:create')

  const [tab, setTab] = useState<'documents' | 'finished' | 'locations'>('documents')
  const [locationsRefreshKey, setLocationsRefreshKey] = useState(0)
  const [keyword, setKeyword] = useState('')
  const [appliedKeyword, setAppliedKeyword] = useState('')

  const [orders, setOrders] = useState<OutboundOrder[]>([])
  const [ordersLoading, setOrdersLoading] = useState(true)
  const [ordersError, setOrdersError] = useState(false)

  const [finished, setFinished] = useState<FinishedGoods[]>([])
  const [finishedLoading, setFinishedLoading] = useState(false)
  const [finishedError, setFinishedError] = useState(false)

  const [warehouses, setWarehouses] = useState<Warehouse[]>([])
  const [createOpen, setCreateOpen] = useState(false)
  const [warehouseId, setWarehouseId] = useState<string>('')
  const [remark, setRemark] = useState('')
  const [draftLines, setDraftLines] = useState<DraftLine[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [detail, setDetail] = useState<OutboundOrder | null>(null)

  const loadOrders = useCallback(async () => {
    setOrdersLoading(true)
    setOrdersError(false)
    try {
      const res = await outboundOrderApi.list({ keyword: appliedKeyword || undefined })
      setOrders(res.data.data || [])
    } catch {
      // 读失败 ≠ 空态：常驻错误出口 + 重试（issue #6691）
      setOrdersError(true)
    } finally {
      setOrdersLoading(false)
    }
  }, [appliedKeyword])

  const loadFinished = useCallback(async () => {
    setFinishedLoading(true)
    setFinishedError(false)
    try {
      const res = await finishedGoodsApi.listInStock()
      setFinished(res.data.data || [])
    } catch {
      setFinishedError(true)
    } finally {
      setFinishedLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadOrders()
  }, [loadOrders])

  useEffect(() => {
    if (tab === 'finished') {
      void loadFinished()
    }
  }, [tab, loadFinished])

  useEffect(() => {
    // 仓库下拉：只服务于「布料出库落哪个仓」；读失败不挡出库（后端会用默认仓兜底）
    warehouseApi
      .list()
      .then((res) => setWarehouses(res.data.data || []))
      .catch(() => setWarehouses([]))
  }, [])

  const toggleSku = (choice: SkuPickerChoice) => {
    setDraftLines((prev) => {
      const exists = prev.some((l) => l.skuId === String(choice.sku.id))
      if (exists) {
        return prev.filter((l) => l.skuId !== String(choice.sku.id))
      }
      return [
        ...prev,
        {
          skuId: String(choice.sku.id),
          label: skuLineLabel(choice.product, choice.sku),
          quantity: '',
        },
      ]
    })
  }

  const closeCreate = () => {
    if (submitting) return
    setCreateOpen(false)
    setDraftLines([])
    setRemark('')
    setWarehouseId('')
  }

  const submitCreate = async () => {
    if (draftLines.length === 0) {
      toast.error('请至少勾选一个 SKU 作为出库明细')
      return
    }
    for (const line of draftLines) {
      const reason = checkStockQuantity(line.quantity)
      if (reason) {
        toast.error(`「${line.label}」的${reason}`)
        return
      }
    }
    setSubmitting(true)
    try {
      await outboundOrderApi.create({
        warehouseId: warehouseId === '' ? null : Number(warehouseId),
        remark: remark || null,
        items: draftLines.map((line) => ({
          // 雪花号字符串原样透传（issue #5904：Number() 会吞末位）
          skuId: line.skuId,
          quantity: Number(line.quantity),
        })),
      })
      toast.success('已出库：库存已扣减、台账已记账（出库单无草稿态）')
      closeCreate()
      await loadOrders()
    } catch {
      // 拦截器已提示（库存不足等业务错误带服务端原文）
    } finally {
      setSubmitting(false)
    }
  }

  const openDetail = async (row: OutboundOrder) => {
    try {
      const res = await outboundOrderApi.detail(row.id)
      setDetail(res.data.data)
    } catch {
      setDetail(row)
    }
  }

  const orderColumns = useMemo(
    () => [
      {
        key: 'outboundNo',
        title: '出库单号',
        dataIndex: 'outboundNo' as const,
        render: (row: OutboundOrder) => (
          <span className="font-mono text-neutral-900">{row.outboundNo}</span>
        ),
      },
      {
        key: 'bizCategory',
        title: '类别',
        dataIndex: 'bizCategory' as const,
        render: (row: OutboundOrder) => displayEnum(BIZ_LABEL, row.bizCategory),
      },
      {
        key: 'source',
        title: '来源',
        dataIndex: 'source' as const,
        render: (row: OutboundOrder) => displayEnum(SOURCE_LABEL, row.source),
      },
      {
        key: 'warehouse',
        title: '仓库',
        dataIndex: 'warehouse' as const,
        render: (row: OutboundOrder) => row.warehouse || '—',
      },
      {
        key: 'orderNo',
        title: '关联订单',
        dataIndex: 'orderNo' as const,
        render: (row: OutboundOrder) => row.orderNo || '—',
      },
      {
        key: 'outboundDate',
        title: '出库日期',
        dataIndex: 'outboundDate' as const,
      },
      {
        key: 'itemCount',
        title: '行数',
        dataIndex: 'itemCount' as const,
        align: 'right' as const,
        render: (row: OutboundOrder) => row.itemCount ?? 0,
      },
      {
        key: 'totalQuantity',
        title: '数量合计',
        dataIndex: 'totalQuantity' as const,
        align: 'right' as const,
        render: (row: OutboundOrder) => formatStockQuantity(row.totalQuantity ?? 0),
      },
      {
        key: 'status',
        title: '状态',
        dataIndex: 'status' as const,
        render: () => (
          <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700">已过账</span>
        ),
      },
    ],
    [],
  )

  const finishedColumns = useMemo(
    () => [
      {
        key: 'binCode',
        title: '仓位号',
        dataIndex: 'binCode' as const,
        render: (row: FinishedGoods) => (
          <span className="font-mono font-semibold text-neutral-900" data-testid="finished-bin-code">
            {row.binCode}
          </span>
        ),
      },
      {
        key: 'productName',
        title: '品名',
        dataIndex: 'productName' as const,
        render: (row: FinishedGoods) => row.productName || '—',
      },
      {
        key: 'orderNo',
        title: '订单号',
        dataIndex: 'orderNo' as const,
        render: (row: FinishedGoods) => row.orderNo || row.orderId,
      },
      {
        key: 'quantity',
        title: '数量',
        dataIndex: 'quantity' as const,
        align: 'right' as const,
        render: (row: FinishedGoods) =>
          `${formatStockQuantity(row.quantity)}${row.unit === 'set' ? ' 套' : ` ${row.unit}`}`,
      },
      {
        // 显示单号 RK-…（服务端投影 inbound_orders.inbound_no，issue #7792）；
        // `inboundOrderId` 是入库单的内部 id，属内部标识，不上屏。
        key: 'inboundNo',
        title: '入库单',
        dataIndex: 'inboundNo' as const,
        render: (row: FinishedGoods) => row.inboundNo || '—',
      },
      {
        key: 'status',
        title: '状态',
        dataIndex: 'status' as const,
        render: (row: FinishedGoods) => displayEnum(FINISHED_STATUS_LABEL, row.status),
      },
    ],
    [],
  )

  return (
    <div data-testid="outbound-orders-page" className="p-6 space-y-4">
      <PageHeader
        title={
          <span className="flex items-center gap-2">
            <PackageMinus className="w-5 h-5 text-primary-600" />
            出库单
          </span>
        }
        subtitle={
          <InlineMarkdown
            text={'与入库单对称的出口单据 —— **建单即过账**（扣库存 + 落台账一次完成）。成品发货出库由发货动作自动生成，不在这里手建。'}
          />
        }
        actions={
          <>
            <Button
              variant="secondary"
              onClick={() => {
                if (tab === 'documents') void loadOrders()
                else if (tab === 'finished') void loadFinished()
                else setLocationsRefreshKey((key) => key + 1)
              }}
            >
              <RefreshCw className="mr-1 h-4 w-4" />
              刷新
            </Button>
            {tab === 'documents' && canWrite && (
              <Button onClick={() => setCreateOpen(true)}>
                <Plus className="mr-1 h-4 w-4" />
                新建出库单
              </Button>
            )}
          </>
        }
      />

      {/* 视图切换：出库单 × 成品库存 × 仓位管理（药丸态 = 本仓既有口径，见库存明细页） */}
      <div className="flex gap-2" role="tablist" aria-label="出库单视图">
        {(
          [
            ['documents', '出库单'],
            ['finished', '成品库存'],
            ['locations', '仓位管理'],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            data-testid={`outbound-tab-${key}`}
            onClick={() => setTab(key)}
            className={
              'rounded-md border px-3 py-1.5 text-sm ' +
              (tab === key
                ? 'border-primary-300 bg-primary-50 text-primary-700'
                : 'border-neutral-300 bg-white text-neutral-600 hover:border-primary-300')
            }
          >
            {label}
          </button>
        ))}
      </div>

      {tab === 'documents' && (
        <>
          <PageCard className="flex items-center gap-3">
            <Input
              placeholder="搜索出库单号 / 仓库 / 订单号"
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') setAppliedKeyword(keyword.trim())
              }}
              className="max-w-xs"
              data-testid="outbound-search"
            />
            <Button variant="secondary" onClick={() => setAppliedKeyword(keyword.trim())}>
              <Search className="w-4 h-4 mr-1.5" />
              查询
            </Button>
            <Button
              variant="ghost"
              onClick={() => {
                setKeyword('')
                setAppliedKeyword('')
              }}
            >
              重置
            </Button>
          </PageCard>
          <PageCard padded={false} className="overflow-hidden">

          {ordersError ? (
            <ListLoadError
              testId="outbound-orders-load-error"
              message="没读到出库单（不是没有数据，是这次读取失败了）"
              onRetry={() => void loadOrders()}
              retrying={ordersLoading}
            />
          ) : (
            <Table
              columns={orderColumns}
              dataSource={orders}
              loading={ordersLoading}
              rowKey={(row) => row.id}
              onRowClick={(row) => void openDetail(row)}
              emptyText="还没有出库单：布料出库点右上角「新建出库单」；成品出库在发货时自动生成"
            />
          )}
          </PageCard>
        </>
      )}

      {tab === 'finished' && (
        <PageCard padded={false} className="overflow-hidden">
          {finishedError ? (
            <ListLoadError
              testId="finished-goods-load-error"
              message="没读到成品库存（不是没有数据，是这次读取失败了）"
              onRetry={() => void loadFinished()}
              retrying={finishedLoading}
            />
          ) : finishedLoading ? (
            <div className="py-10 text-center text-sm text-neutral-500">加载中…</div>
          ) : finished.length === 0 ? (
            <EmptyState
              title="成品仓暂时是空的"
              description="工人在手机端完成打包后，系统会自动给每个成品分配成品仓仓位号，这里就能看到。仓位号也可以先按现场货架建好。"
              action={
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setTab('locations')}
                  data-testid="finished-manage-locations"
                >
                  {canWrite ? '管理仓位' : '查看仓位'}
                </Button>
              }
            />
          ) : (
            <Table
              columns={finishedColumns}
              dataSource={finished}
              rowKey={(row) => String(row.id)}
              emptyText="成品仓暂时是空的"
            />
          )}
        </PageCard>
      )}

      {tab === 'locations' && (
        <WarehouseLocationPanel canWrite={canWrite} refreshKey={locationsRefreshKey} />
      )}

      <Modal open={createOpen} onClose={closeCreate} title="新建出库单（布料）" width={960}>
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-sm text-neutral-600">仓库（不选 = 默认仓）</label>
              <Select
                value={warehouseId}
                onChange={(e) => setWarehouseId(e.target.value)}
                options={[
                  { value: '', label: '默认仓' },
                  ...warehouses.map((w) => ({
                    value: String(w.id),
                    label:
                      w.name +
                      (w.warehouseType === 'material'
                        ? '（原料仓）'
                        : w.warehouseType === 'finished'
                          ? '（成品仓）'
                          : ''),
                  })),
                ]}
              />
            </div>
            <div>
              <label className="mb-1 block text-sm text-neutral-600">备注</label>
              <Input value={remark} onChange={(e) => setRemark(e.target.value)} placeholder="可空" />
            </div>
          </div>

          <SkuPicker
            selectedSkuIds={draftLines.map((l) => l.skuId)}
            onToggle={toggleSku}
            title="勾选要出库的布料（一个 SKU 一行）"
            testIdPrefix="outbound"
          />

          {draftLines.length > 0 && (
            <div className="overflow-x-auto rounded-lg border border-neutral-200">
              <table className="w-full text-sm" data-testid="outbound-draft-table">
                <thead className="bg-neutral-50 text-left text-neutral-500">
                  <tr>
                    <th className="px-3 py-2 whitespace-nowrap">货号 / 规格</th>
                    <th className="px-3 py-2 w-40 whitespace-nowrap">出库数量（米）</th>
                    <th className="px-3 py-2 w-20 whitespace-nowrap" />
                  </tr>
                </thead>
                <tbody>
                  {draftLines.map((line) => (
                    <tr key={line.skuId} className="border-t border-neutral-100">
                      <td className="px-3 py-2 text-neutral-900">{line.label}</td>
                      <td className="px-3 py-2">
                        <Input
                          type="number"
                          min="0"
                          step="0.1"
                          value={line.quantity}
                          placeholder="如 12.5"
                          onChange={(e) =>
                            setDraftLines((prev) =>
                              prev.map((l) =>
                                l.skuId === line.skuId ? { ...l, quantity: e.target.value } : l,
                              ),
                            )
                          }
                        />
                      </td>
                      <td className="px-3 py-2">
                        <button
                          type="button"
                          className="text-xs text-red-600 hover:underline"
                          onClick={() =>
                            setDraftLines((prev) => prev.filter((l) => l.skuId !== line.skuId))
                          }
                        >
                          移除
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <p className="text-xs text-neutral-500">
            提交即出库：库存不足会整笔拒绝（不会扣成负数），失败时不会留下任何单据或台账。
          </p>

          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={closeCreate} disabled={submitting}>
              取消
            </Button>
            <Button onClick={() => void submitCreate()} loading={submitting} data-testid="outbound-submit">
              确认出库
            </Button>
          </div>
        </div>
      </Modal>

      <Modal open={detail !== null} onClose={() => setDetail(null)} title={`出库单 ${detail?.outboundNo || ''}`} width={860}>
        {detail && (
          <div className="space-y-3 text-sm" data-testid="outbound-detail">
            <div className="grid gap-2 sm:grid-cols-2">
              <div>类别：{displayEnum(BIZ_LABEL, detail.bizCategory)}</div>
              <div>来源：{displayEnum(SOURCE_LABEL, detail.source)}</div>
              <div>仓库：{detail.warehouse || '—'}</div>
              <div>出库日期：{detail.outboundDate}</div>
              <div>操作人：{detail.postedBy || '—'}</div>
              <div>关联订单：{detail.orderNo || '—'}</div>
            </div>
            <div className="overflow-x-auto rounded-lg border border-neutral-200">
              <table className="w-full text-sm">
                <thead className="bg-neutral-50 text-left text-neutral-500">
                  <tr>
                    <th className="px-3 py-2 whitespace-nowrap">货号 / 品名</th>
                    <th className="px-3 py-2 whitespace-nowrap">仓位号</th>
                    <th className="px-3 py-2 text-right whitespace-nowrap">数量</th>
                    <th className="px-3 py-2 text-right whitespace-nowrap">单价</th>
                    <th className="px-3 py-2 text-right whitespace-nowrap">金额</th>
                  </tr>
                </thead>
                <tbody>
                  {(detail.items ?? []).map((item, index) => (
                    <tr key={item.id ?? index} className="border-t border-neutral-100">
                      <td className="px-3 py-2">{item.skuCode || item.productName || '—'}</td>
                      <td className="px-3 py-2 font-mono">{item.binCode || '—'}</td>
                      <td className="px-3 py-2 text-right">
                        {formatStockQuantity(item.quantity)}
                        {item.unit === 'set' ? ' 套' : ` ${item.unit}`}
                      </td>
                      <td className="px-3 py-2 text-right">
                        {item.unitCost == null ? '未记' : formatStockQuantity(item.unitCost)}
                      </td>
                      <td className="px-3 py-2 text-right">
                        {item.amount == null ? '未记' : formatStockQuantity(item.amount)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}
