'use client'

import { useEffect, useState, useCallback } from 'react'
import { Plus, Pencil, Trash2, Send, Archive } from 'lucide-react'
import { toast } from 'sonner'
import { knowledgeApi } from '@/lib/api'
import { Table, Pagination, Modal, Button, Badge, SearchBar } from '@/components/ui'
import type { TableColumn } from '@/components/ui'
import type { KnowledgeCard, KnowledgeCardStatus, KnowledgeCandidate, KnowledgeTemplateInfo } from '@/types'
import DateTimeCell from '@/components/common/DateTimeCell'
import { cn } from '@/lib/utils'

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

  // ===== 待确认队列 / 行业模板 / 提炼（LLM WIKI P3/P5/P6）=====
  const [activeTab, setActiveTab] = useState<'cards' | 'candidates' | 'templates'>('cards')
  const [candidates, setCandidates] = useState<KnowledgeCandidate[]>([])
  const [candidatesTotal, setCandidatesTotal] = useState(0)
  const [pendingCount, setPendingCount] = useState(0)
  const [templates, setTemplates] = useState<KnowledgeTemplateInfo[]>([])
  const [distilling, setDistilling] = useState(false)
  const [docModalOpen, setDocModalOpen] = useState(false)
  const [docForm, setDocForm] = useState({ title: '', content: '' })
  const [applying, setApplying] = useState('')

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

  const loadCandidates = useCallback(async () => {
    try {
      const [list, count] = await Promise.all([
        knowledgeApi.getCandidates({ status: 'pending', page: 1, size: 20 }),
        knowledgeApi.getPendingCount(),
      ])
      setCandidates(list.data?.data?.items ?? [])
      setCandidatesTotal(list.data?.data?.total ?? 0)
      setPendingCount(count.data?.data?.pending ?? 0)
    } catch {
      toast.error('加载待确认队列失败')
    }
  }, [])

  useEffect(() => {
    if (activeTab === 'candidates') loadCandidates()
    if (activeTab === 'templates') loadTemplates()
  }, [activeTab]) // eslint-disable-line react-hooks/exhaustive-deps

  const loadTemplates = async () => {
    try {
      const res = await knowledgeApi.getTemplates()
      setTemplates(res.data?.data ?? [])
    } catch {
      toast.error('加载行业模板失败')
    }
  }

  const adoptCandidate = async (candidate: KnowledgeCandidate) => {
    try {
      await knowledgeApi.adoptCandidate(candidate.id)
      toast.success('已采纳，知识卡片已发布')
      // 跳转「知识卡片」Tab 并刷新列表，让采纳结果立即可见可编辑（#3070）
      setActiveTab('cards')
      setKeyword('')
      setCategory('')
      setStatusFilter('')
      setCurrent(1)
      loadEntries()
      loadCandidates()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '采纳失败')
    }
  }

  const rejectCandidate = async (candidate: KnowledgeCandidate) => {
    try {
      await knowledgeApi.rejectCandidate(candidate.id, '商家拒绝')
      toast.success('已拒绝')
      loadCandidates()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '拒绝失败')
    }
  }

  const applyTemplate = async (templateId: string) => {
    setApplying(templateId)
    try {
      const res = await knowledgeApi.applyTemplate(templateId)
      toast.success(`模板已套用：新增 ${res.data?.data?.created ?? 0} 条，跳过 ${res.data?.data?.skipped ?? 0} 条`)
      // 跳转「知识卡片」Tab 并重置筛选刷新列表，套用出的卡片立即可见可编辑（#3070）
      setActiveTab('cards')
      setKeyword('')
      setCategory('')
      setStatusFilter('')
      setCurrent(1)
      loadEntries()
      loadTemplates()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '套用失败')
    } finally {
      setApplying('')
    }
  }

  const triggerConversationDistill = async () => {
    setDistilling(true)
    try {
      const res = await knowledgeApi.distillConversations(24)
      toast.success(`会话提炼完成：候选 ${res.data?.data?.candidates ?? 0} 条（新增 ${res.data?.data?.created ?? 0}）`)
      loadCandidates()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '会话提炼失败')
    } finally {
      setDistilling(false)
    }
  }

  const submitDocumentDistill = async () => {
    if (docForm.content.trim().length < 50) {
      toast.error('文档内容过短（至少 50 字）')
      return
    }
    setDistilling(true)
    try {
      const res = await knowledgeApi.distillDocument({
        title: docForm.title.trim() || undefined,
        content: docForm.content,
      })
      toast.success(`文档提炼完成：候选 ${res.data?.data?.candidates ?? 0} 条（新增 ${res.data?.data?.created ?? 0}）`)
      setDocModalOpen(false)
      setDocForm({ title: '', content: '' })
      loadCandidates()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '文档提炼失败')
    } finally {
      setDistilling(false)
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
    <div className="p-6 space-y-4">
      {/* 页面标题（与全局产品样式对齐） */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-neutral-900">知识库</h1>
          <p className="text-sm text-neutral-500 mt-1">LLM WIKI 知识卡片管理 — 发布后的知识卡片将优先用于 AI 客服知识问答</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" onClick={triggerConversationDistill} disabled={distilling}>
            {distilling ? '提炼中…' : '会话提炼'}
          </Button>
          <Button variant="secondary" size="sm" onClick={() => setDocModalOpen(true)}>文档提炼</Button>
          <Button onClick={openCreate}>
            <Plus className="h-4 w-4" /> 新建知识卡片
          </Button>
        </div>
      </div>

      {/* Tab + 内容卡片（与订单/客户页同构：border 卡片内 Tab 栏 + 内容） */}
      <div className="bg-white rounded-lg border border-neutral-200">
        {/* Tab 栏 */}
        <div className="flex items-center gap-6 px-5 pt-3 border-b border-neutral-200 overflow-x-auto">
          {([
            { key: 'cards', label: '知识卡片' },
            { key: 'candidates', label: pendingCount > 0 ? `待确认 (${pendingCount})` : '待确认' },
            { key: 'templates', label: '行业模板' },
          ] as const).map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={cn(
                'relative pb-3 text-sm whitespace-nowrap transition-colors',
                activeTab === tab.key ? 'text-primary-600 font-medium' : 'text-neutral-600 hover:text-neutral-900'
              )}
            >
              {tab.label}
              {activeTab === tab.key && (
                <span className="absolute left-0 right-0 -bottom-px h-0.5 bg-primary-600 rounded-full" />
              )}
            </button>
          ))}
        </div>

        {activeTab === 'cards' && (
          <div className="p-5 space-y-4">
            <SearchBar
              fields={[
                { key: 'keyword', label: '关键词', type: 'input', placeholder: '搜索标题 / 关键词 / 常见问法 / 回答内容' },
              ]}
              onSearch={(values) => { setKeyword(values.keyword ?? ''); setCurrent(1); loadEntries() }}
              onReset={() => { setKeyword(''); setCurrent(1); loadEntries() }}
            />

            <div className="flex items-center gap-2">
              <select
                className="h-9 px-3 rounded border border-neutral-300 bg-white text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                value={category}
                onChange={(e) => { setCategory(e.target.value); setCurrent(1) }}
              >
                <option value="">全部分类</option>
                {CATEGORY_OPTIONS.map((c) => (
                  <option key={c.value} value={c.value}>{c.label}</option>
                ))}
              </select>
              <select
                className="h-9 px-3 rounded border border-neutral-300 bg-white text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
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
          </div>
        )}

      {/* ===== 待确认队列（LLM WIKI P5）===== */}
      {activeTab === 'candidates' && (
        <div className="p-5 space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-sm text-neutral-500">AI 从客服会话/文档中提炼的候选知识卡片，采纳后立即生效（AI 只产生候选，发布权在您）</p>
            <Button size="sm" variant="secondary" onClick={triggerConversationDistill} disabled={distilling}>
              {distilling ? '提炼中…' : '重新提炼会话'}
            </Button>
          </div>
          <div className="divide-y">
            {candidates.length === 0 && (
              <p className="py-4 text-sm text-neutral-500">暂无待确认候选。点击「会话提炼」或「文档提炼」让 AI 从客服会话/资料中提炼知识。</p>
            )}
            {candidates.map((c) => (
              <div key={c.id} className="py-3 flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{c.suggestedTitle}</span>
                    <Badge variant={c.sourceType === 'document' ? 'info' : 'warning'}>
                      {c.sourceType === 'document' ? '文档提炼' : '会话提炼'}
                    </Badge>
                    {c.confidence != null && (
                      <span className="text-xs text-neutral-500">置信度 {(Number(c.confidence) * 100).toFixed(0)}%</span>
                    )}
                  </div>
                  <p className="text-sm text-neutral-500 mt-1 line-clamp-2">{c.suggestedAnswer}</p>
                  {c.evidence && <p className="text-xs text-neutral-500/70 mt-1">依据：{c.evidence}</p>}
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <Button size="sm" onClick={() => adoptCandidate(c)}>采纳</Button>
                  <Button size="sm" variant="ghost" onClick={() => rejectCandidate(c)}>拒绝</Button>
                </div>
              </div>
            ))}
            {candidatesTotal > candidates.length && (
              <p className="pt-3 text-xs text-neutral-500">共 {candidatesTotal} 条待确认（仅展示最近 20 条）</p>
            )}
          </div>
        </div>
      )}

      {/* ===== 行业模板（LLM WIKI P3）===== */}
      {activeTab === 'templates' && (
        <div className="p-5 space-y-3">
          <p className="text-sm text-neutral-500">平台预置行业知识模板，一键套用自动获得该行业的预置知识卡片（可编辑）</p>
          <div className="divide-y">
            {templates.length === 0 && <p className="py-4 text-sm text-neutral-500">暂无可用模板</p>}
            {templates.map((t) => (
              <div key={t.templateId} className="py-3 flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{t.name}</span>
                    <Badge variant="info">v{t.version}</Badge>
                    <span className="text-xs text-neutral-500">{t.entryCount} 条预置知识卡片</span>
                  </div>
                  {t.description && <p className="text-sm text-neutral-500 mt-1">{t.description}</p>}
                </div>
                <Button size="sm" onClick={() => applyTemplate(t.templateId)} disabled={applying === t.templateId}>
                  {applying === t.templateId ? '套用中…' : '一键套用'}
                </Button>
              </div>
            ))}
          </div>
        </div>
      )}
      </div>

      {/* 新建/编辑模态框 */}
      <Modal open={editorOpen} onClose={() => setEditorOpen(false)} title={editing ? '编辑知识卡片' : '新建知识卡片'}>
        <div className="space-y-3">
          <div>
            <label className="text-sm font-medium">标题 <span className="text-red-500">*</span></label>
            <input
              className="mt-1 w-full h-9 px-3 rounded border border-neutral-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              placeholder="如：雪尼尔面料会起球吗"
            />
            {formErrors.title && <p className="mt-1 text-xs text-red-500">{formErrors.title}</p>}
          </div>
          <div>
            <label className="text-sm font-medium">分类</label>
            <select
              className="mt-1 w-full h-9 px-3 rounded border border-neutral-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
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
              className="mt-1 w-full h-9 px-3 rounded border border-neutral-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
              value={form.question}
              onChange={(e) => setForm({ ...form, question: e.target.value })}
              placeholder="顾客可能的问法（用于检索命中）"
            />
          </div>
          <div>
            <label className="text-sm font-medium">标准回答 <span className="text-red-500">*</span></label>
            <textarea
              className="mt-1 w-full rounded border border-neutral-300 px-3 py-2 text-sm min-h-[120px] focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
              value={form.answer}
              onChange={(e) => setForm({ ...form, answer: e.target.value })}
              placeholder="AI 客服将基于此内容回答"
            />
            {formErrors.answer && <p className="mt-1 text-xs text-red-500">{formErrors.answer}</p>}
          </div>
          <div>
            <label className="text-sm font-medium">关键词（逗号分隔）</label>
            <input
              className="mt-1 w-full h-9 px-3 rounded border border-neutral-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
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

      {/* 文档提炼（LLM WIKI P6） */}
      <Modal open={docModalOpen} onClose={() => setDocModalOpen(false)} title="文档提炼">
        <div className="space-y-3">
          <div>
            <label className="text-sm font-medium">文档标题</label>
            <input
              className="mt-1 w-full h-9 px-3 rounded border border-neutral-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
              value={docForm.title}
              onChange={(e) => setDocForm({ ...docForm, title: e.target.value })}
              placeholder="如：面料手册 / 价格表说明"
            />
          </div>
          <div>
            <label className="text-sm font-medium">文档内容 <span className="text-red-500">*</span>（至少 50 字）</label>
            <textarea
              className="mt-1 w-full rounded border border-neutral-300 px-3 py-2 text-sm min-h-[160px] focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
              value={docForm.content}
              onChange={(e) => setDocForm({ ...docForm, content: e.target.value })}
              placeholder="粘贴面料说明、产品资料、售后政策等文本内容，AI 将提炼为知识卡片候选"
            />
          </div>
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setDocModalOpen(false)}>取消</Button>
          <Button onClick={submitDocumentDistill} disabled={distilling}>{distilling ? '提炼中…' : '开始提炼'}</Button>
        </div>
      </Modal>
    </div>
  )
}
