'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { Building2, Save } from 'lucide-react'
import Image from 'next/image'
import { useSearchParams, useRouter } from 'next/navigation'
import { toast } from 'sonner'
import { Button } from '@/components/ui'
import { settingsApi, uploadApi } from '@/lib/api'
import type { SystemSettings } from '@/types'

export default function SettingsPage() {
  const searchParams = useSearchParams()
  const router = useRouter()

  // 旧链接 /settings?tab=ai → 重定向到机器人设置
  useEffect(() => {
    if (searchParams.get('tab') === 'ai') {
      router.replace('/chat/config')
    }
  }, [searchParams, router])

  // 基本设置
  const [settings, setSettings] = useState<SystemSettings>({
    companyName: '',
    logo: '',
    notificationEnabled: false,
    notificationEmail: '',
  })
  const [savingSettings, setSavingSettings] = useState(false)
  const [uploadingLogo, setUploadingLogo] = useState(false)
  const [loadingSettings, setLoadingSettings] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // 加载基本设置
  const loadSettings = useCallback(async () => {
    setLoadingSettings(true)
    try {
      const res = await settingsApi.getSettings()
      if (res.data.data) {
        setSettings(res.data.data)
      }
    } catch (error) {
      toast.error('加载设置失败')
    } finally {
      setLoadingSettings(false)
    }
  }, [])

  useEffect(() => {
    loadSettings()
  }, [loadSettings])

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
    setUploadingLogo(true)
    try {
      const res = await uploadApi.uploadImage(file)
      setSettings((prev) => ({ ...prev, logo: res.data.data.url }))
      toast.success('Logo 上传成功')
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
      toast.success('设置已保存')
    } catch (error) {
      toast.error('保存失败')
    } finally {
      setSavingSettings(false)
    }
  }

  return (
    <div className="p-6">
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-gray-900">企业基础信息</h1>
        <p className="text-sm text-gray-500 mt-1">配置公司基本信息和系统参数</p>
      </div>

      <div className="bg-white border border-gray-200 rounded-lg p-6 max-w-lg">
        {loadingSettings ? (
          <div className="text-sm text-gray-500 py-8 text-center">加载中...</div>
        ) : (
          <div className="space-y-6">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">
                公司名称 <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                className="w-full h-9 px-3 rounded border border-gray-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                value={settings.companyName}
                onChange={(e) => setSettings({ ...settings, companyName: e.target.value })}
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">Logo</label>
              <div className="flex items-center gap-4">
                <div className="w-16 h-16 bg-gray-100 rounded-lg flex items-center justify-center border border-gray-200">
                  {settings.logo ? (
                    <Image src={settings.logo} alt="Logo" width={64} height={64} className="w-full h-full object-cover rounded-lg" unoptimized />
                  ) : (
                    <Building2 className="w-8 h-8 text-gray-400" />
                  )}
                </div>
                <Button variant="secondary" size="sm" onClick={() => fileInputRef.current?.click()} loading={uploadingLogo}>上传 Logo</Button>
                <input ref={fileInputRef} type="file" accept="image/jpeg,image/png,image/webp" className="hidden" onChange={handleLogoUpload} />
              </div>
            </div>

            <div className="border-t border-gray-200 pt-6">
              <h3 className="text-sm font-semibold text-gray-900 mb-4">通知设置</h3>
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm font-medium text-gray-700">启用系统通知</div>
                    <div className="text-xs text-gray-500">接收订单、客服等重要通知</div>
                  </div>
                  <button
                    className={`relative w-11 h-6 rounded-full transition-colors ${
                      settings.notificationEnabled ? 'bg-primary-600' : 'bg-gray-300'
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
                    <label className="block text-sm font-medium text-gray-700 mb-1.5">通知邮箱</label>
                    <input
                      type="email"
                      className="w-full h-9 px-3 rounded border border-gray-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                      value={settings.notificationEmail || ''}
                      onChange={(e) => setSettings({ ...settings, notificationEmail: e.target.value })}
                      placeholder="接收通知的邮箱地址"
                    />
                  </div>
                )}
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
    </div>
  )
}
