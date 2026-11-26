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

export interface KfChannelCreateResult {
  channel: KfChannelView
  verified: boolean
  message: string
}

export const kfApi = {
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
