'use client'

import { useEffect, useState, useCallback, useRef } from 'react'
import { Upload, Trash2, FileText, RefreshCw, Search, Sparkles } from 'lucide-react'
import { toast } from 'sonner'
import { knowledgeApi } from '@/lib/api'
import { Table, Pagination, Modal, Button, Badge, SearchBar } from '@/components/ui'
import type { TableColumn } from '@/components/ui'
import type { KnowledgeDocument, KnowledgeDocumentUploadForm, KnowledgeSearchResult } from '@/types'
import DateTimeCell from '@/components/common/DateTimeCell'

export default function KnowledgePage() {
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([])
  const [loading, setLoading] = useState(false)
  const [total, setTotal] = useState(0)
  const [current, setCurrent] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [searchParams, setSearchParams] = useState({
    keyword: '',
    type: '',
    status: '',
  })

  // 上传模态框状态
  const [uploadModalOpen, setUploadModalOpen] = useState(false)
  const [uploadForm, setUploadForm] = useState<KnowledgeDocumentUploadForm>({
    name: '',
    type: 'faq',
    description: '',
  })
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [formErrors, setFormErrors] = useState<Record<string, string>>({})
  const [isDragging, setIsDragging] = useState(false)

  // 删除确认状态
  const [deleteModalOpen, setDeleteModalOpen] = useState(false)
  const [deletingDoc, setDeletingDoc] = useState<KnowledgeDocument | null>(null)

  // 搜索测试状态
  const [searchTestOpen, setSearchTestOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<KnowledgeSearchResult[]>([])
  const [searching, setSearching] = useState(false)

  // 加载数据
  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      // Mock 数据
      setDocuments([
        {
          id: '1',
          name: '窗帘常见问题 FAQ',
          type: 'faq',
          chunkCount: 24,
          status: 'processed',
          description: '客户常见咨询问题汇总',
          fileSize: 125000,
          uploadedAt: '2026-04-15T10:30:00',
        },
        {
          id: '2',
          name: '产品目录 2026',
          type: 'product',
          chunkCount: 156,
          status: 'processed',
          description: '全系列产品详细介绍',
          fileSize: 2340000,
          uploadedAt: '2026-04-14T16:45:00',
        },
        {
          id: '3',
          name: '窗帘尺寸测量指南',
          type: 'guide',
          chunkCount: 12,
          status: 'processing',
          description: '如何正确测量窗帘尺寸',
          fileSize: 89000,
          uploadedAt: '2026-04-18T09:20:00',
        },
        {
          id: '4',
          name: '安装服务说明',
          type: 'guide',
          chunkCount: 0,
          status: 'failed',
          description: '上门安装服务流程说明',
          fileSize: 45000,
          uploadedAt: '2026-04-10T14:00:00',
        },
      ])
      setTotal(4)
    } catch (error) {
      console.error('加载数据失败:', error)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadData()
  }, [loadData])

  // 搜索
  const handleSearch = (values: Record<string, string>) => {
    setCurrent(1)
    setSearchParams({
      keyword: values.keyword || '',
      type: values.type || '',
      status: values.status || '',
    })
  }

  const handleReset = () => {
    setCurrent(1)
    setSearchParams({ keyword: '', type: '', status: '' })
  }

  // 打开上传模态框
  const openUploadModal = () => {
    setUploadForm({ name: '', type: 'faq', description: '' })
    setSelectedFile(null)
    setFormErrors({})
    setUploadProgress(0)
    setUploadModalOpen(true)
  }

  // 验证上传表单
  const validateUploadForm = (): boolean => {
    const errors: Record<string, string> = {}
    if (!uploadForm.name.trim()) errors.name = '请输入文档名称'
    if (!selectedFile) errors.file = '请选择要上传的文件'
    setFormErrors(errors)
    return Object.keys(errors).length === 0
  }

  // 处理文件选择
  const handleFileSelect = (file: File) => {
    const allowedTypes = ['.pdf', '.doc', '.docx', '.txt', '.md']
    const ext = '.' + file.name.split('.').pop()?.toLowerCase()
    if (!allowedTypes.includes(ext)) {
      toast.error('不支持的文件类型，请上传 PDF、Word、TXT 或 Markdown 文件')
      return
    }
    setSelectedFile(file)
    if (!uploadForm.name) {
      setUploadForm({ ...uploadForm, name: file.name.replace(/\.[^/.]+$/, '') })
    }
    setFormErrors((prev) => ({ ...prev, file: '' }))
  }

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) handleFileSelect(file)
  }

  // 拖拽上传
  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
    const file = e.dataTransfer.files?.[0]
    if (file) handleFileSelect(file)
  }

  // 处理上传（带进度模拟）
  const handleUpload = async () => {
    if (!validateUploadForm()) return

    setUploading(true)
    setUploadProgress(0)
    try {
      // 模拟上传进度
      const progressInterval = setInterval(() => {
        setUploadProgress((prev) => {
          if (prev >= 90) {
            clearInterval(progressInterval)
            return 90
          }
          return prev + Math.random() * 15
        })
      }, 300)

      await new Promise((resolve) => setTimeout(resolve, 2000))
      clearInterval(progressInterval)
      setUploadProgress(100)

      toast.success('文档上传成功')
      setTimeout(() => {
        setUploadModalOpen(false)
        loadData()
      }, 500)
    } catch (error) {
      toast.error('上传失败')
    } finally {
      setUploading(false)
    }
  }

  // 重新同步
  const handleResync = async (doc: KnowledgeDocument) => {
    try {
      // await knowledgeApi.resyncDocument(doc.id)
      toast.success(`已触发文档「${doc.name}」重新同步`)
      loadData()
    } catch (error) {
      toast.error('重新同步失败')
    }
  }

  // 删除文档
  const handleDelete = (doc: KnowledgeDocument) => {
    setDeletingDoc(doc)
    setDeleteModalOpen(true)
  }

  const confirmDelete = async () => {
    if (!deletingDoc) return
    try {
      await new Promise((resolve) => setTimeout(resolve, 500))
      toast.success('删除成功')
      loadData()
    } catch (error) {
      toast.error('删除失败')
    } finally {
      setDeleteModalOpen(false)
      setDeletingDoc(null)
    }
  }

  // 搜索测试
  const handleSearchTest = async () => {
    if (!searchQuery.trim()) {
      toast.error('请输入搜索内容')
      return
    }
    setSearching(true)
    try {
      // Mock 搜索结果
      await new Promise((resolve) => setTimeout(resolve, 800))
      setSearchResults([
        {
          chunkId: 'chunk_001',
          content: '遮光窗帘布采用高精密织造工艺，遮光率可达 85%-95%。适用于卧室、会议室等需要遮光的场景。加工方式可选：打孔加工（¥5/个）、挂钩加工（¥3/个）。',
          score: 0.92,
          source: { documentId: 'doc_001', title: '遮光窗帘布 - 产品说明', docType: 'product_info' },
        },
        {
          chunkId: 'chunk_002',
          content: '窗帘尺寸测量方法：1. 测量窗户宽度，左右各加 15-20cm；2. 测量窗户高度，上方加 10cm，下方根据需要确定长度。',
          score: 0.78,
          source: { documentId: 'doc_002', title: '窗帘尺寸测量指南', docType: 'guide' },
        },
        {
          chunkId: 'chunk_003',
          content: '常见问题：Q: 窗帘可以机洗吗？A: 建议手洗或干洗，机洗可能导致面料变形。',
          score: 0.65,
          source: { documentId: 'doc_003', title: '窗帘常见问题 FAQ', docType: 'faq' },
        },
      ])
    } catch (error) {
      toast.error('搜索失败')
    } finally {
      setSearching(false)
    }
  }

  // 格式化文件大小
  const formatFileSize = (bytes?: number) => {
    if (!bytes) return '-'
    if (bytes < 1024) return bytes + ' B'
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
  }

  const getTypeLabel = (type: string) => {
    const labels: Record<string, string> = { faq: 'FAQ', product: '产品说明', guide: '尺寸指南' }
    return labels[type] || type
  }

  const getStatusBadge = (status: string) => {
    const config: Record<string, { variant: 'success' | 'warning' | 'error'; label: string }> = {
      processed: { variant: 'success', label: '已同步' },
      processing: { variant: 'warning', label: '同步中' },
      failed: { variant: 'error', label: '未同步' },
    }
    const { variant, label } = config[status] || { variant: 'default' as const, label: status }
    return <Badge variant={variant}>{label}</Badge>
  }

  // 表格列
  const columns: TableColumn<KnowledgeDocument>[] = [
    {
      key: 'name',
      title: '文档名称',
      render: (record) => (
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-blue-50 rounded-lg flex items-center justify-center">
            <FileText className="w-5 h-5 text-blue-600" />
          </div>
          <div>
            <div className="font-medium text-gray-900">{record.name}</div>
            {record.description && (
              <div className="text-xs text-gray-500">{record.description}</div>
            )}
          </div>
        </div>
      ),
    },
    {
      key: 'type',
      title: '类型',
      width: '120px',
      render: (record) => <Badge variant="info">{getTypeLabel(record.type)}</Badge>,
    },
    {
      key: 'fileSize',
      title: '文件大小',
      width: '100px',
      render: (record) => <span className="text-gray-600">{formatFileSize(record.fileSize)}</span>,
    },
    {
      key: 'chunkCount',
      title: '分块数',
      width: '80px',
      align: 'center',
      render: (record) => <span className="font-medium">{record.chunkCount}</span>,
    },
    {
      key: 'uploadedAt',
      title: '更新时间',
      width: '160px',
      render: (record) => <DateTimeCell value={record.uploadedAt} />,
    },
    {
      key: 'status',
      title: '状态',
      width: '100px',
      render: (record) => getStatusBadge(record.status),
    },
    {
      key: 'action',
      title: '操作',
      width: '140px',
      align: 'center',
      render: (record) => (
        <div className="flex items-center justify-center gap-2">
          <button
            onClick={(e) => { e.stopPropagation(); handleResync(record) }}
            className="p-1.5 text-blue-600 hover:bg-blue-50 rounded transition-colors"
            title="重新同步"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
          <button
            onClick={(e) => { e.stopPropagation(); handleDelete(record) }}
            className="p-1.5 text-red-600 hover:bg-red-50 rounded transition-colors"
            title="删除"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      ),
    },
  ]

  const searchFields = [
    { key: 'keyword', label: '关键词', type: 'input' as const, placeholder: '请输入文档名称' },
    {
      key: 'type', label: '类型', type: 'select' as const, placeholder: '请选择类型',
      options: [
        { value: '', label: '全部' },
        { value: 'faq', label: 'FAQ' },
        { value: 'product', label: '产品说明' },
        { value: 'guide', label: '尺寸指南' },
      ],
    },
    {
      key: 'status', label: '状态', type: 'select' as const, placeholder: '请选择状态',
      options: [
        { value: '', label: '全部' },
        { value: 'processed', label: '已同步' },
        { value: 'processing', label: '同步中' },
        { value: 'failed', label: '未同步' },
      ],
    },
  ]

  return (
    <div className="p-6">
      {/* 页面标题 */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">知识库管理</h1>
          <p className="text-sm text-gray-500 mt-1">管理 AI 客服的知识库文档和问答</p>
        </div>
        <div className="flex items-center gap-3">
          <Button variant="secondary" onClick={() => setSearchTestOpen(true)}>
            <Sparkles className="w-4 h-4 mr-1.5" />
            搜索测试
          </Button>
          <Button onClick={openUploadModal}>
            <Upload className="w-4 h-4 mr-1.5" />
            上传文档
          </Button>
        </div>
      </div>

      {/* 搜索栏 */}
      <SearchBar fields={searchFields} onSearch={handleSearch} onReset={handleReset} loading={loading} className="mb-4" />

      {/* 数据表格 */}
      <div className="bg-white rounded-lg border border-gray-200">
        <Table columns={columns} dataSource={documents} loading={loading} rowKey="id" />
        <Pagination current={current} pageSize={pageSize} total={total} onChange={setCurrent} onPageSizeChange={setPageSize} />
      </div>

      {/* 上传文档模态框 */}
      <Modal
        open={uploadModalOpen}
        onClose={() => setUploadModalOpen(false)}
        title="上传文档"
        footer={
          <>
            <Button variant="secondary" onClick={() => setUploadModalOpen(false)}>取消</Button>
            <Button onClick={handleUpload} loading={uploading}>
              {uploading ? `上传中 ${Math.round(uploadProgress)}%` : '上传'}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">
              文档名称 <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              className={`w-full h-9 px-3 rounded border text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 ${
                formErrors.name ? 'border-red-500' : 'border-gray-300'
              }`}
              placeholder="请输入文档名称"
              value={uploadForm.name}
              onChange={(e) => setUploadForm({ ...uploadForm, name: e.target.value })}
            />
            {formErrors.name && <p className="mt-1 text-sm text-red-600">{formErrors.name}</p>}
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">
              文档类型 <span className="text-red-500">*</span>
            </label>
            <select
              className="w-full h-9 px-3 rounded border border-gray-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
              value={uploadForm.type}
              onChange={(e) => setUploadForm({ ...uploadForm, type: e.target.value as 'faq' | 'product' | 'guide' })}
            >
              <option value="faq">FAQ</option>
              <option value="product">产品说明</option>
              <option value="guide">尺寸指南</option>
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">
              选择文件 <span className="text-red-500">*</span>
            </label>
            <div
              className={`border-2 border-dashed rounded-lg p-6 text-center transition-colors ${
                isDragging
                  ? 'border-primary-500 bg-primary-50'
                  : formErrors.file
                  ? 'border-red-300 bg-red-50'
                  : 'border-gray-300 hover:border-primary-500'
              }`}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
            >
              <input
                type="file"
                id="file-upload"
                className="hidden"
                accept=".pdf,.doc,.docx,.txt,.md"
                onChange={handleFileChange}
              />
              <label htmlFor="file-upload" className="cursor-pointer flex flex-col items-center">
                <Upload className="w-8 h-8 text-gray-400 mb-2" />
                <span className="text-sm text-gray-600">
                  {selectedFile ? selectedFile.name : isDragging ? '释放文件以上传' : '点击选择或拖拽文件到此处'}
                </span>
                <span className="text-xs text-gray-400 mt-1">
                  支持 PDF、Word、TXT、Markdown 格式
                </span>
                {selectedFile && (
                  <span className="text-xs text-primary-600 mt-1">
                    {formatFileSize(selectedFile.size)}
                  </span>
                )}
              </label>
            </div>
            {formErrors.file && <p className="mt-1 text-sm text-red-600">{formErrors.file}</p>}
          </div>

          {/* 上传进度条 */}
          {uploading && (
            <div className="space-y-1">
              <div className="flex justify-between text-xs text-gray-500">
                <span>上传进度</span>
                <span>{Math.round(uploadProgress)}%</span>
              </div>
              <div className="w-full bg-gray-200 rounded-full h-2">
                <div
                  className="bg-primary-600 h-2 rounded-full transition-all duration-300"
                  style={{ width: `${uploadProgress}%` }}
                />
              </div>
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">描述</label>
            <textarea
              rows={3}
              className="w-full px-3 py-2 rounded border border-gray-300 text-sm placeholder:text-gray-400 focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 resize-none"
              placeholder="请输入文档描述（可选）"
              value={uploadForm.description}
              onChange={(e) => setUploadForm({ ...uploadForm, description: e.target.value })}
            />
          </div>
        </div>
      </Modal>

      {/* 删除确认模态框 */}
      <Modal
        open={deleteModalOpen}
        onClose={() => setDeleteModalOpen(false)}
        title="确认删除"
        footer={
          <>
            <Button variant="secondary" onClick={() => setDeleteModalOpen(false)}>取消</Button>
            <Button variant="danger" onClick={confirmDelete}>确认删除</Button>
          </>
        }
      >
        <p className="text-gray-600">
          确定要删除文档 <span className="font-medium text-gray-900">{deletingDoc?.name}</span> 吗？此操作不可恢复。
        </p>
      </Modal>

      {/* 搜索测试模态框 */}
      <Modal
        open={searchTestOpen}
        onClose={() => setSearchTestOpen(false)}
        title="知识库搜索测试"
        width={700}
        footer={
          <Button variant="secondary" onClick={() => setSearchTestOpen(false)}>关闭</Button>
        }
      >
        <div className="space-y-4">
          <div className="flex gap-3">
            <input
              type="text"
              className="flex-1 h-9 px-3 rounded border border-gray-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
              placeholder="输入搜索内容，测试 RAG 检索效果..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearchTest()}
            />
            <Button onClick={handleSearchTest} loading={searching}>
              <Search className="w-4 h-4 mr-1" />
              搜索
            </Button>
          </div>

          {searchResults.length > 0 && (
            <div className="space-y-3 max-h-[400px] overflow-y-auto">
              {searchResults.map((result, index) => (
                <div key={result.chunkId} className="border border-gray-200 rounded-lg p-4">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-medium text-gray-500">#{index + 1}</span>
                      <span className="text-sm font-medium text-gray-900">{result.source.title}</span>
                      <Badge variant="info">{result.source.docType}</Badge>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <span className="text-xs text-gray-500">相关度</span>
                      <span className={`text-sm font-bold ${
                        result.score >= 0.8 ? 'text-green-600' : result.score >= 0.6 ? 'text-amber-600' : 'text-gray-500'
                      }`}>
                        {(result.score * 100).toFixed(0)}%
                      </span>
                    </div>
                  </div>
                  <p className="text-sm text-gray-700 leading-relaxed">{result.content}</p>
                </div>
              ))}
            </div>
          )}

          {searchResults.length === 0 && !searching && searchQuery && (
            <div className="text-center py-8 text-gray-500 text-sm">
              暂无搜索结果，请尝试其他关键词
            </div>
          )}
        </div>
      </Modal>
    </div>
  )
}
