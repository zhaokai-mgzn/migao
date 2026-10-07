'use client'

/**
 * 工人端页面开关面板（V141，母单 #5161）—— 挂在「设置 → 工人端页面」tab **页内**渲染。
 *
 * ## 为什么是 settings 的一个 tab（`migao-dev-flow` §22 P1）
 *
 * 用户裁定：商家端**不新建路由/菜单**（那会动「菜单三源同构」那套），
 * 在**现有**页面里加一个最小配置区即可。工人端页面是**企业级**开关
 * ⇒ 与「参数总览」同层放 settings 里（同族先例：`TenantParamsPanel` 的小件用料面板也是页内挂载）。
 *
 * ## 🔴 本组件不判任何口径、不下发任何权限
 *
 * - 「哪些页面键合法」「缺键怎么办」全在**服务端**（`WorkerPageConfigService` 的闭词表 + 422 逐条理由）
 *   ⇒ 组件把服务端的逐条理由**原样**贴出来（不自己编文案、不静默丢弃被拒的键）；
 * - 这里的 `pages` 是**页面可见性**，**不是**权限码：工人 session 的 `permissions` 恒为 `[]`，
 *   工人可达面恒为 `/api/worker/**`。把某个页面关掉**不等于**挡住对应接口 —— 这句话显式印在面板里，
 *   而不是让商家猜（否则商家会以为「关了发货页 = 工人发不了货」）。
 *
 * ## §22 落点
 *
 * | 原则 | 本组件怎么做 |
 * |---|---|
 * | **P2 三件套** | 每个页面给 `label`（人话名）+ 一句口径（这个页面工人拿它干什么） |
 * | **P3 默认值可见** | 读面 `source='default'` ⇒ 显式标「**未配置（正在用默认值 = 全部页面都开）**」 |
 * | **不越界** | 本面板**不碰**工人 session 的闲置超时（那是服务端配置 `worker.session.idle-minutes`，默认 30 天）—— 只配页面开关 |
 * | **P4 改完会怎样** | 面板顶部印「改动**只影响工人端页面上看不看得见**，不影响任何权限」 |
 * | **P5 术语可就地查** | 页面名用商家端既有叫法（报工 / 订单 / 裁高计算器 / 发货） |
 * | **基线 ① 文案不出现数字** | 面板不写任何权限码 / 会话时长（43200 分钟 = 30 天）字面量 |
 */
import { useCallback, useEffect, useState } from 'react'
import { AlertCircle, Check, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui'
import { workerPageConfigApi } from '@/lib/api'
import type { WorkerPageConfigResponse } from '@/types'

/** 每个页面一句口径（键是机器码；文案是给商家人读的）。 */
const PAGE_HINTS: Record<string, string> = {
  report: '扫码领活 / 完工报工（计件归属那一笔就记在这里）',
  order: '订单与套号明细（工人看自己要做的单）',
  cut_calc: '裁高计算器（与「工艺配置 → 裁高配置」同一个算面）',
  shipment: '发货（工人拍照发货的那一面）',
}

export function WorkerPageConfigPanel() {
  const [view, setView] = useState<WorkerPageConfigResponse | null>(null)
  const [keys, setKeys] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [problems, setProblems] = useState<string[]>([])
  const [savedAt, setSavedAt] = useState('')

  const apply = useCallback((next: WorkerPageConfigResponse) => {
    setView(next)
    setKeys(next.pages)
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    setProblems([])
    try {
      const res = await workerPageConfigApi.get()
      const data = res.data?.data
      if (data) apply(data)
      else setView(null)
    } catch {
      // 读面受 `production:view` 门控：**权限拒绝是终态**，不是「参数有问题」⇒ 给可行动话术
      setView(null)
      setProblems(['工人端页面读取失败（可能是当前岗位没有「生产」查看权限）—— 请联系管理员开权限后重试'])
    }
    setLoading(false)
  }, [apply])

  useEffect(() => {
    void load()
  }, [load])

  const toggle = useCallback((key: string) => {
    setSavedAt('')
    setKeys((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]))
  }, [])

  const save = useCallback(async () => {
    setSaving(true)
    setProblems([])
    setSavedAt('')
    try {
      const res = await workerPageConfigApi.update({ pages: keys })
      const data = res.data?.data
      if (data) {
        apply(data)
        setSavedAt('已保存 —— 工人端下次进入时按这份页面集渲染')
      }
    } catch (e) {
      // 服务端逐条理由**原样**显示（不自己编文案、不静默丢弃被拒的键）
      setProblems(problemLinesOf(e))
    }
    setSaving(false)
  }, [keys, apply])

  const labels = view?.labels ?? {}
  const allKeys = Object.keys(labels)
  const isDefault = view?.source === 'default'

  return (
    <div className="bg-white border border-neutral-200 rounded-lg p-6 max-w-2xl" data-testid="worker-page-config">
      <div className="flex items-start justify-between gap-4 mb-1">
        <h2 className="text-lg font-semibold text-neutral-900">工人端页面</h2>
        <Button variant="secondary" onClick={() => void load()} disabled={loading}>
          <RefreshCw className={loading ? 'w-4 h-4 animate-spin' : 'w-4 h-4'} />
          刷新
        </Button>
      </div>

      {/* §22 P4：改动的影响面必须显式说清（商家最容易误读成「权限」） */}
      <p className="text-xs text-neutral-500 mb-4">
        这里的开关只决定工人端 <b>页面上看不看得见</b>，<b>不代表权限</b>：关掉某个页面不会改变工人能访问的接口。
        工人始终只有工人端身份，进不了管理后台。
      </p>

      {isDefault && !loading && (
        <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1 mb-4" data-testid="worker-page-config-default">
          未配置（正在用默认值：全部页面都开）—— 保存一次即成为本企业自己的配置
        </p>
      )}

      {loading ? (
        <p className="text-sm text-neutral-500">加载中…</p>
      ) : (
        <div className="space-y-2">
          {allKeys.map((key) => (
            <label
              key={key}
              className="flex items-start gap-3 p-2 rounded hover:bg-neutral-50 cursor-pointer"
              data-testid={`worker-page-${key}`}
            >
              <input
                type="checkbox"
                className="mt-1 w-4 h-4"
                checked={keys.includes(key)}
                onChange={() => toggle(key)}
              />
              <span className="min-w-0">
                <span className="text-sm font-medium text-neutral-900">{labels[key]}</span>
                <span className="block text-xs text-neutral-500">{PAGE_HINTS[key] ?? '工人端页面'}</span>
              </span>
            </label>
          ))}
          {allKeys.length === 0 && (
            <p className="text-sm text-neutral-500">
              没有读到可配置的页面清单（服务端没回 labels）—— 请刷新重试，不要凭记忆勾选
            </p>
          )}
        </div>
      )}

      {problems.length > 0 && (
        <div className="mt-3 text-sm text-danger-600 space-y-1" data-testid="worker-page-config-error">
          {problems.map((p) => (
            <p key={p} className="flex items-start gap-2">
              <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
              <span>{p}</span>
            </p>
          ))}
        </div>
      )}

      {savedAt && (
        <p className="mt-3 text-sm text-green-600 flex items-center gap-2" data-testid="worker-page-config-saved">
          <Check className="w-4 h-4" />
          {savedAt}
        </p>
      )}

      <div className="pt-4">
        <Button onClick={() => void save()} loading={saving} disabled={loading || allKeys.length === 0}>
          保存
        </Button>
      </div>
    </div>
  )
}

/** 服务端 422 的逐条理由 ⇒ 人读行（读不到 details ⇒ 退回一句话摘要，不编理由）。 */
function problemLinesOf(error: unknown): string[] {
  const err = (error as { response?: { data?: { error?: { message?: string; details?: unknown } } } })
    ?.response?.data?.error
  const details = err?.details
  if (Array.isArray(details)) {
    const lines = details
      .map((d) => {
        const item = d as { field?: string; message?: string }
        if (!item?.message) return ''
        return item.field ? `${item.field}：${item.message}` : item.message
      })
      .filter(Boolean)
    if (lines.length > 0) return lines
  }
  return [err?.message || '保存失败（请检查页面清单后重试）']
}
