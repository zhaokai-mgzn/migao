'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { Building2, Bot, Bell, Save } from 'lucide-react'
import Image from 'next/image'
import { useSearchParams } from 'next/navigation'
import { toast } from 'sonner'
import { Button } from '@/components/ui'
import { settingsApi, uploadApi } from '@/lib/api'
import { readImageDimensions } from '@/lib/image-dimensions'
import { useAuthStore } from '@/store/auth'
import type { SystemSettings, AiConfig } from '@/types'

// #3081: 原「AI 客服配置」独立页面（/chat/config）合并进企业基础信息，
// 区块命名「AI 客服设置」——配置顾客在对话中看到的 AI 客服助手（小布）的名称与欢迎语。
// #3098: 恢复 #3006 之前的左侧 tab 导航布局（基本设置 / AI 客服设置 / 通知设置）；
// 修改密码/登录日志保持 #3006 隐藏决定（登录日志无记录、密码未来统一短信码登录）。

type SettingsTab = 'basic' | 'ai' | 'notification'

const TABS: { key: SettingsTab; label: string; icon: typeof Building2 }[] = [
  { key: 'basic', label: '基本设置', icon: Building2 },
  { key: 'ai', label: 'AI 客服设置', icon: Bot },
  { key: 'notification', label: '通知设置', icon: Bell },
]

export default function SettingsPage() {
  const searchParams = useSearchParams()
  const urlTab = searchParams?.get('tab')
  // 支持 ?tab=ai 直达（原 /chat/config 时代的旧链接兼容，#3098 tab 布局）
  const [activeTab, setActiveTab] = useState<SettingsTab>(urlTab === 'ai' ? 'ai' : 'basic')

  // ============ 基本设置（企业信息）============
  const [settings, setSettings] = useState<SystemSettings>({
    companyName: '',
    logo: '',
    notificationEnabled: false,
    notificationEmail: '',
  })
  const [savingSettings, setSavingSettings] = useState(false)
  const [uploadingLogo, setUploadingLogo] = useState(false)
  // Logo 预览加载失败标记：URL 失效/过期时回退到占位图标
  const [logoPreviewError, setLogoPreviewError] = useState(false)
  const [loadingSettings, setLoadingSettings] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // ============ AI 客服设置 ============
  const defaultAiConfig: AiConfig = {
    botName: '小布',
    greetingTemplate: '',
  }
  const [aiConfig, setAiConfig] = useState<AiConfig>(defaultAiConfig)
  const [loadingAiConfig, setLoadingAiConfig] = useState(false)
  const [savingAiConfig, setSavingAiConfig] = useState(false)

  // 加载企业信息
  const loadSettings = useCallback(async () => {
    setLoadingSettings(true)
    try {
      const res = await settingsApi.getSettings()
      if (res.data.data) {
        setSettings({
          companyName: res.data.data.companyName || '',
          logo: res.data.data.logo || '',
          notificationEnabled: !!res.data.data.notificationEnabled,
          notificationEmail: res.data.data.notificationEmail || '',
        })
        // Logo 变化时重置预览失败标记
        setLogoPreviewError(false)
      }
    } catch (error) {
      toast.error('加载设置失败')
    } finally {
      setLoadingSettings(false)
    }
  }, [])

  // 加载 AI 客服设置
  const loadAiConfig = useCallback(async () => {
    setLoadingAiConfig(true)
    try {
      const res = await settingsApi.getAiConfig()
      if (res.data.data) {
        setAiConfig({ ...defaultAiConfig, ...res.data.data })
      }
    } catch (e) {
      toast.error('加载 AI 客服设置失败')
    } finally {
      setLoadingAiConfig(false)
    }
  }, [])

  useEffect(() => {
    loadSettings()
    loadAiConfig()
  }, [loadSettings, loadAiConfig])

  const handleLogoUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
      toast.error('仅支持 JPG、PNG、WebP 格式')
      return
    }
    if (file.size > 5 * 1024 * 1024) {
      toast.error('图片大小不能超过 5MB')
      return
    }
    // 分辨率校验：Logo 在侧边栏仅 32×32（预览 64×64，2x retina 即 128px），
    // 过小图片会被放大导致模糊。最小 128×128，建议正方形（展示区按正方形居中裁剪）。
    try {
      const dims = await readImageDimensions(file)
      if (dims.width < 128 || dims.height < 128) {
        toast.error(`图片分辨率过低（${dims.width}×${dims.height}），建议至少 128×128 像素且为正方形`)
        return
      }
    } catch {
      // 读取尺寸失败（环境不支持）时不阻断上传，交由后端格式/大小校验兜底
    }
    setUploadingLogo(true)
    try {
      const res = await uploadApi.uploadImage(file)
      setSettings((prev) => ({ ...prev, logo: res.data.data.url }))
      setLogoPreviewError(false)
      toast.success('Logo 上传成功，记得点击「保存设置」生效')
    } catch {
      toast.error('Logo 上传失败')
    } finally {
      setUploadingLogo(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const handleSaveSettings = async () => {
    if (!settings.companyName.trim()) {
      toast.error('请输入公司名称')
      return
    }
    setSavingSettings(true)
    try {
      await settingsApi.updateSettings(settings)
      // #3099: 保存后立即刷新用户信息（企业名/Logo 在 /api/auth/me 内层 user.tenantName/tenantLogo），
      // 否则侧边栏/右上角需刷新页面才同步 —— 此前 toast 宣称「侧边栏将同步展示」但实际不刷新
      try {
        await useAuthStore.getState().fetchUserInfo()
      } catch {
        // 刷新失败不阻塞保存成功的提示（下次进入应用/刷新页面仍会同步）
      }
      toast.success('企业信息已保存，侧边栏将同步展示')
    } catch (error: any) {
      toast.error(error?.response?.data?.error?.message || '保存失败')
    } finally {
      setSavingSettings(false)
    }
  }

  const handleSaveAiConfig = async () => {
    if (!aiConfig.botName.trim()) {
      toast.error('请输入 AI 客服名称')
      return
    }
    setSavingAiConfig(true)
    try {
      await settingsApi.updateAiConfig(aiConfig)
      toast.success('AI 客服设置已保存，顾客侧将按新配置生效')
    } catch (e) {
      toast.error('保存失败')
    } finally {
      setSavingAiConfig(false)
    }
  }

  return (
    <div className="p-6">
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-neutral-900">企业基础信息</h1>
        <p className="text-sm text-neutral-500 mt-1">配置公司基本信息、AI 客服助手与站内通知</p>
      </div>

      <div className="flex gap-6">
        {/* 左侧 Tab 导航（#3098 恢复 #3006 之前的 tab 布局） */}
        <div className="w-48 flex-shrink-0">
          <nav className="space-y-1">
            {TABS.map((tab) => (
              <button
                key={tab.key}
                className={`w-full flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                  activeTab === tab.key
                    ? 'bg-primary-50 text-primary-700'
                    : 'text-neutral-600 hover:bg-neutral-50 hover:text-neutral-900'
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
          {/* 基本设置（企业信息） */}
          {activeTab === 'basic' && (
            <div className="bg-white border border-neutral-200 rounded-lg p-6 max-w-lg">
              <h2 className="text-lg font-semibold text-neutral-900 mb-6">基本设置</h2>
              {loadingSettings ? (
                <div className="text-sm text-neutral-500 py-8 text-center">加载中...</div>
              ) : (
                <div className="space-y-6">
                  <div>
                    <label className="block text-sm font-medium text-neutral-700 mb-1.5">
                      公司名称 <span className="text-red-500">*</span>
                    </label>
                    <input
                      type="text"
                      className="w-full h-9 px-3 rounded border border-neutral-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                      value={settings.companyName}
                      onChange={(e) => setSettings({ ...settings, companyName: e.target.value })}
                    />
                    <p className="text-xs text-neutral-400 mt-1">将展示在后台侧边栏与米宝的企业身份中</p>
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-neutral-700 mb-1.5">Logo</label>
                    <div className="flex items-center gap-4">
                      <div className="w-16 h-16 bg-neutral-100 rounded-lg flex items-center justify-center border border-neutral-200 overflow-hidden">
                        {settings.logo && !logoPreviewError ? (
                          <Image
                            src={settings.logo}
                            alt="Logo"
                            width={64}
                            height={64}
                            className="w-full h-full object-cover rounded-lg"
                            unoptimized
                            onError={() => setLogoPreviewError(true)}
                          />
                        ) : (
                          <Building2 className="w-8 h-8 text-neutral-400" />
                        )}
                      </div>
                      <div>
                        <div className="flex items-center gap-2">
                          <Button variant="secondary" size="sm" onClick={() => fileInputRef.current?.click()} loading={uploadingLogo}>上传 Logo</Button>
                          {settings.logo && (
                            <Button
                              variant="secondary"
                              size="sm"
                              onClick={() => {
                                setSettings((prev) => ({ ...prev, logo: '' }))
                                setLogoPreviewError(false)
                              }}
                            >
                              移除 Logo
                            </Button>
                          )}
                        </div>
                        <input ref={fileInputRef} type="file" accept="image/jpeg,image/png,image/webp" className="hidden" onChange={handleLogoUpload} />
                        <p className="text-xs text-neutral-400 mt-1.5">
                          未设置时展示米高默认 Logo；上传/移除后需点击「保存设置」生效，将展示在后台侧边栏企业名旁
                        </p>
                      </div>
                    </div>
                  </div>

                  <div className="pt-4">
                    <Button onClick={handleSaveSettings} loading={savingSettings}>
                      <Save className="w-4 h-4 mr-1.5" />
                      保存设置
                    </Button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* AI 客服设置（原 AI 客服配置基础设置，#3081 合并进企业基础信息） */}
          {activeTab === 'ai' && (
            <div className="bg-white border border-neutral-200 rounded-lg p-6 max-w-lg">
              <div className="flex items-start gap-3 mb-6">
                <div className="w-9 h-9 rounded-lg bg-primary-50 flex items-center justify-center flex-shrink-0">
                  <Bot className="w-5 h-5 text-primary-600" />
                </div>
                <div>
                  <h2 className="text-lg font-semibold text-neutral-900">AI 客服设置</h2>
                  <p className="text-sm text-neutral-500 mt-0.5">
                    配置顾客在对话中看到的 AI 客服助手（小布）的名称与欢迎语
                  </p>
                </div>
              </div>
              {loadingAiConfig ? (
                <div className="text-sm text-neutral-500 py-8 text-center">加载中...</div>
              ) : (
                <div className="space-y-6">
                  <div>
                    <label className="block text-sm font-medium text-neutral-700 mb-1.5">
                      AI 客服名称 <span className="text-red-500">*</span>
                    </label>
                    <input
                      type="text"
                      className="w-full h-9 px-3 rounded border border-neutral-300 text-sm placeholder:text-neutral-400 focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                      placeholder="小布"
                      value={aiConfig.botName}
                      onChange={(e) => setAiConfig({ ...aiConfig, botName: e.target.value })}
                    />
                    <p className="text-xs text-neutral-500 mt-1.5">顾客在对话中看到的 AI 客服助手名称（默认：小布）</p>
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-neutral-700 mb-1.5">欢迎语</label>
                    <textarea
                      rows={3}
                      className="w-full px-3 py-2 rounded border border-neutral-300 text-sm placeholder:text-neutral-400 focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 resize-none"
                      placeholder="您好，我是小布，有什么可以帮您？"
                      value={aiConfig.greetingTemplate}
                      onChange={(e) => setAiConfig({ ...aiConfig, greetingTemplate: e.target.value })}
                    />
                    <p className="text-xs text-neutral-500 mt-1.5">顾客发起对话时看到的第一条消息，支持变量 {'{customer_name}'}</p>
                  </div>

                  <div className="pt-4">
                    <Button onClick={handleSaveAiConfig} loading={savingAiConfig}>
                      <Save className="w-4 h-4 mr-1.5" />
                      保存 AI 客服设置
                    </Button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* 通知设置 */}
          {activeTab === 'notification' && (
            <div className="bg-white border border-neutral-200 rounded-lg p-6 max-w-lg">
              <h2 className="text-lg font-semibold text-neutral-900 mb-6">通知设置</h2>
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm font-medium text-neutral-700">启用系统通知</div>
                    <div className="text-xs text-neutral-500">控制订单、客服等重要事件站内通知的发送；关闭后不再产生新的站内通知（历史通知保留）</div>
                  </div>
                  <button
                    className={`relative w-11 h-6 rounded-full transition-colors ${
                      settings.notificationEnabled ? 'bg-primary-600' : 'bg-neutral-300'
                    }`}
                    onClick={() => setSettings({ ...settings, notificationEnabled: !settings.notificationEnabled })}
                  >
                    <span
                      className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full transition-transform shadow ${
                        settings.notificationEnabled ? 'translate-x-5' : 'translate-x-0'
                      }`}
                    />
                  </button>
                </div>

                {settings.notificationEnabled && (
                  <div>
                    <label className="block text-sm font-medium text-neutral-700 mb-1.5">通知邮箱</label>
                    <input
                      type="email"
                      className="w-full h-9 px-3 rounded border border-neutral-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                      value={settings.notificationEmail || ''}
                      onChange={(e) => setSettings({ ...settings, notificationEmail: e.target.value })}
                      placeholder="接收通知的邮箱地址"
                    />
                  </div>
                )}

                <div className="pt-4">
                  <Button onClick={handleSaveSettings} loading={savingSettings}>
                    <Save className="w-4 h-4 mr-1.5" />
                    保存通知设置
                  </Button>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
