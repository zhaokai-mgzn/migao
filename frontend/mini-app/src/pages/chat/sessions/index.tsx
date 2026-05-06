import { useState, useCallback, useRef, useMemo } from 'react'
import { View, Text, ScrollView, Input } from '@tarojs/components'
import Taro, { usePullDownRefresh, useDidShow } from '@tarojs/taro'
import { useChatStore } from '../../../store/chatStore'
import type { Session } from '../../../types'
import './index.scss'

/**
 * 格式化会话时间
 * 今天 → HH:mm，昨天 → "昨天"，其他 → MM-DD
 */
function formatSessionTime(dateStr: string): string {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  const now = new Date()

  const isToday =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate()

  if (isToday) {
    const h = String(date.getHours()).padStart(2, '0')
    const m = String(date.getMinutes()).padStart(2, '0')
    return `${h}:${m}`
  }

  const yesterday = new Date(now)
  yesterday.setDate(yesterday.getDate() - 1)
  const isYesterday =
    date.getFullYear() === yesterday.getFullYear() &&
    date.getMonth() === yesterday.getMonth() &&
    date.getDate() === yesterday.getDate()

  if (isYesterday) return '昨天'

  const mm = String(date.getMonth() + 1).padStart(2, '0')
  const dd = String(date.getDate()).padStart(2, '0')
  return `${mm}-${dd}`
}

export default function SessionsPage() {
  const {
    sessions,
    isLoadingSessions,
    loadSessions,
    deleteSession,
    selectSession,
    createSession,
  } = useChatStore()

  const [searchText, setSearchText] = useState('')
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // 防抖搜索
  const handleSearchInput = useCallback((e: any) => {
    const value = e.detail.value as string
    if (debounceTimer.current) {
      clearTimeout(debounceTimer.current)
    }
    debounceTimer.current = setTimeout(() => {
      setSearchText(value)
    }, 300)
  }, [])

  // 过滤后的会话列表（按更新时间倒序）
  const filteredSessions = useMemo(() => {
    let list = [...sessions]
    // 按 updated_at 倒序
    list.sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
    if (searchText.trim()) {
      const keyword = searchText.trim().toLowerCase()
      list = list.filter(
        s =>
          (s.title || '').toLowerCase().includes(keyword) ||
          (s.last_message || '').toLowerCase().includes(keyword),
      )
    }
    return list
  }, [sessions, searchText])

  // 页面显示时加载
  useDidShow(() => {
    loadSessions()
  })

  // 下拉刷新
  usePullDownRefresh(async () => {
    await loadSessions()
    Taro.stopPullDownRefresh()
  })

  // 点击会话
  const handleSessionTap = useCallback(
    async (session: Session) => {
      await selectSession(session.id)
      Taro.switchTab({ url: '/pages/chat/index/index' })
    },
    [selectSession],
  )

  // 长按删除
  const handleSessionLongPress = useCallback(
    (session: Session) => {
      Taro.showActionSheet({
        itemList: ['删除会话'],
        success: (res) => {
          if (res.tapIndex === 0) {
            Taro.showModal({
              title: '确认删除',
              content: `确定要删除该会话吗？`,
              confirmColor: '#FF4D4F',
              success: (modalRes) => {
                if (modalRes.confirm) {
                  deleteSession(session.id)
                }
              },
            })
          }
        },
      })
    },
    [deleteSession],
  )

  // 新建会话
  const handleCreateSession = useCallback(async () => {
    await createSession()
    Taro.switchTab({ url: '/pages/chat/index/index' })
  }, [createSession])

  return (
    <View className='sessions-page'>
      {/* 搜索栏 */}
      <View className='sessions-search'>
        <View className='sessions-search__input-wrap'>
          <Text className='sessions-search__icon'>🔍</Text>
          <Input
            className='sessions-search__input'
            type='text'
            placeholder='搜索会话...'
            placeholderClass='sessions-search__placeholder'
            onInput={handleSearchInput}
            confirmType='search'
          />
        </View>
      </View>

      {/* 会话列表 */}
      <ScrollView
        className='sessions-list'
        scrollY
        enhanced
        showScrollbar={false}
      >
        {isLoadingSessions && sessions.length === 0 ? (
          <View className='sessions-loading'>
            <Text className='sessions-loading__text'>加载中...</Text>
          </View>
        ) : filteredSessions.length === 0 ? (
          <View className='sessions-empty'>
            <Text className='sessions-empty__icon'>💬</Text>
            <Text className='sessions-empty__text'>暂无会话记录</Text>
            <View className='sessions-empty__btn' onClick={handleCreateSession}>
              <Text className='sessions-empty__btn-text'>开始对话</Text>
            </View>
          </View>
        ) : (
          filteredSessions.map(session => (
            <View
              key={session.id}
              className='session-item'
              hoverClass='session-item--hover'
              onClick={() => handleSessionTap(session)}
              onLongPress={() => handleSessionLongPress(session)}
            >
              <View className='session-item__content'>
                <View className='session-item__header'>
                  <Text className='session-item__title'>
                    {session.title || '小布'}
                  </Text>
                  <Text className='session-item__time'>
                    {formatSessionTime(session.updated_at)}
                  </Text>
                </View>
                <Text className='session-item__preview'>
                  {session.last_message || '暂无消息'}
                </Text>
              </View>
            </View>
          ))
        )}
      </ScrollView>

      {/* 底部新建按钮 */}
      <View className='sessions-footer'>
        <View className='sessions-footer__btn' onClick={handleCreateSession}>
          <Text className='sessions-footer__btn-text'>+ 新建会话</Text>
        </View>
      </View>
    </View>
  )
}
