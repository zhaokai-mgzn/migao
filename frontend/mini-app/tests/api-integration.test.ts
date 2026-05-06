/**
 * API 集成测试
 *
 * 覆盖: chatService 和 userService 的 API 调用逻辑
 */
import Taro from '@tarojs/taro'
import { STORAGE_KEYS } from '../src/utils/constants'

describe('chatService API', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    ;(Taro as any).__clearStorage()
    // 预设 Token
    Taro.setStorageSync(STORAGE_KEYS.TOKEN, 'test-token')
  })

  describe('createSession', () => {
    it('应发送 POST 创建会话', async () => {
      ;(Taro.request as jest.Mock).mockResolvedValueOnce({
        statusCode: 200,
        data: {
          success: true,
          data: { id: 's1', title: '新对话', created_at: '2024-01-01', updated_at: '2024-01-01' },
        },
      })

      const { createSession } = require('../src/services/chatService')
      const session = await createSession()

      expect(session.id).toBe('s1')
      expect(Taro.request).toHaveBeenCalledWith(
        expect.objectContaining({
          method: 'POST',
          data: expect.objectContaining({ platform: 'wechat_mini' }),
        }),
      )
    })

    it('创建失败应抛出错误', async () => {
      ;(Taro.request as jest.Mock).mockResolvedValueOnce({
        statusCode: 200,
        data: { success: false, error: { code: 'ERR', message: '服务器错误' } },
      })

      const { createSession } = require('../src/services/chatService')
      await expect(createSession()).rejects.toThrow('服务器错误')
    })
  })

  describe('getSessionList', () => {
    it('应发送 GET 获取会话列表', async () => {
      ;(Taro.request as jest.Mock).mockResolvedValueOnce({
        statusCode: 200,
        data: {
          success: true,
          data: { items: [{ id: 's1' }, { id: 's2' }], page: 1, size: 20, total: 2 },
        },
      })

      const { getSessionList } = require('../src/services/chatService')
      const result = await getSessionList()

      expect(result.items).toHaveLength(2)
    })
  })

  describe('deleteSession', () => {
    it('应发送 DELETE 删除会话', async () => {
      ;(Taro.request as jest.Mock).mockResolvedValueOnce({
        statusCode: 200,
        data: { success: true },
      })

      const { deleteSession } = require('../src/services/chatService')
      await deleteSession('s1')

      expect(Taro.request).toHaveBeenCalledWith(
        expect.objectContaining({
          method: 'DELETE',
        }),
      )
    })
  })

  describe('getSessionMessages', () => {
    it('应获取并格式化消息列表', async () => {
      ;(Taro.request as jest.Mock).mockResolvedValueOnce({
        statusCode: 200,
        data: {
          success: true,
          data: {
            session_id: 's1',
            messages: [
              { id: 'm1', session_id: 's1', role: 'user', content: '你好', created_at: '2024-01-01' },
              { id: 'm2', session_id: 's1', role: 'assistant', content: '你好！', created_at: '2024-01-01' },
            ],
          },
        },
      })

      const { getSessionMessages } = require('../src/services/chatService')
      const messages = await getSessionMessages('s1')

      expect(messages).toHaveLength(2)
      expect(messages[0].role).toBe('user')
      expect(messages[1].role).toBe('assistant')
    })
  })

  describe('getQuickActions', () => {
    it('应获取快捷操作列表', async () => {
      ;(Taro.request as jest.Mock).mockResolvedValueOnce({
        statusCode: 200,
        data: {
          success: true,
          data: {
            actions: [{ id: 'q1', name: '查订单', prompt: '查订单' }],
          },
        },
      })

      const { getQuickActions } = require('../src/services/chatService')
      const actions = await getQuickActions()

      expect(actions).toHaveLength(1)
      expect(actions[0].name).toBe('查订单')
    })

    it('获取失败应返回空数组', async () => {
      ;(Taro.request as jest.Mock).mockResolvedValueOnce({
        statusCode: 200,
        data: { success: false },
      })

      const { getQuickActions } = require('../src/services/chatService')
      const actions = await getQuickActions()

      expect(actions).toEqual([])
    })
  })
})

describe('userService API', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    ;(Taro as any).__clearStorage()
    Taro.setStorageSync(STORAGE_KEYS.TOKEN, 'test-token')
  })

  describe('getUserInfo', () => {
    it('应获取用户信息', async () => {
      ;(Taro.request as jest.Mock).mockResolvedValueOnce({
        statusCode: 200,
        data: {
          success: true,
          data: { id: 'u1', nickname: '测试用户', avatar: null, tenant_id: 1 },
        },
      })

      const { getUserInfo } = require('../src/services/userService')
      const user = await getUserInfo()

      expect(user.id).toBe('u1')
      expect(user.nickname).toBe('测试用户')
    })

    it('获取失败应抛出错误', async () => {
      ;(Taro.request as jest.Mock).mockResolvedValueOnce({
        statusCode: 200,
        data: { success: false, error: { code: 'ERR', message: '未登录' } },
      })

      const { getUserInfo } = require('../src/services/userService')
      await expect(getUserInfo()).rejects.toThrow('未登录')
    })
  })

  describe('updateUserInfo', () => {
    it('应更新用户信息', async () => {
      ;(Taro.request as jest.Mock).mockResolvedValueOnce({
        statusCode: 200,
        data: {
          success: true,
          data: { id: 'u1', nickname: '新昵称', avatar: 'url', tenant_id: 1 },
        },
      })

      const { updateUserInfo } = require('../src/services/userService')
      const user = await updateUserInfo({ nickname: '新昵称' })

      expect(user.nickname).toBe('新昵称')
      expect(Taro.request).toHaveBeenCalledWith(
        expect.objectContaining({
          method: 'PUT',
          data: { nickname: '新昵称' },
        }),
      )
    })
  })
})
