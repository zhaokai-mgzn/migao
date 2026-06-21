'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { Building2, Shield, Save, Eye, EyeOff } from 'lucide-react'
import Image from 'next/image'
import { useSearchParams, useRouter } from 'next/navigation'
import { toast } from 'sonner'
import { Button } from '@/components/ui'
import { settingsApi, uploadApi } from '@/lib/api'
import type { SystemSettings, ChangePasswordParams, LoginLog } from '@/types'
import dayjs from 'dayjs'

type SettingsTab = 'basic' | 'security'

const TABS: { key: SettingsTab; label: string; icon: typeof Building2 }[] = [
  { key: 'basic', label: '基本设置', icon: Building2 },
  { key: 'security', label: '账户安全', icon: Shield },
]

export default function SettingsPage() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const [activeTab, setActiveTab] = useState<SettingsTab>('basic')

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

  // 密码
  const [passwordForm, setPasswordForm] = useState<ChangePasswordParams>({
    oldPassword: '',
    newPassword: '',
    confirmPassword: '',
  })
  const [showPasswords, setShowPasswords] = useState({ old: false, new: false, confirm: false })
  const [changingPassword, setChangingPassword] = useState(false)

  // 登录日志
  const [loginLogs, setLoginLogs] = useState<LoginLog[]>([])
  const [loadingLogs, setLoadingLogs] = useState(false)

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

  // 加载登录日志
  const loadLoginLogs = useCallback(async () => {
    setLoadingLogs(true)
    try {
      const res = await settingsApi.getLoginLogs({ page: 1, size: 20 })
      setLoginLogs(res.data.data?.items || [])
    } catch (error) {
      toast.error('加载登录日志失败')
    } finally {
      setLoadingLogs(false)
    }
  }, [])

  // 根据当前 Tab 加载数据
  useEffect(() => {
    if (activeTab === 'basic') {
      loadSettings()
    } else if (activeTab === 'security') {
      loadLoginLogs()
    }
  }, [activeTab, loadSettings, loadLoginLogs])

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

  const handleChangePassword = async () => {
    if (!passwordForm.oldPassword) { toast.error('请输入当前密码'); return }
    if (!passwordForm.newPassword) { toast.error('请输入新密码'); return }
    if (passwordForm.newPassword.length < 6) { toast.error('密码长度至少 6 位'); return }
    if (passwordForm.newPassword !== passwordForm.confirmPassword) { toast.error('两次密码不一致'); return }

    setChangingPassword(true)
    try {
      await settingsApi.changePassword(passwordForm)
      toast.success('密码修改成功')
      setPasswordForm({ oldPassword: '', newPassword: '', confirmPassword: '' })
    } catch (error) {
      toast.error('密码修改失败')
    } finally {
      setChangingPassword(false)
    }
  }

  return (
    <div className="p-6">
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-gray-900">系统设置</h1>
        <p className="text-sm text-gray-500 mt-1">配置系统参数和账户安全</p>

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
          {/* 基本设置 */}
          {activeTab === 'basic' && (
            <div className="bg-white border border-gray-200 rounded-lg p-6">
              <h2 className="text-lg font-semibold text-gray-900 mb-6">基本设置</h2>
              <div className="space-y-6 max-w-lg">
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
            </div>
          )}

          {/* 账户安全 */}
          {activeTab === 'security' && (
            <div className="space-y-6">
              <div className="bg-white border border-gray-200 rounded-lg p-6">
                <h3 className="text-base font-semibold text-gray-900 mb-4">修改密码</h3>
                <div className="space-y-4 max-w-sm">
                  <div className="relative">
                    <label className="block text-sm font-medium text-gray-700 mb-1.5">当前密码</label>
                    <input
                      type={showPasswords.old ? 'text' : 'password'}
                      className="w-full h-9 px-3 pr-10 rounded border border-gray-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                      value={passwordForm.oldPassword}
                      onChange={(e) => setPasswordForm({ ...passwordForm, oldPassword: e.target.value })}
                      placeholder="请输入当前密码"
                    />
                    <button
                      type="button"
                      className="absolute right-2 top-[30px] text-gray-400 hover:text-gray-600"
                      onClick={() => setShowPasswords({ ...showPasswords, old: !showPasswords.old })}
                    >
                      {showPasswords.old ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>
                  <div className="relative">
                    <label className="block text-sm font-medium text-gray-700 mb-1.5">新密码</label>
                    <input
                      type={showPasswords.new ? 'text' : 'password'}
                      className="w-full h-9 px-3 pr-10 rounded border border-gray-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                      value={passwordForm.newPassword}
                      onChange={(e) => setPasswordForm({ ...passwordForm, newPassword: e.target.value })}
                      placeholder="请输入新密码"
                    />
                    <button
                      type="button"
                      className="absolute right-2 top-[30px] text-gray-400 hover:text-gray-600"
                      onClick={() => setShowPasswords({ ...showPasswords, new: !showPasswords.new })}
                    >
                      {showPasswords.new ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>
                  <div className="relative">
                    <label className="block text-sm font-medium text-gray-700 mb-1.5">确认新密码</label>
                    <input
                      type={showPasswords.confirm ? 'text' : 'password'}
                      className="w-full h-9 px-3 pr-10 rounded border border-gray-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                      value={passwordForm.confirmPassword}
                      onChange={(e) => setPasswordForm({ ...passwordForm, confirmPassword: e.target.value })}
                      placeholder="请输入确认新密码"
                    />
                    <button
                      type="button"
                      className="absolute right-2 top-[30px] text-gray-400 hover:text-gray-600"
                      onClick={() => setShowPasswords({ ...showPasswords, confirm: !showPasswords.confirm })}
                    >
                      {showPasswords.confirm ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>
                  <div className="pt-2">
                    <Button onClick={handleChangePassword} loading={changingPassword}>
                      <Save className="w-4 h-4 mr-1.5" />
                      修改密码
                    </Button>
                  </div>
                </div>
              </div>

              <div className="bg-white border border-gray-200 rounded-lg p-6">
                <h3 className="text-base font-semibold text-gray-900 mb-4">登录日志</h3>
                {loadingLogs ? (
                  <div className="text-sm text-gray-500">加载中...</div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-gray-200">
                          <th className="text-left py-2 pr-4 font-medium text-gray-600">IP 地址</th>
                          <th className="text-left py-2 pr-4 font-medium text-gray-600">设备</th>
                          <th className="text-left py-2 pr-4 font-medium text-gray-600">位置</th>
                          <th className="text-left py-2 font-medium text-gray-600">登录时间</th>
                        </tr>
                      </thead>
                      <tbody>
                        {loginLogs.length === 0 ? (
                          <tr>
                            <td colSpan={4} className="text-center py-4 text-sm text-gray-500">暂无登录记录</td>
                          </tr>
                        ) : (
                          loginLogs.map((log) => (
                            <tr key={log.id} className="border-b border-gray-100">
                              <td className="py-2 pr-4 text-gray-900">{log.ip}</td>
                              <td className="py-2 pr-4 text-gray-600">{log.device}</td>
                              <td className="py-2 pr-4 text-gray-600">{log.location}</td>
                              <td className="py-2 text-gray-600">{dayjs(log.createdAt).format('YYYY-MM-DD HH:mm')}</td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}