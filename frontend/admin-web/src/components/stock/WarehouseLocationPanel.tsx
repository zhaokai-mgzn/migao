'use client'

import { useCallback, useEffect, useState } from 'react'
import { Layers, Plus } from 'lucide-react'
import { toast } from 'sonner'
import {
  Button,
  EmptyState,
  Input,
  Modal,
  PageCard,
  RowActions,
  Table,
  type TableColumn,
} from '@/components/ui'
import FormPanel, { Field, FormGrid } from '@/components/ui/FormPanel'
import ListLoadError from '@/components/common/ListLoadError'
import { finishedGoodsApi } from '@/lib/api'
import type { WarehouseLocation } from '@/types'

/**
 * 成品仓仓位管理（issue #7785；水位 / 容量 / 批量建号 = issue #7791）—— 出库单页的第三个视图。
 *
 * ## 口径（服务端是唯一裁判，前端只做形态）
 *
 * - 仓位号租户内唯一、统一大写；占用中（有在库成品）**不能改号 / 删除**（在库行与已贴标签认这个号）；
 * - 水位 = 在库件数 / 每仓容量（容量按区域统一，默认 10 件）；打包优先放**水位最低且未满**的仓位；
 * - 停用只影响后续自动分配，已占用库存不受影响，可重新启用；
 * - 删除是软删；批量建号按数字区间生成，已存在的自动跳过；
 * - 容量按区域统一：改一个仓的容量会同步本区所有仓位。
 *
 * ## 边界（照实登记）
 *
 * - 不做移库（仓位随打包分配、随发货释放）；
 * - 不做货架层级 / 体积 / 重量维度（容量 = 件数）。
 */
export default function WarehouseLocationPanel({
  canWrite,
  refreshKey,
}: {
  /** `inbound:create`：没有它时整块只读（读码是 `inbound:view`，页面已门控） */
  canWrite: boolean
  /** 页面右上「刷新」的计数器：变了就重新读清单 */
  refreshKey: number
}) {
  const [rows, setRows] = useState<WarehouseLocation[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<WarehouseLocation | null>(null)
  const [form, setForm] = useState({
    binCode: '',
    zoneCode: 'A',
    zoneName: '成品区',
    remark: '',
    capacity: '10',
  })
  const [saving, setSaving] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<WarehouseLocation | null>(null)
  const [deleting, setDeleting] = useState(false)

  const [batchOpen, setBatchOpen] = useState(false)
  const [batch, setBatch] = useState({
    zoneCode: 'A',
    zoneName: '成品区',
    from: '1',
    to: '20',
    capacity: '10',
  })
  const [batching, setBatching] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      const res = await finishedGoodsApi.locations({ includeInactive: true })
      setRows(res.data.data || [])
    } catch {
      // 读失败 ≠ 没有仓位（issue #6691）：常驻错误出口 + 重试，不画成空态
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load, refreshKey])

  const capacityOf = (zoneCode: string) => {
    const row = rows.find((r) => r.zoneCode === zoneCode)
    return row?.capacity ?? 10
  }

  const nextBatchStart = (zoneCode: string) => {
    const numbers = rows
      .filter((r) => r.zoneCode === zoneCode)
      .map((r) => Number(r.binCode.match(/-(\d+)$/)?.[1] ?? 0))
    return Math.max(0, ...numbers) + 1
  }

  const openCreate = () => {
    setEditing(null)
    const zoneCode = rows[0]?.zoneCode || 'A'
    setForm({
      binCode: '',
      zoneCode,
      zoneName: rows[0]?.zoneName || '成品区',
      remark: '',
      capacity: String(capacityOf(zoneCode)),
    })
    setFormOpen(true)
  }

  const openEdit = (row: WarehouseLocation) => {
    setEditing(row)
    setForm({
      binCode: row.binCode,
      zoneCode: row.zoneCode,
      zoneName: row.zoneName,
      remark: row.remark || '',
      capacity: String(row.capacity ?? 10),
    })
    setFormOpen(true)
  }

  const openBatch = () => {
    const zoneCode = rows[0]?.zoneCode || 'A'
    const zoneName = rows[0]?.zoneName || '成品区'
    const from = nextBatchStart(zoneCode)
    setBatch({
      zoneCode,
      zoneName,
      from: String(from),
      to: String(from + 19),
      capacity: String(capacityOf(zoneCode)),
    })
    setBatchOpen(true)
  }

  const closeForm = () => {
    if (saving) return
    setFormOpen(false)
    setEditing(null)
  }

  const closeBatch = () => {
    if (batching) return
    setBatchOpen(false)
  }

  const capacityNumber = () => {
    const capacity = Number(form.capacity)
    if (!Number.isInteger(capacity) || capacity < 1 || capacity > 999) {
      toast.error('每仓容量请填 1~999 件')
      return null
    }
    return capacity
  }

  const submit = async () => {
    const binCode = form.binCode.trim()
    if (!binCode) {
      toast.error('请填写仓位号（如 A-01）')
      return
    }
    const capacity = capacityNumber()
    if (capacity == null) return
    setSaving(true)
    try {
      const payload = {
        binCode,
        zoneCode: form.zoneCode.trim() || undefined,
        zoneName: form.zoneName.trim() || undefined,
        remark: form.remark,
        capacity,
      }
      if (editing) {
        await finishedGoodsApi.updateLocation(editing.id, payload)
        toast.success(`仓位 ${binCode.toUpperCase()} 已更新`)
      } else {
        await finishedGoodsApi.createLocation(payload)
        toast.success(`仓位 ${binCode.toUpperCase()} 已创建`)
      }
      setFormOpen(false)
      setEditing(null)
      await load()
    } catch {
      // 拦截器已提示（占用中 / 重复仓位号等服务端原文）
    } finally {
      setSaving(false)
    }
  }

  const batchPreview = (() => {
    const from = Number(batch.from)
    const to = Number(batch.to)
    const capacity = Number(batch.capacity)
    if (!Number.isInteger(from) || !Number.isInteger(to) || from < 1 || to < 1) return null
    if (from > to) return { error: '结束编号不能小于起始编号' }
    const total = to - from + 1
    if (total > 500) return { error: '单次最多创建 500 个仓位' }
    if (!Number.isInteger(capacity) || capacity < 1 || capacity > 999) {
      return { error: '每仓容量请填 1~999 件' }
    }
    const zone = (batch.zoneCode.trim() || 'A').toUpperCase()
    const pad = (n: number) => String(n).padStart(2, '0')
    const existing = Array.from({ length: total }, (_, i) => `${zone}-${pad(from + i)}`)
      .filter((code) => rows.some((r) => r.binCode === code)).length
    return {
      fromCode: `${zone}-${pad(from)}`,
      toCode: `${zone}-${pad(to)}`,
      total,
      existing,
    }
  })()

  const submitBatch = async () => {
    if (!batchPreview || 'error' in batchPreview) {
      toast.error(batchPreview && 'error' in batchPreview ? batchPreview.error : '请填写有效的数字区间')
      return
    }
    const from = Number(batch.from)
    const to = Number(batch.to)
    const capacity = Number(batch.capacity)
    setBatching(true)
    try {
      const res = await finishedGoodsApi.batchCreateLocations({
        zoneCode: batch.zoneCode.trim() || 'A',
        zoneName: batch.zoneName.trim() || '成品区',
        numberFrom: from,
        numberTo: to,
        capacity,
      })
      const result = res.data.data
      toast.success(
        result.created > 0
          ? `已新建 ${result.created} 个仓位${result.skipped > 0 ? `（跳过 ${result.skipped} 个已存在）` : ''}`
          : `这 ${result.skipped} 个仓位都已存在`,
      )
      setBatchOpen(false)
      await load()
    } catch {
      // 拦截器已提示（区间 / 容量 / 权限等服务端原文）
    } finally {
      setBatching(false)
    }
  }

  const toggleStatus = async (row: WarehouseLocation) => {
    const next = row.status === 'active' ? 'inactive' : 'active'
    try {
      await finishedGoodsApi.updateLocation(row.id, { status: next })
      toast.success(next === 'inactive' ? `仓位 ${row.binCode} 已停用` : `仓位 ${row.binCode} 已启用`)
      await load()
    } catch {
      // 拦截器已提示
    }
  }

  const confirmDelete = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await finishedGoodsApi.deleteLocation(deleteTarget.id)
      toast.success(`仓位 ${deleteTarget.binCode} 已删除`)
      setDeleteTarget(null)
      await load()
    } catch {
      // 拦截器已提示（占用中 ⇒ 409 + 可行动建议）
    } finally {
      setDeleting(false)
    }
  }

  const columns: TableColumn<WarehouseLocation>[] = [
    {
      key: 'binCode',
      title: '仓位号',
      dataIndex: 'binCode',
      render: (row) => (
        <span className="font-mono font-semibold text-neutral-900" data-testid="warehouse-location-bin">
          {row.binCode}
        </span>
      ),
    },
    {
      key: 'zone',
      title: '区域',
      render: (row) => `${row.zoneName}（${row.zoneCode}）`,
    },
    {
      key: 'water',
      title: '水位',
      render: (row) => {
        const count = row.inStockCount ?? (row.occupied ? 1 : 0)
        const capacity = row.capacity ?? 10
        const pct = capacity > 0 ? Math.min(100, Math.round((count / capacity) * 100)) : 100
        const color =
          count >= capacity ? 'bg-red-500' : count / capacity >= 0.8 ? 'bg-amber-500' : 'bg-emerald-500'
        return (
          <div
            className="flex items-center gap-2 whitespace-nowrap"
            data-testid={`warehouse-location-water-${row.id}`}
          >
            <div className="h-1.5 w-16 overflow-hidden rounded-full bg-neutral-100" aria-hidden>
              <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
            </div>
            <span className="font-mono text-xs text-neutral-600">
              {count} / {capacity}
            </span>
          </div>
        )
      },
    },
    {
      key: 'state',
      title: '状态',
      render: (row) => {
        // 只读状态用「点 + 文字」陈述，不做成孤立状态徽标（#6588：状态该由控件本体表达）
        const count = row.inStockCount ?? (row.occupied ? 1 : 0)
        const capacity = row.capacity ?? 10
        const state =
          row.status === 'inactive'
            ? { label: '已停用', dot: 'bg-neutral-400', text: 'text-neutral-500' }
            : count >= capacity
              ? { label: '已满', dot: 'bg-red-500', text: 'text-red-600' }
              : count > 0
                ? { label: '占用中', dot: 'bg-amber-500', text: 'text-neutral-700' }
                : { label: '空闲', dot: 'bg-emerald-500', text: 'text-neutral-700' }
        return (
          <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
            <span className={`h-1.5 w-1.5 rounded-full ${state.dot}`} aria-hidden />
            <span className={state.text}>{state.label}</span>
          </span>
        )
      },
    },
    {
      key: 'remark',
      title: '备注',
      wrap: true,
      render: (row) => row.remark || '—',
    },
    {
      key: 'actions',
      title: '操作',
      // issue #8038：**1 主行动（编辑）+ ⋯ 菜单**（停用·启用 / 删除）。删除仍是页面既有的
      // 确认弹框（`setDeleteTarget` ⇒ `Modal`），占用中禁用 + `title` 说明为什么 —— 一字未改。
      render: (row) =>
        canWrite ? (
          <RowActions
            testId={`warehouse-location-actions-${row.id}`}
            menuTestId={`warehouse-location-menu-${row.id}`}
            items={[
              {
                key: 'toggle',
                label: row.status === 'active' ? '停用' : '启用',
                testId: `warehouse-location-toggle-${row.id}`,
                onClick: () => void toggleStatus(row),
              },
              {
                key: 'delete',
                label: '删除',
                testId: `warehouse-location-delete-${row.id}`,
                onClick: () => setDeleteTarget(row),
                danger: true,
                disabled: row.occupied,
                title: row.occupied ? '占用中的仓位不能删除：先发货或撤销打包释放' : undefined,
              },
            ]}
          >
            <Button
              variant="ghost"
              size="sm"
              data-testid={`warehouse-location-edit-${row.id}`}
              onClick={() => openEdit(row)}
            >
              编辑
            </Button>
          </RowActions>
        ) : (
          <span className="text-neutral-400">—</span>
        ),
    },
  ]

  return (
    <div className="space-y-4" data-testid="warehouse-location-panel">
      <PageCard padded={false} className="overflow-hidden">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-neutral-200 px-4 py-3">
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-neutral-900">成品仓仓位</h3>
            <p className="mt-1 text-xs leading-5 text-neutral-500">
              {'按水位（在库件数 / 每仓容量）分配：打包优先放水位最低且未满的仓位；同一区域容量统一。占用中的仓位不能改号或删除。'}
            </p>
          </div>
          {canWrite && rows.length > 0 && (
            <div className="flex items-center gap-2">
              <Button
                variant="secondary"
                size="sm"
                icon={<Layers className="h-4 w-4" />}
                onClick={openBatch}
                data-testid="warehouse-location-batch"
              >
                批量新建
              </Button>
              <Button
                variant="secondary"
                size="sm"
                icon={<Plus className="h-4 w-4" />}
                onClick={openCreate}
                data-testid="warehouse-location-create"
              >
                新建仓位
              </Button>
            </div>
          )}
        </div>

        {error ? (
          <div className="p-4">
            <ListLoadError
              testId="warehouse-locations-load-error"
              message="没读到仓位清单（不是没有仓位，是这次读取失败了）"
              onRetry={() => void load()}
              retrying={loading}
            />
          </div>
        ) : loading ? (
          <div className="py-10 text-center text-sm text-neutral-500">加载中…</div>
        ) : rows.length === 0 ? (
          <EmptyState
            icon="package"
            title="还没有仓位"
            description="打包时会自动建 A-01…；也可以按货架单个或批量建号。"
            testId="warehouse-locations-empty"
            action={
              canWrite ? (
                <div className="flex flex-wrap items-center justify-center gap-2">
                  <Button
                    variant="secondary"
                    size="sm"
                    icon={<Layers className="h-4 w-4" />}
                    onClick={openBatch}
                    data-testid="warehouse-location-batch-empty"
                  >
                    批量新建
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    icon={<Plus className="h-4 w-4" />}
                    onClick={openCreate}
                    data-testid="warehouse-location-create-empty"
                  >
                    新建仓位
                  </Button>
                </div>
              ) : undefined
            }
          />
        ) : (
          <Table
            columns={columns}
            dataSource={rows}
            rowKey={(row) => String(row.id)}
            emptyText="还没有仓位"
          />
        )}
      </PageCard>

      <Modal
        open={formOpen}
        onClose={closeForm}
        title={editing ? `编辑仓位 ${editing.binCode}` : '新建仓位'}
        width={560}
        closable={!saving}
        maskClosable={!saving}
        footer={
          <>
            <Button variant="secondary" onClick={closeForm} disabled={saving}>
              取消
            </Button>
            <Button onClick={() => void submit()} loading={saving} data-testid="warehouse-location-save">
              {editing ? '保存' : '创建'}
            </Button>
          </>
        }
      >
        <FormPanel
          title="仓位信息"
          hint="仓位号统一大写，用字母 / 数字 / 短横线（如 A-01），同租户唯一；每仓容量按区域统一。"
        >
          <FormGrid cols={2}>
            <Field
              label="仓位号"
              htmlFor="warehouse-bin-code"
              hint={editing?.occupied ? '占用中不能改号：在库成品与已贴标签都认这个号' : undefined}
            >
              <Input
                id="warehouse-bin-code"
                value={form.binCode}
                disabled={saving || (editing?.occupied ?? false)}
                onChange={(e) => setForm((prev) => ({ ...prev, binCode: e.target.value }))}
                placeholder="A-01"
                data-testid="warehouse-bin-code-input"
              />
            </Field>
            <Field label="区域编码" htmlFor="warehouse-zone-code" hint="缺省 A">
              <Input
                id="warehouse-zone-code"
                value={form.zoneCode}
                disabled={saving}
                onChange={(e) => setForm((prev) => ({ ...prev, zoneCode: e.target.value }))}
                placeholder="A"
                data-testid="warehouse-zone-code-input"
              />
            </Field>
            <Field label="区域名称" htmlFor="warehouse-zone-name" hint="展示用，缺省成品区">
              <Input
                id="warehouse-zone-name"
                value={form.zoneName}
                disabled={saving}
                onChange={(e) => setForm((prev) => ({ ...prev, zoneName: e.target.value }))}
                placeholder="成品区"
                data-testid="warehouse-zone-name-input"
              />
            </Field>
            <Field
              label="每仓容量（件）"
              htmlFor="warehouse-capacity"
              hint={`同一区域统一；改这里会同步 ${form.zoneCode || 'A'} 区所有仓位`}
            >
              <Input
                id="warehouse-capacity"
                type="number"
                min={1}
                max={999}
                value={form.capacity}
                disabled={saving}
                onChange={(e) => setForm((prev) => ({ ...prev, capacity: e.target.value }))}
                placeholder="10"
                data-testid="warehouse-capacity-input"
              />
            </Field>
            <Field label="备注" htmlFor="warehouse-remark" hint="可空，如「靠门口」">
              <Input
                id="warehouse-remark"
                value={form.remark}
                disabled={saving}
                onChange={(e) => setForm((prev) => ({ ...prev, remark: e.target.value }))}
                placeholder="可空"
                data-testid="warehouse-remark-input"
              />
            </Field>
          </FormGrid>
        </FormPanel>
      </Modal>

      <Modal
        open={batchOpen}
        onClose={closeBatch}
        title="批量新建仓位"
        width={560}
        closable={!batching}
        maskClosable={!batching}
        footer={
          <>
            <Button variant="secondary" onClick={closeBatch} disabled={batching}>
              取消
            </Button>
            <Button onClick={() => void submitBatch()} loading={batching} data-testid="warehouse-batch-submit">
              批量创建
            </Button>
          </>
        }
      >
        <FormPanel
          title="批量信息"
          hint="输入数字区间，如 1~20 ⇒ A-01…A-20；已存在的仓位号自动跳过。单次最多 500 个。"
        >
          <FormGrid cols={2}>
            <Field label="区域编码" htmlFor="warehouse-batch-zone-code" hint="缺省 A">
              <Input
                id="warehouse-batch-zone-code"
                value={batch.zoneCode}
                disabled={batching}
                onChange={(e) => setBatch((prev) => ({ ...prev, zoneCode: e.target.value }))}
                placeholder="A"
                data-testid="warehouse-batch-zone-code"
              />
            </Field>
            <Field label="区域名称" htmlFor="warehouse-batch-zone-name" hint="展示用，缺省成品区">
              <Input
                id="warehouse-batch-zone-name"
                value={batch.zoneName}
                disabled={batching}
                onChange={(e) => setBatch((prev) => ({ ...prev, zoneName: e.target.value }))}
                placeholder="成品区"
                data-testid="warehouse-batch-zone-name"
              />
            </Field>
            <Field label="起始编号" htmlFor="warehouse-batch-from" hint="含，如 1 ⇒ A-01">
              <Input
                id="warehouse-batch-from"
                type="number"
                min={1}
                max={9999}
                value={batch.from}
                disabled={batching}
                onChange={(e) => setBatch((prev) => ({ ...prev, from: e.target.value }))}
                placeholder="1"
                data-testid="warehouse-batch-from"
              />
            </Field>
            <Field label="结束编号" htmlFor="warehouse-batch-to" hint="含，如 20 ⇒ A-20">
              <Input
                id="warehouse-batch-to"
                type="number"
                min={1}
                max={9999}
                value={batch.to}
                disabled={batching}
                onChange={(e) => setBatch((prev) => ({ ...prev, to: e.target.value }))}
                placeholder="20"
                data-testid="warehouse-batch-to"
              />
            </Field>
            <Field
              label="每仓容量（件）"
              htmlFor="warehouse-batch-capacity"
              hint={`同一区域统一；改这里会同步 ${batch.zoneCode || 'A'} 区所有仓位`}
            >
              <Input
                id="warehouse-batch-capacity"
                type="number"
                min={1}
                max={999}
                value={batch.capacity}
                disabled={batching}
                onChange={(e) => setBatch((prev) => ({ ...prev, capacity: e.target.value }))}
                placeholder="10"
                data-testid="warehouse-batch-capacity"
              />
            </Field>
          </FormGrid>
          <div
            className={`mt-3 rounded-md px-3 py-2 text-xs ${
              batchPreview && 'error' in batchPreview
                ? 'bg-red-50 text-red-700'
                : 'bg-neutral-50 text-neutral-600'
            }`}
            data-testid="warehouse-batch-preview"
          >
            {batchPreview
              ? 'error' in batchPreview
                ? batchPreview.error
                : `将生成 ${batchPreview.fromCode} ~ ${batchPreview.toCode}，共 ${batchPreview.total} 个${
                    batchPreview.existing > 0 ? `；其中 ${batchPreview.existing} 个已存在，将跳过` : ''
                  }`
              : '请填写 1~9999 的数字区间'}
          </div>
        </FormPanel>
      </Modal>

      <Modal
        open={deleteTarget !== null}
        onClose={() => {
          if (!deleting) setDeleteTarget(null)
        }}
        title="删除仓位"
        width={420}
        closable={!deleting}
        maskClosable={!deleting}
        footer={
          <>
            <Button variant="secondary" onClick={() => setDeleteTarget(null)} disabled={deleting}>
              取消
            </Button>
            <Button
              variant="danger"
              onClick={() => void confirmDelete()}
              loading={deleting}
              data-testid="warehouse-location-delete-confirm"
            >
              删除
            </Button>
          </>
        }
      >
        <p className="text-sm text-neutral-700">
          删除仓位{' '}
          <span className="font-mono font-semibold">{deleteTarget?.binCode}</span>？
        </p>
        <p className="mt-1 text-xs leading-5 text-neutral-500">
          仅空闲仓位可删；已经生成的单据仍会显示原来的仓位号，不受影响。
        </p>
      </Modal>
    </div>
  )
}
