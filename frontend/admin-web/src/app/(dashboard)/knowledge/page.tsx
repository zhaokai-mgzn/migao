'use client'

import { useEffect, useState, useCallback } from 'react'
import { Plus, Pencil, Trash2, Send, Archive } from 'lucide-react'
import { toast } from 'sonner'
import { knowledgeApi } from '@/lib/api'
import { Table, Pagination, Modal, Button, Badge, SearchBar } from '@/components/ui'
import type { TableColumn } from '@/components/ui'
import type { KnowledgeCard, KnowledgeCardStatus } from '@/types'
import DateTimeCell from '@/components/common/DateTimeCell'

// 知识卡片状态 → 徽标（三端一致契约：draft/pending_review/published/archived）
const STATUS_META: Record<KnowledgeCardStatus, { label: string; variant: 'default' | 'warning' | 'success' | 'error' }> = {
  draft: { label: '草稿', variant: 'default' },
  pending_review: { label: '待审核', variant: 'warning' },
  published: { label: '已发布', variant: 'success' },
  archived: { label: '已归档', variant: 'error' },
}

// 知识卡片来源 → 徽标（template/product/config/conversation/document/manual）
const SOURCE_META: Record<string, { label: string; variant: 'default' | 'info' | 'warning' | 'success' }> = {
  template: { label: '模板', variant: 'info' },
  product: { label: '商品派生', variant: 'info' },
  config: { label: '配置', variant: 'info' },
  conversation: { label: '会话提炼', variant: 'warning' },
  document: { label: '文档提炼', variant: 'info' },
  manual: { label: '人工', variant: 'success' },
}

const CATEGORY_OPTIONS = [
  { value: 'faq', label: 'FAQ' },
  { value: 'product', label: '商品' },
  { value: 'measure', label: '测量' },
  { value: 'aftersale', label: '售后' },
  { value: 'config', label: '店铺配置' },
]

export default function KnowledgePage() {
  const [entries, setEntries] = useState<KnowledgeCard[]>([])
  const [loading, setLoading] = useState(false)
  const [total, setTotal] = useState(0)
  const [current, setCurrent] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [keyword, setKeyword] = useState('')
  const [category, setCategory] = useState('')
  const [statusFilter, setStatusFilter] = useState('')

  // 编辑模态框
  const [editorOpen, setEditorOpen] = useState(false)
  const [editing, setEditing] = useState<KnowledgeCard | null>(null)
  const [form, setForm] = useState({ title: '', category: 'faq', question: '', answer: '', keywords: '' })
  const [formErrors, setFormErrors] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)

  const [deleteTarget, setDeleteTarget] = useState<KnowledgeCard | null>(null)

  const loadEntries = useCallback(async () => {
    setLoading(true)
    try {
      const res = await knowledgeApi.getCards({
        page: current,
        size: pageSize,
        keyword: keyword || undefined,
        category: category || undefined,
        status: statusFilter || undefined,
      })
      setEntries(res.data?.data?.items ?? [])
      setTotal(res.data?.data?.total ?? 0)
    } catch {
      toast.error('加载知识卡片失败')
    } finally {
      setLoading(false)
    }
  }, [current, pageSize, keyword, category, statusFilter])

  useEffect(() => {
    loadEntries()
  }, [loadEntries])

  const openCreate = () => {
    setEditing(null)
    setForm({ title: '', category: 'faq', question: '', answer: '', keywords: '' })
    setFormErrors({})
    setEditorOpen(true)
  }

  const openEdit = (entry: KnowledgeCard) => {
    setEditing(entry)
    setForm({
      title: entry.title,
      category: entry.category ?? 'faq',
      question: entry.question ?? '',
      answer: entry.answer,
      keywords: entry.keywords ?? '',
    })
    setFormErrors({})
    setEditorOpen(true)
  }

  const saveEntry = async () => {
    const errors: Record<string, string> = {}
    if (!form.title.trim()) errors.title = '标题不能为空'
    if (!form.answer.trim()) errors.answer = '标准回答不能为空'
    setFormErrors(errors)
    if (Object.keys(errors).length > 0) return

    setSaving(true)
    try {
      const payload = {
        title: form.title.trim(),
        category: form.category,
        question: form.question.trim() || undefined,
        answer: form.answer,
        keywords: form.keywords.trim() || undefined,
      }
      if (editing) {
        await knowledgeApi.updateCard(editing.id, payload)
        toast.success('知识卡片已更新')
      } else {
        await knowledgeApi.createCard(payload)
        toast.success('知识卡片已创建（草稿）')
      }
      setEditorOpen(false)
      loadEntries()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const publishCard = async (entry: KnowledgeCard) => {
    try {
      await knowledgeApi.publishCard(entry.id)
      toast.success('知识卡片已发布')
      loadEntries()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '发布失败')
    }
  }

  const archiveCard = async (entry: KnowledgeCard) => {
    try {
      await knowledgeApi.archiveCard(entry.id)
      toast.success('知识卡片已归档')
      loadEntries()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '归档失败')
    }
  }

  const confirmDelete = async () => {
    if (!deleteTarget) return
    try {
      await knowledgeApi.deleteCard(deleteTarget.id)
      toast.success('知识卡片已删除')
      setDeleteTarget(null)
      loadEntries()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '删除失败')
    }
  }

  const columns: TableColumn<KnowledgeCard>[] = [
    {
      key: 'title',
      title: '知识卡片标题',
      render: (entry) => (
        <div className="min-w-[220px]">
          <div className="font-medium">{entry.title}</div>
          {entry.question && <div className="text-xs text-muted-foreground mt-0.5">常见问法：{entry.question}</div>}
        </div>
      ),
    },
    {
      key: 'category',
      title: '分类',
      width: '90px',
      render: (entry) => CATEGORY_OPTIONS.find((c) => c.value === entry.category)?.label ?? entry.category ?? '-',
    },
    {
      key: 'sourceType',
      title: '来源',
      width: '100px',
      render: (entry) => {
        const meta = SOURCE_META[entry.sourceType]
        return meta ? <Badge variant={meta.variant}>{meta.label}</Badge> : <span>-</span>
      },
    },
    {
      key: 'status',
      title: '状态',
      width: '90px',
      render: (entry) => {
        const meta = STATUS_META[entry.status as KnowledgeCardStatus]
        return meta ? <Badge variant={meta.variant}>{meta.label}</Badge> : <span>{entry.status}</span>
      },
    },
    {
      key: 'version',
      title: '版本',
      width: '60px',
      render: (entry) => `v${entry.version}`,
    },
    {
      key: 'updatedAt',
      title: '更新时间',
      width: '150px',
      render: (entry) => <DateTimeCell value={entry.updatedAt} />,
    },
    {
      key: 'actions',
      title: '操作',
      width: '180px',
      render: (entry) => (
        <div className="flex items-center gap-1">
          <Button size="sm" variant="ghost" onClick={() => openEdit(entry)}>
            <Pencil className="h-3.5 w-3.5" /> 编辑
          </Button>
          {entry.status === 'draft' || entry.status === 'pending_review' ? (
            <Button size="sm" variant="ghost" onClick={() => publishCard(entry)}>
              <Send className="h-3.5 w-3.5" /> 发布
            </Button>
          ) : entry.status === 'published' ? (
            <Button size="sm" variant="ghost" onClick={() => archiveCard(entry)}>
              <Archive className="h-3.5 w-3.5" /> 归档
            </Button>
          ) : null}
          <Button size="sm" variant="ghost" onClick={() => setDeleteTarget(entry)}>
            <Trash2 className="h-3.5 w-3.5" /> 删除
          </Button>
        </div>
      ),
    },
  ]

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold">知识卡片</h1>
          <p className="text-sm text-muted-foreground">LLM WIKI 知识卡片管理 — 发布后的知识卡片将优先用于 AI 客服知识问答</p>
        </div>
        <Button onClick={openCreate}>
          <Plus className="h-4 w-4" /> 新建知识卡片
        </Button>
      </div>

      <SearchBar
        fields={[
          { key: 'keyword', label: '关键词', type: 'input', placeholder: '搜索标题 / 关键词 / 常见问法 / 回答内容' },
        ]}
        onSearch={(values) => { setKeyword(values.keyword ?? ''); setCurrent(1); loadEntries() }}
        onReset={() => { setKeyword(''); setCurrent(1); loadEntries() }}
      />

      <div className="flex items-center gap-2">
        <select
          className="h-9 rounded-md border px-2 text-sm"
          value={category}
          onChange={(e) => { setCategory(e.target.value); setCurrent(1) }}
        >
          <option value="">全部分类</option>
          {CATEGORY_OPTIONS.map((c) => (
            <option key={c.value} value={c.value}>{c.label}</option>
          ))}
        </select>
        <select
          className="h-9 rounded-md border px-2 text-sm"
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value); setCurrent(1) }}
        >
          <option value="">全部状态</option>
          <option value="draft">草稿</option>
          <option value="pending_review">待审核</option>
          <option value="published">已发布</option>
          <option value="archived">已归档</option>
        </select>
      </div>

      <Table columns={columns} dataSource={entries} loading={loading} rowKey="id" emptyText="暂无知识卡片，点击「新建知识卡片」或从行业模板一键套用" />

      <Pagination
        current={current}
        pageSize={pageSize}
        total={total}
        onChange={(page) => { setCurrent(page) }}
      />

      {/* 新建/编辑模态框 */}
      <Modal open={editorOpen} onClose={() => setEditorOpen(false)} title={editing ? '编辑知识卡片' : '新建知识卡片'}>
        <div className="space-y-3">
          <div>
            <label className="text-sm font-medium">标题 <span className="text-red-500">*</span></label>
            <input
              className="mt-1 w-full rounded-md border px-3 py-2 text-sm"
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              placeholder="如：雪尼尔面料会起球吗"
            />
            {formErrors.title && <p className="mt-1 text-xs text-red-500">{formErrors.title}</p>}
          </div>
          <div>
            <label className="text-sm font-medium">分类</label>
            <select
              className="mt-1 w-full rounded-md border px-3 py-2 text-sm"
              value={form.category}
              onChange={(e) => setForm({ ...form, category: e.target.value })}
            >
              {CATEGORY_OPTIONS.map((c) => (
                <option key={c.value} value={c.value}>{c.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-sm font-medium">常见问法</label>
            <input
              className="mt-1 w-full rounded-md border px-3 py-2 text-sm"
              value={form.question}
              onChange={(e) => setForm({ ...form, question: e.target.value })}
              placeholder="顾客可能的问法（用于检索命中）"
            />
          </div>
          <div>
            <label className="text-sm font-medium">标准回答 <span className="text-red-500">*</span></label>
            <textarea
              className="mt-1 w-full rounded-md border px-3 py-2 text-sm min-h-[120px]"
              value={form.answer}
              onChange={(e) => setForm({ ...form, answer: e.target.value })}
              placeholder="AI 客服将基于此内容回答"
            />
            {formErrors.answer && <p className="mt-1 text-xs text-red-500">{formErrors.answer}</p>}
          </div>
          <div>
            <label className="text-sm font-medium">关键词（逗号分隔）</label>
            <input
              className="mt-1 w-full rounded-md border px-3 py-2 text-sm"
              value={form.keywords}
              onChange={(e) => setForm({ ...form, keywords: e.target.value })}
              placeholder="如：雪尼尔, 起球, 面料"
            />
          </div>
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setEditorOpen(false)}>取消</Button>
          <Button onClick={saveEntry} disabled={saving}>{saving ? '保存中…' : '保存'}</Button>
        </div>
      </Modal>

      {/* 删除确认 */}
      <Modal open={!!deleteTarget} onClose={() => setDeleteTarget(null)} title="删除知识卡片">
        <p className="text-sm">确认删除「{deleteTarget?.title}」？删除后不可恢复。</p>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setDeleteTarget(null)}>取消</Button>
          <Button variant="danger" onClick={confirmDelete}>删除</Button>
        </div>
      </Modal>
    </div>
  )
}
