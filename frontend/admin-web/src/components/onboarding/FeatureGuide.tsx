'use client'

import { useEffect, useState } from 'react'
import { BarChart3, Bot, Menu, Sparkles, Star } from 'lucide-react'
import Modal from '@/components/ui/Modal'
import Button from '@/components/ui/Button'
import { useAuthStore } from '@/store/auth'
import {
  buildFeatureGuideModules,
  dismissFeatureGuide,
  featureGuideUserKey,
  markFeatureGuideShown,
  shouldShowFeatureGuide,
} from '@/lib/feature-guide'

interface FeatureGuideProps {
  /** 路由守卫判为无权（403 面）时不弹：用户当前连这一页都进不去，先解决权限问题。 */
  enabled?: boolean
}

/**
 * 首次登录功能使用引导（issue #8925）。
 *
 * 触发链：登录成功 ⇒ `markFeatureGuidePending()`（sessionStorage）⇒ 业务页布局挂载本组件
 * ⇒ `shouldShowFeatureGuide()` 三重判定（本次登录待展示 / 本会话没展示过 / 没点「不再提醒」）。
 * 关闭与「不再提醒」的持久化语义都在 `@/lib/feature-guide`，本组件只负责呈现。
 *
 * 功能地图不另写菜单：按 `config/menu.ts` 的分组 + 当前账号权限派生（同侧边栏过滤函数），
 * 所以菜单改名、权限收回后引导不会出现「教用户点不存在的入口」。
 */
export default function FeatureGuide({ enabled = true }: FeatureGuideProps) {
  const user = useAuthStore((s) => s.user)
  const [open, setOpen] = useState(false)
  const userKey = featureGuideUserKey(user)

  useEffect(() => {
    if (!enabled) return
    if (!userKey || !shouldShowFeatureGuide(userKey)) return
    // 先消费标记再开窗：React StrictMode 下 effect 会跑两次，第二次据此不再重复打开。
    markFeatureGuideShown()
    setOpen(true)
  }, [enabled, userKey])

  if (!user) return null

  const permissions = user.permissions || []
  const roles = user.roles || []
  const modules = buildFeatureGuideModules(permissions, roles)
  const canSeeDashboard = permissions.includes('*') || permissions.includes('dashboard:view')
  const canUseMibao = user.capabilities?.mibaoChat === true

  const steps: Array<{ icon: typeof BarChart3; title: string; body: string }> = [
    ...(canSeeDashboard
      ? [{
          icon: BarChart3,
          title: '先看经营报表',
          body: '登录后先看这里：今日经营、待处理、经营数据与经营分析都在这页，今天的钱和活一眼看清。',
        }]
      : []),
    {
      icon: Menu,
      title: '从左侧菜单进入业务',
      body: '菜单按你的岗位权限展示。点组名展开，找不到入口时再看一眼下面这份功能地图。',
    },
    {
      icon: Star,
      title: '把高频功能钉在最上面',
      body: '菜单项右侧的星标可加入「常用」；按 Ctrl / ⌘ + K 搜索功能名或拼音首字母，直达对应页面。',
    },
    ...(canUseMibao
      ? [{
          icon: Bot,
          title: '不会操作就问米宝',
          body: '右下角米宝助手会结合当前页面回答操作问题；找不到入口时也可以直接问它。',
        }]
      : []),
  ]

  const handleClose = () => setOpen(false)

  const handleNeverRemind = () => {
    if (userKey) dismissFeatureGuide(userKey)
    setOpen(false)
  }

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="功能使用引导"
      width={820}
      closable={false}
      maskClosable={false}
      footer={
        <div className="flex w-full flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs leading-5 text-neutral-500">
            「关闭」仅本次，下次登录仍会提示
          </p>
          <div className="flex items-center justify-end gap-3">
            <Button
              type="button"
              variant="secondary"
              data-testid="feature-guide-never"
              onClick={handleNeverRemind}
            >
              不再提醒
            </Button>
            <Button
              type="button"
              data-testid="feature-guide-close"
              onClick={handleClose}
            >
              关闭
            </Button>
          </div>
        </div>
      }
    >
      <div data-testid="feature-guide" className="space-y-5">
        <div className="rounded-xl border border-primary-100 bg-gradient-to-br from-primary-50 via-white to-neutral-50 p-4">
          <div className="flex items-start gap-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary-100 text-primary-700">
              <Sparkles className="h-5 w-5" aria-hidden />
            </span>
            <div>
              <h4 className="text-base font-semibold text-neutral-900">欢迎使用观星台</h4>
              <p className="mt-1 text-sm leading-6 text-neutral-600">
                这是一份按你的岗位权限生成的功能地图，帮你快速找到要用的功能。
              </p>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {steps.map((step) => (
            <div
              key={step.title}
              data-testid="feature-guide-step"
              className="rounded-xl border border-neutral-200 bg-white p-3.5"
            >
              <div className="flex items-center gap-2">
                <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-neutral-100 text-neutral-600">
                  <step.icon className="h-4 w-4" aria-hidden />
                </span>
                <h5 className="text-sm font-semibold text-neutral-800">{step.title}</h5>
              </div>
              <p className="mt-2 text-xs leading-5 text-neutral-500">{step.body}</p>
            </div>
          ))}
        </div>

        <div>
          <div className="mb-2 flex items-baseline justify-between gap-3">
            <h5 className="text-sm font-semibold text-neutral-800">你的可用功能</h5>
            <span className="text-xs text-neutral-400">按当前岗位权限展示</span>
          </div>
          {modules.length > 0 ? (
            <div data-testid="feature-guide-modules" className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {modules.map((module) => (
                <div
                  key={module.key}
                  data-testid={`feature-guide-module-${module.key}`}
                  className="rounded-lg border border-neutral-200 bg-neutral-50/70 px-3 py-2.5"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium text-neutral-800">{module.name}</span>
                    <span className="shrink-0 text-[11px] text-neutral-400">{module.items.length} 项</span>
                  </div>
                  <p className="mt-1 text-xs leading-5 text-neutral-500">{module.items.join(' · ')}</p>
                </div>
              ))}
            </div>
          ) : (
            <p
              data-testid="feature-guide-no-modules"
              className="rounded-lg border border-dashed border-neutral-200 bg-neutral-50 px-3 py-4 text-sm text-neutral-500"
            >
              当前账号还没有可见菜单，请联系企业管理员配置岗位权限。
            </p>
          )}
        </div>
      </div>
    </Modal>
  )
}
