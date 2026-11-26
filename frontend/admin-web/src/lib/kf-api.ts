import request from './request'
import type { ApiResponse } from '@/types'

// 微信客服渠道自助接入（issue #9230）
export interface KfChannelView {
  id: string
  corpId: string
  openKfid: string
  authMode: string
  status: 'active' | 'unauthorized' | 'expired' | 'revoked'
  createdAt?: string
  updatedAt?: string
}

export interface KfSetupInfo {
  callbackUrl: string
  callbackToken: string | null
  encodingAesKey: string | null
  trustedIps: string[]
}

export interface KfChannelCreateResult {
  channel: KfChannelView
  verified: boolean
  message: string
}

export const kfApi = {
  /** 接入页要客户复制到企微后台的部署级值（issue #9238）。 */
  getSetupInfo: () =>
    request.get<ApiResponse<KfSetupInfo>>('/api/admin/kf/channels/setup-info'),

  listChannels: () =>
    request.get<ApiResponse<KfChannelView[]>>('/api/admin/kf/channels'),

  createChannel: (data: { corpId: string; openKfid: string; secret: string }) =>
    request.post<ApiResponse<KfChannelCreateResult>>('/api/admin/kf/channels', {
      corp_id: data.corpId,
      open_kfid: data.openKfid,
      secret: data.secret,
    }),

  verifyChannel: (id: string) =>
    request.post<ApiResponse<KfChannelView>>(`/api/admin/kf/channels/${id}/verify`),

  disableChannel: (id: string) =>
    request.post<ApiResponse<KfChannelView>>(`/api/admin/kf/channels/${id}/disable`),

  createLink: (id: string, sceneParam?: string) =>
    request.post<ApiResponse<{ url: string }>>(`/api/admin/kf/channels/${id}/link`, {
      scene_param: sceneParam || undefined,
    }),
}
