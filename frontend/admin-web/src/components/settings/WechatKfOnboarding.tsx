'use client'

import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { QRCodeSVG } from 'qrcode.react'
import { CheckCircle2, Copy, ExternalLink } from 'lucide-react'
import { kfApi, type KfChannelView, type KfSetupInfo } from '@/lib/kf-api'
import { displayEnum } from '@/lib/enum-display'

const STATUS_LABEL: Record<string, string | undefined> = {
  active: '已接通',
  unauthorized: '待自检',
  expired: '已过期',
  revoked: '已停用',
}

function errorMessage(error: unknown): string {
  const e = error as { response?: { data?: { error?: { message?: string } } }; message?: string }
  return e.response?.data?.error?.message || e.message || '请求失败，请稍后重试'
}

/**
 * 微信客服渠道自助接入（issue #9230）。
 *
 * 产品面只收商户自己的 corp_id / open_kfid / secret；secret 只提交一次，服务端加密落库，
 * 列表接口不回传。自检成功才置 active；失败保留渠道并给出可执行原因。
 */
export function WechatKfOnboarding() {
  const [channels, setChannels] = useState<KfChannelView[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [notice, setNotice] = useState<{ kind: 'ok' | 'warn' | 'error'; text: string } | null>(null)
  const [form, setForm] = useState({ corpId: '', openKfid: '', secret: '' })
  const [setup, setSetup] = useState<KfSetupInfo>({
    callbackUrl: '',
    callbackToken: null,
    encodingAesKey: null,
    trustedIps: [],
  })
  const [link, setLink] = useState<{ channelId: string; url: string } | null>(null)

  useEffect(() => {
    // 回退值：老部署没有 setup-info 端点时，至少给出本页回调地址
    setSetup((prev) => ({ ...prev, callbackUrl: `${window.location.origin}/api/kf/callback` }))
    void (async () => {
      try {
        const res = await kfApi.getSetupInfo()
        const data = res.data.data
        if (data) setSetup(data)
      } catch {
        // 读不到就保留回退地址与「联系平台管理员」提示 —— 不谎报已配置
      }
    })()
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await kfApi.listChannels()
      setChannels(res.data.data || [])
    } catch (error) {
      setNotice({ kind: 'error', text: errorMessage(error) })
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const create = async () => {
    if (!form.corpId.trim() || !form.openKfid.trim() || !form.secret.trim()) {
      setNotice({ kind: 'warn', text: '企业 ID、客服账号 ID、Secret 三项都要填写' })
      return
    }
    setSaving(true)
    setNotice(null)
    try {
      const res = await kfApi.createChannel(form)
      const result = res.data.data
      if (!result) throw new Error('没有拿到接入结果，请重试')
      setForm({ corpId: '', openKfid: '', secret: '' })
      setNotice(result.verified
        ? { kind: 'ok', text: '接入成功：客服账号已在线，可以生成客服链接了' }
        : { kind: 'warn', text: result.message || '渠道已保存，但自检未通过，请按提示修正后重试' })
      await load()
    } catch (error) {
      setNotice({ kind: 'error', text: errorMessage(error) })
    } finally {
      setSaving(false)
    }
  }

  const verify = async (id: string) => {
    setBusyId(id)
    setNotice(null)
    try {
      await kfApi.verifyChannel(id)
      setNotice({ kind: 'ok', text: '自检通过：客服账号已在线' })
      await load()
    } catch (error) {
      setNotice({ kind: 'error', text: errorMessage(error) })
      await load()
    } finally {
      setBusyId(null)
    }
  }

  const disable = async (id: string) => {
    setBusyId(id)
    setNotice(null)
    try {
      await kfApi.disableChannel(id)
      setNotice({ kind: 'ok', text: '已停用：该渠道不再接收新会话' })
      if (link?.channelId === id) setLink(null)
      await load()
    } catch (error) {
      setNotice({ kind: 'error', text: errorMessage(error) })
    } finally {
      setBusyId(null)
    }
  }

  const makeLink = async (id: string) => {
    setBusyId(id)
    setNotice(null)
    try {
      const res = await kfApi.createLink(id)
      const url = res.data.data?.url
      if (!url) throw new Error('没有生成客服链接，请重试')
      setLink({ channelId: id, url })
    } catch (error) {
      setNotice({ kind: 'error', text: errorMessage(error) })
    } finally {
      setBusyId(null)
    }
  }

  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setNotice({ kind: 'ok', text: '已复制' })
    } catch {
      setNotice({ kind: 'warn', text: '复制失败，请手动选中复制' })
    }
  }

  return (
    <div className="space-y-6" data-testid="kf-onboarding">
      <section className="rounded-lg border border-neutral-200" data-testid="kf-guide">
        <div className="border-b border-neutral-100 px-4 py-3">
          <h2 className="text-base font-semibold text-neutral-900">接入流程</h2>
          <p className="mt-1 text-sm text-neutral-500">
            下面四步都在企业微信后台完成；最后回到本页把三个值填上，保存后会自动自检。约 10 分钟。
          </p>
        </div>
        <ol className="divide-y divide-neutral-100">
          <Step n={1} title="准备企业微信">
            <p>
              先到
              <a className="mx-1 text-primary-700 underline" href="https://work.weixin.qq.com" target="_blank" rel="noreferrer">
                企业微信管理后台
              </a>
              完成企业认证，再开通微信客服。
            </p>
            <p className="text-neutral-500">
              我的企业 → 企业信息 → 企业认证；应用管理 → 微信客服 → 开通。认证通常要 1–3 个工作日，可先继续配下面的技术步骤。
            </p>
          </Step>
          <Step n={2} title="创建一个自建应用">
            <p>
              应用管理 → 应用 → 自建 → 创建应用（名称建议「智能客服」）。创建后到应用详情复制 <b>Secret</b>（只显示一次）。
            </p>
            <p className="text-neutral-500">企业 ID 在「我的企业 → 企业信息」；这个 ID 和 Secret 最后一步要用。</p>
          </Step>
          <Step n={3} title="开通权限、配回调与可信 IP">
            <p>把刚建的应用加入「微信客服 → 可调用接口的应用」，并在应用详情勾选「微信客服」权限。</p>
            <p>微信客服 → API 接收事件，填下面三个值（保存时企微会校验，平台会自动应答）：</p>
            <div className="space-y-1.5">
              <CopyRow label="回调 URL" value={setup.callbackUrl} testId="kf-callback-url" onCopy={copy} />
              <CopyRow label="Token" value={setup.callbackToken ?? ''} testId="kf-callback-token" onCopy={copy} />
              <CopyRow label="EncodingAESKey" value={setup.encodingAesKey ?? ''} testId="kf-callback-aeskey" onCopy={copy} />
            </div>
            <p className="mt-2">应用详情 → 企业可信IP，加入平台出口 IP：</p>
            <CopyRow label="可信 IP" value={setup.trustedIps.join(', ')} testId="kf-trusted-ips" onCopy={copy} />
            {!setup.callbackToken || !setup.encodingAesKey || setup.trustedIps.length === 0 ? (
              <p className="text-xs text-amber-700" data-testid="kf-setup-missing">
                回调 Token / EncodingAESKey / 可信 IP 还没下发，请联系平台管理员。
              </p>
            ) : null}
          </Step>
          <Step n={4} title="建客服账号，拿到客服账号 ID">
            <p>微信客服 → 客服账号 → 添加客服账号；在账号详情复制 <b>客服账号 ID</b>（以 wk 开头）。</p>
            <p className="text-neutral-500">
              给这个账号加接待人员，并确保至少一名接待人员登录过企业微信 —— 否则客户消息发不出去。
            </p>
          </Step>
        </ol>
      </section>

      {notice ? (
        <div
          data-testid="kf-notice"
          className={`rounded-lg border px-4 py-3 text-sm ${
            notice.kind === 'ok'
              ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
              : notice.kind === 'warn'
                ? 'border-amber-200 bg-amber-50 text-amber-800'
                : 'border-red-200 bg-red-50 text-red-700'
          }`}
        >
          {notice.text}
        </div>
      ) : null}

      <section className="rounded-lg border border-neutral-200">
        <div className="border-b border-neutral-100 px-4 py-3">
          <h2 className="text-base font-semibold text-neutral-900">最后一步：把三个值填回来</h2>
          <p className="mt-1 text-sm text-neutral-500">企业 ID、应用 Secret、客服账号 ID；保存后立即自检，通过后即为「已接通」。</p>
        </div>
        <div className="grid gap-4 px-4 py-4 sm:grid-cols-2">
          <label className="block text-sm">
            <span className="mb-1.5 block font-medium text-neutral-700">企业 ID</span>
            <input
              data-testid="kf-corp-id"
              className="h-9 w-full rounded border border-neutral-300 px-3 text-sm"
              placeholder="ww..."
              value={form.corpId}
              onChange={(e) => setForm({ ...form, corpId: e.target.value })}
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1.5 block font-medium text-neutral-700">客服账号 ID</span>
            <input
              data-testid="kf-open-kfid"
              className="h-9 w-full rounded border border-neutral-300 px-3 text-sm"
              placeholder="wk..."
              value={form.openKfid}
              onChange={(e) => setForm({ ...form, openKfid: e.target.value })}
            />
          </label>
          <label className="block text-sm sm:col-span-2">
            <span className="mb-1.5 block font-medium text-neutral-700">应用 Secret</span>
            <input
              data-testid="kf-secret"
              type="password"
              autoComplete="new-password"
              className="h-9 w-full rounded border border-neutral-300 px-3 text-sm"
              placeholder="只提交一次，保存后不会回显"
              value={form.secret}
              onChange={(e) => setForm({ ...form, secret: e.target.value })}
            />
          </label>
        </div>
        <div className="flex items-center justify-between border-t border-neutral-100 px-4 py-3">
          <p className="text-xs text-neutral-500">Secret 只在提交时使用；列表与自检都不会回传。</p>
          <button
            type="button"
            data-testid="kf-create"
            disabled={saving}
            onClick={() => void create()}
            className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
          >
            {saving ? '保存并自检中…' : '保存并自检'}
          </button>
        </div>
      </section>

      <section className="rounded-lg border border-neutral-200">
        <div className="border-b border-neutral-100 px-4 py-3">
          <h2 className="text-base font-semibold text-neutral-900">已接入渠道</h2>
          <p className="mt-1 text-sm text-neutral-500">自检通过后生成客服链接/二维码；停用后不再接收新会话，历史会话保留。</p>
        </div>
        {loading ? (
          <div className="px-4 py-8 text-center text-sm text-neutral-500">加载中…</div>
        ) : channels.length === 0 ? (
          <div className="px-4 py-8 text-center text-sm text-neutral-500" data-testid="kf-empty">
            还没有接入微信客服。接入后，顾客在微信里发消息就会进入智能客服的接待队列。
          </div>
        ) : (
          <ul className="divide-y divide-neutral-100">
            {channels.map((channel) => (
              <li key={channel.id} className="px-4 py-4" data-testid="kf-channel-row">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-sm font-medium text-neutral-900">{channel.openKfid}</span>
                      <span
                        data-testid={`kf-status-${channel.id}`}
                        className={`rounded-full px-2 py-0.5 text-xs ${
                          channel.status === 'active'
                            ? 'bg-emerald-50 text-emerald-700'
                            : channel.status === 'unauthorized'
                              ? 'bg-amber-50 text-amber-700'
                              : 'bg-neutral-100 text-neutral-600'
                        }`}
                      >
                        {displayEnum(STATUS_LABEL, channel.status)}
                      </span>
                    </div>
                    <p className="mt-1 break-all text-xs text-neutral-500">企业 ID：{channel.corpId}</p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {channel.status !== 'active' ? (
                      <button
                        type="button"
                        data-testid={`kf-verify-${channel.id}`}
                        disabled={busyId === channel.id}
                        onClick={() => void verify(channel.id)}
                        className="rounded border border-primary-200 px-3 py-1.5 text-xs font-medium text-primary-700 disabled:opacity-50"
                      >
                        重新自检
                      </button>
                    ) : (
                      <button
                        type="button"
                        data-testid={`kf-link-${channel.id}`}
                        disabled={busyId === channel.id}
                        onClick={() => void makeLink(channel.id)}
                        className="rounded border border-primary-200 px-3 py-1.5 text-xs font-medium text-primary-700 disabled:opacity-50"
                      >
                        生成客服链接
                      </button>
                    )}
                    {channel.status !== 'revoked' ? (
                      <button
                        type="button"
                        data-testid={`kf-disable-${channel.id}`}
                        disabled={busyId === channel.id}
                        onClick={() => void disable(channel.id)}
                        className="rounded border border-neutral-200 px-3 py-1.5 text-xs text-neutral-600 disabled:opacity-50"
                      >
                        停用
                      </button>
                    ) : null}
                  </div>
                </div>

                {link?.channelId === channel.id ? (
                  <div className="mt-4 flex flex-col gap-4 rounded-lg bg-neutral-50 p-4 sm:flex-row sm:items-center" data-testid="kf-link-panel">
                    <div className="rounded bg-white p-2">
                      <QRCodeSVG value={link.url} size={128} title="微信客服链接" />
                    </div>
                    <div className="min-w-0 flex-1 space-y-2">
                      <p className="text-sm text-neutral-700">让顾客扫码或点链接，直接在微信里发起咨询。</p>
                      <p className="break-all rounded bg-white px-2 py-1 text-xs text-neutral-500">{link.url}</p>
                      <div className="flex flex-wrap gap-2">
                        <button type="button" className="inline-flex items-center gap-1 rounded border border-neutral-200 px-2.5 py-1 text-xs" onClick={() => void copy(link.url)}>
                          <Copy className="h-3 w-3" />复制链接
                        </button>
                        <a href={link.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 rounded border border-neutral-200 px-2.5 py-1 text-xs">
                          <ExternalLink className="h-3 w-3" />打开
                        </a>
                      </div>
                    </div>
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>

      <div className="flex items-start gap-2 text-xs text-neutral-500">
        <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-600" />
        接入成功后，顾客消息会进入「在线接待」工作台；48 小时内最多回复 5 条，超出后请让顾客继续发消息或转人工。
      </div>
    </div>
  )
}

function Step({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <li className="flex gap-3 px-4 py-4">
      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary-50 text-xs font-semibold text-primary-700">
        {n}
      </span>
      <div className="min-w-0 space-y-1.5 text-sm text-neutral-700">
        <h3 className="font-medium text-neutral-900">{title}</h3>
        {children}
      </div>
    </li>
  )
}

function CopyRow({ label, value, testId, onCopy }: { label: string; value: string; testId: string; onCopy: (text: string) => void }) {
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-28 shrink-0 text-neutral-500">{label}</span>
      <code data-testid={testId} className="min-w-0 flex-1 truncate rounded bg-neutral-50 px-1.5 py-0.5 text-neutral-700">
        {value || '平台未配置'}
      </code>
      {value ? (
        <button type="button" className="inline-flex shrink-0 items-center gap-1 text-primary-700 underline" onClick={() => onCopy(value)}>
          <Copy className="h-3 w-3" />复制
        </button>
      ) : null}
    </div>
  )
}
