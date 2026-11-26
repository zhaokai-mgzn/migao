'use client'

import { useCallback, useEffect, useState } from 'react'
import { QRCodeSVG } from 'qrcode.react'
import { CheckCircle2, Copy, ExternalLink, ShieldCheck } from 'lucide-react'
import { kfApi, type KfChannelView } from '@/lib/kf-api'
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
  const [callbackUrl, setCallbackUrl] = useState('')
  const [link, setLink] = useState<{ channelId: string; url: string } | null>(null)

  useEffect(() => {
    setCallbackUrl(`${window.location.origin}/api/kf/callback`)
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
      <div className="rounded-lg border border-neutral-200 bg-neutral-50 px-4 py-3 text-sm text-neutral-600">
        <div className="flex items-start gap-2">
          <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-primary-600" />
          <div className="space-y-1">
            <p>接入前请在企业微信后台确认：已开通「微信客服」、应用有「通过 API 管理微信客服账号」权限、至少一名接待人员已激活企业微信。</p>
            <p>
              回调地址：<code className="rounded bg-white px-1.5 py-0.5 text-xs" data-testid="kf-callback-url">{callbackUrl || '加载中…'}</code>
              {callbackUrl ? (
                <button type="button" className="ml-2 inline-flex items-center gap-1 text-primary-700 underline" onClick={() => void copy(callbackUrl)}>
                  <Copy className="h-3 w-3" />复制
                </button>
              ) : null}
            </p>
            <p className="text-xs text-neutral-500">回调 Token / EncodingAESKey 由平台部署配置，请向平台管理员索取后在企微后台填入同一组值。</p>
          </div>
        </div>
      </div>

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
          <h2 className="text-base font-semibold text-neutral-900">接入新的微信客服账号</h2>
          <p className="mt-1 text-sm text-neutral-500">填写企业微信的企业 ID 与客服账号 ID；保存后立即自检，通过后即为「已接通」。</p>
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
            还没有接入微信客服。接入后，顾客在微信里发消息就会进入米宝的接待队列。
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
