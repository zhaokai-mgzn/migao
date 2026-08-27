'use client'

import { useState, useEffect, useCallback } from 'react'
import { Bot, MessageSquare, Save, Plus, Trash2, Edit3, X, Check, Zap } from 'lucide-react'
import { toast } from 'sonner'
import { Button, Badge } from '@/components/ui'
import { settingsApi, quickReplyApi } from '@/lib/api'
import type { AiConfig } from '@/types'
import type { QuickReplyTemplate } from '@/lib/api'

type ConfigTab = 'basic' | 'quick-replies'

const TABS: { key: ConfigTab; label: string; icon: typeof Bot }[] = [
  { key: 'basic', label: '基础设置', icon: Bot },
  { key: 'quick-replies', label: '快捷回复', icon: MessageSquare },
]

export default function ChatConfigPage() {
  const [activeTab, setActiveTab] = useState<ConfigTab>('basic')

  // ========== 基础设置 ==========
  const defaultAiConfig: AiConfig = {
    botName: '小布',
    greetingTemplate: '',
  }
  const [aiConfig, setAiConfig] = useState<AiConfig>(defaultAiConfig)
  const [savingAiConfig, setSavingAiConfig] = useState(false)
  const [loading, setLoading] = useState(false)

  const loadAiConfig = useCallback(async () => {
    setLoading(true)
    try {
      const res = await settingsApi.getAiConfig()
      if (res.data.data) {
        setAiConfig({ ...defaultAiConfig, ...res.data.data })
      }
    } catch (e) {
      toast.error('加载 AI 配置失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (activeTab === 'basic') loadAiConfig()
  }, [activeTab, loadAiConfig])

  const handleSaveAiConfig = async () => {
    if (!aiConfig.botName.trim()) {
      toast.error('请输入机器人名称')
      return
    }
    setSavingAiConfig(true)
    try {
      await settingsApi.updateAiConfig(aiConfig)
      toast.success('机器人配置已保存')
    } catch (e) {
      toast.error('保存失败')
    } finally {
      setSavingAiConfig(false)
    }
  }

  // ========== 快捷回复 ==========
  const [templates, setTemplates] = useState<QuickReplyTemplate[]>([])
  const [loadingTemplates, setLoadingTemplates] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editForm, setEditForm] = useState({ title: '', content: '', category: '' })
  const [savingTemplate, setSavingTemplate] = useState(false)
  const [showNewForm, setShowNewForm] = useState(false)
  const [newForm, setNewForm] = useState({ title: '', content: '', category: '通用' })

  const loadTemplates = useCallback(async () => {
    setLoadingTemplates(true)
    try {
      const res = await quickReplyApi.getTemplates({ page: 1, size: 100 })
      setTemplates(res.data.data?.items || [])
    } catch (e) {
      toast.error('加载快捷回复失败')
    } finally {
      setLoadingTemplates(false)
    }
  }, [])

  useEffect(() => {
    if (activeTab === 'quick-replies') loadTemplates()
  }, [activeTab, loadTemplates])

  const handleCreate = async () => {
    if (!newForm.title.trim() || !newForm.content.trim()) {
      toast.error('请输入标题和回复内容')
      return
    }
    setSavingTemplate(true)
    try {
      await quickReplyApi.createTemplate({
        title: newForm.title.trim(),
        content: newForm.content.trim(),
        category: newForm.category.trim() || '通用',
      })
      toast.success('快捷回复已创建')
      setNewForm({ title: '', content: '', category: '通用' })
      setShowNewForm(false)
      loadTemplates()
    } catch (e) {
      toast.error('创建失败')
    } finally {
      setSavingTemplate(false)
    }
  }

  const startEdit = (tpl: QuickReplyTemplate) => {
    setEditingId(tpl.id)
    setEditForm({ title: tpl.title, content: tpl.content, category: tpl.category })
  }

  const cancelEdit = () => {
    setEditingId(null)
    setEditForm({ title: '', content: '', category: '' })
  }

  const handleUpdate = async (id: string) => {
    if (!editForm.title.trim() || !editForm.content.trim()) {
      toast.error('请输入标题和回复内容')
      return
    }
    setSavingTemplate(true)
    try {
      await quickReplyApi.updateTemplate(id, {
        title: editForm.title.trim(),
        content: editForm.content.trim(),
        category: editForm.category.trim() || '通用',
      })
      toast.success('快捷回复已更新')
      cancelEdit()
      loadTemplates()
    } catch (e) {
      toast.error('更新失败')
    } finally {
      setSavingTemplate(false)
    }
  }

  const handleDelete = async (id: string, title: string) => {
    if (!confirm(`确定要删除快捷回复「${title}」吗？`)) return
    try {
      await quickReplyApi.deleteTemplate(id)
      toast.success('已删除')
      loadTemplates()
    } catch (e) {
      toast.error('删除失败')
    }
  }

  return (
    <div className="p-6">
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-gray-900">机器人设置</h1>
        <p className="text-sm text-gray-500 mt-1">配置小布机器人的名称、欢迎语和快捷回复</p>
      </div>

      <div className="flex gap-6">
        {/* 左侧 Tab 导航 */}
        <div className="w-48 flex-shrink-0">
          <nav className="space-y-1">
            {TABS.map((tab) => (
              <button
                key={tab.key}
                className={`w-full flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                  activeTab === tab.key
                    ? 'bg-primary-50 text-primary-700'
                    : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
                }`}
                onClick={() => setActiveTab(tab.key)}
              >
                <tab.icon className="w-5 h-5" />
                {tab.label}
              </button>
            ))}
          </nav>
        </div>

        {/* 右侧内容 */}
        <div className="flex-1 min-w-0">
          {/* 基础设置 */}
          {activeTab === 'basic' && (
            <div className="bg-white border border-gray-200 rounded-lg p-6">
              <h2 className="text-lg font-semibold text-gray-900 mb-6">基础设置</h2>
              {loading ? (
                <div className="text-center py-12 text-sm text-gray-500">加载中...</div>
              ) : (
                <div className="space-y-6 max-w-lg">
                  {/* 机器人名称 */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1.5">
                      机器人名称 <span className="text-red-500">*</span>
                    </label>
                    <input
                      type="text"
                      className="w-full h-9 px-3 rounded border border-gray-300 text-sm placeholder:text-gray-400 focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                      placeholder="小布"
                      value={aiConfig.botName}
                      onChange={(e) => setAiConfig({ ...aiConfig, botName: e.target.value })}
                    />
                    <p className="text-xs text-gray-500 mt-1.5">客户在对话中看到的 AI 助手名称</p>
                  </div>

                  {/* 欢迎语 */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1.5">欢迎语</label>
                    <textarea
                      rows={3}
                      className="w-full px-3 py-2 rounded border border-gray-300 text-sm placeholder:text-gray-400 focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 resize-none"
                      placeholder="您好，我是小布，有什么可以帮您？"
                      value={aiConfig.greetingTemplate}
                      onChange={(e) => setAiConfig({ ...aiConfig, greetingTemplate: e.target.value })}
                    />
                    <p className="text-xs text-gray-500 mt-1.5">客户发起对话时看到的第一条消息，支持变量 {'{customer_name}'}</p>
                  </div>

                  <div className="pt-4">
                    <Button onClick={handleSaveAiConfig} loading={savingAiConfig}>
                      <Save className="w-4 h-4 mr-1.5" />
                      保存设置
                    </Button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* 快捷回复 */}
          {activeTab === 'quick-replies' && (
            <div className="bg-white border border-gray-200 rounded-lg p-6">
              <div className="flex items-center justify-between mb-6">
                <h2 className="text-lg font-semibold text-gray-900">快捷回复</h2>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setShowNewForm(!showNewForm)}
                >
                  <Plus className="w-4 h-4 mr-1" />
                  新建回复
                </Button>
              </div>

              {/* 新建表单 */}
              {showNewForm && (
                <div className="mb-6 p-4 bg-gray-50 rounded-lg border border-gray-200">
                  <h3 className="text-sm font-semibold text-gray-700 mb-3">新建快捷回复</h3>
                  <div className="space-y-3">
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="block text-xs font-medium text-gray-600 mb-1">标题</label>
                        <input
                          type="text"
                          className="w-full h-8 px-2.5 rounded border border-gray-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                          placeholder="例如：欢迎语"
                          value={newForm.title}
                          onChange={(e) => setNewForm({ ...newForm, title: e.target.value })}
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-600 mb-1">分类</label>
                        <input
                          type="text"
                          className="w-full h-8 px-2.5 rounded border border-gray-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                          placeholder="通用"
                          value={newForm.category}
                          onChange={(e) => setNewForm({ ...newForm, category: e.target.value })}
                        />
                      </div>
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-600 mb-1">回复内容</label>
                      <textarea
                        rows={3}
                        className="w-full px-2.5 py-1.5 rounded border border-gray-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 resize-none"
                        placeholder="输入快捷回复内容..."
                        value={newForm.content}
                        onChange={(e) => setNewForm({ ...newForm, content: e.target.value })}
                      />
                    </div>
                    <div className="flex gap-2">
                      <Button size="sm" onClick={handleCreate} loading={savingTemplate}>
                        <Check className="w-4 h-4 mr-1" />
                        确认创建
                      </Button>
                      <Button size="sm" variant="secondary" onClick={() => setShowNewForm(false)}>
                        <X className="w-4 h-4 mr-1" />
                        取消
                      </Button>
                    </div>
                  </div>
                </div>
              )}

              {/* 快捷回复列表 */}
              {loadingTemplates ? (
                <div className="text-center py-12 text-sm text-gray-500">加载中...</div>
              ) : templates.length === 0 ? (
                <div className="text-center py-12">
                  <Zap className="w-10 h-10 text-gray-300 mx-auto mb-3" />
                  <p className="text-sm text-gray-500">暂无快捷回复</p>
                  <p className="text-xs text-gray-400 mt-1">点击&ldquo;新建回复&rdquo;添加第一条快捷回复</p>
                </div>
              ) : (
                <div className="space-y-3">
                  {templates.map((tpl) => (
                    <div
                      key={tpl.id}
                      className="border border-gray-200 rounded-lg p-4 hover:border-gray-300 transition-colors"
                    >
                      {editingId === tpl.id ? (
                        /* 编辑模式 */
                        <div className="space-y-3">
                          <div className="grid grid-cols-2 gap-3">
                            <div>
                              <label className="block text-xs font-medium text-gray-600 mb-1">标题</label>
                              <input
                                type="text"
                                className="w-full h-8 px-2.5 rounded border border-gray-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                                value={editForm.title}
                                onChange={(e) => setEditForm({ ...editForm, title: e.target.value })}
                              />
                            </div>
                            <div>
                              <label className="block text-xs font-medium text-gray-600 mb-1">分类</label>
                              <input
                                type="text"
                                className="w-full h-8 px-2.5 rounded border border-gray-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                                value={editForm.category}
                                onChange={(e) => setEditForm({ ...editForm, category: e.target.value })}
                              />
                            </div>
                          </div>
                          <div>
                            <label className="block text-xs font-medium text-gray-600 mb-1">回复内容</label>
                            <textarea
                              rows={3}
                              className="w-full px-2.5 py-1.5 rounded border border-gray-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 resize-none"
                              value={editForm.content}
                              onChange={(e) => setEditForm({ ...editForm, content: e.target.value })}
                            />
                          </div>
                          <div className="flex gap-2">
                            <Button size="sm" onClick={() => handleUpdate(tpl.id)} loading={savingTemplate}>
                              <Check className="w-4 h-4 mr-1" />
                              保存
                            </Button>
                            <Button size="sm" variant="secondary" onClick={cancelEdit}>
                              <X className="w-4 h-4 mr-1" />
                              取消
                            </Button>
                          </div>
                        </div>
                      ) : (
                        /* 展示模式 */
                        <div>
                          <div className="flex items-start justify-between">
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2 mb-1">
                                <h4 className="text-sm font-semibold text-gray-900">{tpl.title}</h4>
                                <Badge variant="default" className="text-xs">
                                  {tpl.category}
                                </Badge>
                                {tpl.shortcut && (
                                  <Badge variant="info" className="text-xs font-mono">
                                    {tpl.shortcut}
                                  </Badge>
                                )}
                              </div>
                              <p className="text-sm text-gray-600 whitespace-pre-wrap line-clamp-2">
                                {tpl.content}
                              </p>
                              <div className="flex items-center gap-3 mt-2 text-xs text-gray-400">
                                <span>使用 {tpl.usageCount || 0} 次</span>
                                <span>{tpl.updatedAt ? new Date(tpl.updatedAt).toLocaleDateString('zh-CN') : ''}</span>
                              </div>
                            </div>
                            <div className="flex items-center gap-1 ml-4 flex-shrink-0">
                              <button
                                className="p-1.5 text-gray-400 hover:text-primary-600 hover:bg-primary-50 rounded transition-colors"
                                onClick={() => startEdit(tpl)}
                                title="编辑"
                              >
                                <Edit3 className="w-4 h-4" />
                              </button>
                              <button
                                className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded transition-colors"
                                onClick={() => handleDelete(tpl.id, tpl.title)}
                                title="删除"
                              >
                                <Trash2 className="w-4 h-4" />
                              </button>
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
