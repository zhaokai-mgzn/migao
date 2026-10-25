'use client'

import { useCallback, useEffect, useState } from 'react'
import { Plus } from 'lucide-react'
import { toast } from 'sonner'
import {
  Button,
  EmptyState,
  Input,
  Modal,
  PageCard,
  RowActionLink,
  Table,
  type TableColumn,
} from '@/components/ui'
import FormPanel, { Field, FormGrid } from '@/components/ui/FormPanel'
import ListLoadError from '@/components/common/ListLoadError'
import { finishedGoodsApi } from '@/lib/api'
import type { WarehouseLocation } from '@/types'

/**
 * 成品仓仓位管理（issue #7785）—— 出库单页的第三个视图。
 *
 * ## 为什么需要它
 *
 * 仓位号此前是「打包时系统自动生」的（`A-01` 起顺延），商家既不能按现场货架预置仓号，
 * 也清不掉废号。这里把仓位当作**主数据**来管：新建 / 编辑 / 启停 / 删除。
 *
 * ## 口径（服务端是唯一裁判，前端只做形态）
 *
 * - 仓位号租户内唯一、统一大写；占用中（有在库成品）**不能改号 / 删除**（在库行与已贴标签认这个号）；
 * - 停用只影响**后续自动分配**，已占用库存不受影响，可重新启用；
 * - 删除是软删，历史单据的仓位号快照不动；
 * - 自动分配口径不变：优先复用最小空闲号，全占满才新增。
 *
 * ## 边界（照实登记）
 *
 * - 不做「把在库成品从 A-01 挪到 A-02」（仓位随打包分配、随发货释放）；
 * - 不做批量建号 / 容量 / 货架层级（自动分配已覆盖按需建号）。
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
  const [form, setForm] = useState({ binCode: '', zoneCode: 'A', zoneName: '成品区', remark: '' })
  const [saving, setSaving] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<WarehouseLocation | null>(null)
  const [deleting, setDeleting] = useState(false)

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

  const openCreate = () => {
    setEditing(null)
    setForm({ binCode: '', zoneCode: 'A', zoneName: '成品区', remark: '' })
    setFormOpen(true)
  }

  const openEdit = (row: WarehouseLocation) => {
    setEditing(row)
    setForm({
      binCode: row.binCode,
      zoneCode: row.zoneCode,
      zoneName: row.zoneName,
      remark: row.remark || '',
    })
    setFormOpen(true)
  }

  const closeForm = () => {
    if (saving) return
    setFormOpen(false)
    setEditing(null)
  }

  const submit = async () => {
    const binCode = form.binCode.trim()
    if (!binCode) {
      toast.error('请填写仓位号（如 A-01）')
      return
    }
    setSaving(true)
    try {
      const payload = {
        binCode,
        zoneCode: form.zoneCode.trim() || undefined,
        zoneName: form.zoneName.trim() || undefined,
        remark: form.remark,
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
      key: 'state',
      title: '状态',
      render: (row) => {
        // 只读状态用「点 + 文字」陈述，不做成孤立状态徽标（#6588：状态该由控件本体表达）
        const state =
          row.status === 'inactive'
            ? { label: '已停用', dot: 'bg-neutral-400', text: 'text-neutral-500' }
            : row.occupied
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
      render: (row) =>
        canWrite ? (
          <div className="flex items-center gap-3 whitespace-nowrap">
            <RowActionLink
              onClick={() => openEdit(row)}
              data-testid={`warehouse-location-edit-${row.id}`}
            >
              编辑
            </RowActionLink>
            <RowActionLink
              onClick={() => void toggleStatus(row)}
              data-testid={`warehouse-location-toggle-${row.id}`}
            >
              {row.status === 'active' ? '停用' : '启用'}
            </RowActionLink>
            <button
              type="button"
              data-testid={`warehouse-location-delete-${row.id}`}
              disabled={row.occupied}
              title={row.occupied ? '占用中的仓位不能删除：先发货或撤销打包释放' : undefined}
              onClick={() => setDeleteTarget(row)}
              className={
                row.occupied
                  ? 'text-neutral-400 cursor-not-allowed'
                  : 'text-red-600 hover:text-red-700 hover:underline transition-colors'
              }
            >
              删除
            </button>
          </div>
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
              {'打包时优先复用空闲仓位，占满才按序号新增。可按现场货架建号、改备注或停用；占用中的仓位不能改号或删除。'}
            </p>
          </div>
          {canWrite && rows.length > 0 && (
            <Button
              variant="secondary"
              size="sm"
              icon={<Plus className="h-4 w-4" />}
              onClick={openCreate}
              data-testid="warehouse-location-create"
            >
              新建仓位
            </Button>
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
            description="打包时会自动建 A-01…；也可以先按货架建号。"
            testId="warehouse-locations-empty"
            action={
              canWrite ? (
                <Button
                  variant="secondary"
                  size="sm"
                  icon={<Plus className="h-4 w-4" />}
                  onClick={openCreate}
                  data-testid="warehouse-location-create-empty"
                >
                  新建仓位
                </Button>
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
          hint="仓位号统一大写，用字母 / 数字 / 短横线（如 A-01），同租户唯一。"
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
