'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { Building2, Save } from 'lucide-react'
import Image from 'next/image'
import { useSearchParams, useRouter } from 'next/navigation'
import { toast } from 'sonner'
import { Button } from '@/components/ui'
import { settingsApi, uploadApi } from '@/lib/api'
import { readImageDimensions } from '@/lib/image-dimensions'
import type { SystemSettings } from '@/types'

// #3006: 登录日志（无记录）+ 修改密码（未来统一短信码登录）已隐藏，
// 页面仅保留基本设置（品牌 + 通知设置），移除 tab 切换机制

export default function SettingsPage() {
  const searchParams = useSearchParams()
  const router = useRouter()

  // 旧链接 /settings?tab=ai → 重定向到 AI 客服配置
  useEffect(() => {
    if (searchParams.get('tab') === 'ai') {
      router.replace('/chat/config')
    }
  }, [searchParams, router])

  // ============ 基本设置 ============
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

  // 加载基本设置
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
      toast.success('设置已保存，侧边栏与米宝将同步展示企业信息')
    } catch (error: any) {
      toast.error(error?.response?.data?.error?.message || '保存失败')
    } finally {
      setSavingSettings(false)
    }
  }

  return (
    <div className="p-6">
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-neutral-900">企业基础信息</h1>
        <p className="text-sm text-neutral-500 mt-1">配置公司基本信息与站内通知</p>
      </div>

      {/* 基本设置 */}
      <div className="bg-white border border-neutral-200 rounded-lg p-6 max-w-lg">
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

              <div className="border-t border-neutral-200 pt-6">
                <h3 className="text-sm font-semibold text-neutral-900 mb-4">通知设置</h3>
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
