import { useCallback, useEffect, useRef, useState } from 'react'
import { View, Text, ScrollView, Input, Button } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import {
  getAgentSessionDetail,
  assignAgentSession,
  sendAgentReply,
  endAgentSession,
  type AgentSessionDetail,
  type AgentSessionMessage,
} from '../../../services/agentSessionService'
import './index.scss'

/**
 * 移动坐席会话详情（米宝商家端，issue #2977）
 *
 * 流程：待接管会话 → 「接管」绑定给自己（assign）→ 查看消息 → 输入回复 → 结束会话。
 * 轮询 10s 拉取新消息（wx.request 轮询，简单可靠，P0够用）。
 */
export default function SessionDetailPage() {
  const router = useRouter()
  const sessionId = router.params.id || ''

  const [detail, setDetail] = useState<AgentSessionDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [replyText, setReplyText] = useState('')
  const [sending, setSending] = useState(false)
  const [operating, setOperating] = useState(false)
  const scrollRef = useRef<any>(null)

  const load = useCallback(async () => {
    if (!sessionId) return
    const d = await getAgentSessionDetail(sessionId)
    if (d) setDetail(d)
    setLoading(false)
  }, [sessionId])

  useEffect(() => {
    load()
    // 10s 轮询新消息（会话详情页存活期间）
    const timer = setInterval(load, 10000)
    return () => clearInterval(timer)
  }, [load])

  // 新消息滚动到底部
  useEffect(() => {
    if (detail?.messages?.length) {
      setTimeout(() => scrollRef.current?.scrollIntoView?.({ block: 'end' }), 100)
    }
  }, [detail?.messages?.length])

  // 接管会话
  const handleAssign = useCallback(async () => {
    if (operating || !sessionId) return
    setOperating(true)
    const ok = await assignAgentSession(sessionId)
    setOperating(false)
    if (ok) {
      Taro.showToast({ title: '已接管', icon: 'success' })
      await load()
    } else {
      Taro.showToast({ title: '接管失败，可能已被其他客服接管', icon: 'none' })
    }
  }, [operating, sessionId, load])

  // 发送回复
  const handleSend = useCallback(async () => {
    const content = replyText.trim()
    if (!content || sending || !sessionId) return
    setSending(true)
    const ok = await sendAgentReply(sessionId, content)
    setSending(false)
    if (ok) {
      setReplyText('')
      await load()
    } else {
      Taro.showToast({ title: '发送失败，请重试', icon: 'none' })
    }
  }, [replyText, sending, sessionId, load])

  // 结束会话
  const handleEnd = useCallback(() => {
    if (operating || !sessionId) return
    Taro.showModal({
      title: '结束会话',
      content: '确认结束该会话？结束后将无法继续回复。',
      success: async (res) => {
        if (!res.confirm) return
        setOperating(true)
        const ok = await endAgentSession(sessionId)
        setOperating(false)
        if (ok) {
          Taro.showToast({ title: '已结束', icon: 'success' })
          setTimeout(() => Taro.navigateBack(), 800)
        } else {
          Taro.showToast({ title: '操作失败，请重试', icon: 'none' })
        }
      },
    })
  }, [operating, sessionId])

  const isAssigned = !!detail?.employeeId
  const canReply = detail && detail.status !== 'ended' && isAssigned
  const statusLabel = detail
    ? (detail.status === 'waiting' ? '待接管' : detail.status === 'active' ? '进行中' : detail.status === 'ended' ? '已结束' : '已转接')
    : ''

  // 渲染消息
  const renderMessage = (msg: AgentSessionMessage, idx: number) => {
    const isCustomer = msg.senderType === 'customer'
    const isSystem = msg.senderType === 'system'
    if (isSystem) {
      return (
        <View key={`${msg.id}-${idx}`} className='msg--system'>
          <Text className='msg--system__text'>{msg.content}</Text>
        </View>
      )
    }
    return (
      <View key={`${msg.id}-${idx}`} className={`msg ${isCustomer ? 'msg--customer' : 'msg--agent'}`}>
        <View className='msg__bubble'>
          <Text className='msg__text'>{msg.content}</Text>
          <Text className='msg__time'>{msg.createdAt ? msg.createdAt.slice(11, 16) : ''}</Text>
        </View>
      </View>
    )
  }

  return (
    <View className='detail-page'>
      {/* 会话头 */}
      <View className='detail-header'>
        <View className='detail-header__info'>
          <Text className='detail-header__name'>{detail?.customerName || '匿名客户'}</Text>
          <Text className='detail-header__status detail-header__status--${detail?.status}'>
            {statusLabel}
          </Text>
          {detail?.reason && <Text className='detail-header__reason'>{detail.reason}</Text>}
        </View>

        {/* 未接管 → 接管按钮；已接管 → 结束按钮 */}
        {detail && !isAssigned && detail.status !== 'ended' && (
          <Button className='detail-header__op' size='mini' type='primary' loading={operating} onClick={handleAssign}>
            接管
          </Button>
        )}
        {canReply && (
          <Button className='detail-header__op detail-header__op--end' size='mini' loading={operating} onClick={handleEnd}>
            结束
          </Button>
        )}
      </View>

      {/* 消息列表 */}
      <ScrollView scrollY className='detail-messages'>
        {loading ? (
          <View className='detail-loading'><Text>加载会话中...</Text></View>
        ) : !detail || detail.messages.length === 0 ? (
          <View className='detail-loading'><Text>暂无消息</Text></View>
        ) : (
          detail.messages.map(renderMessage)
        )}
      </ScrollView>

      {/* 输入区 */}
      {canReply && (
        <View className='detail-input'>
          <Input
            className='detail-input__field'
            value={replyText}
            onInput={e => setReplyText(e.detail.value)}
            placeholder='输入回复内容…'
            confirmType='send'
            onConfirm={handleSend}
          />
          <Button className='detail-input__send' size='mini' loading={sending} disabled={!replyText.trim()} onClick={handleSend}>
            发送
          </Button>
        </View>
      )}
    </View>
  )
}