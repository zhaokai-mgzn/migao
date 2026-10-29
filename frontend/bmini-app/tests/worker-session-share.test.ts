// case_ids: BM-034
/**
 * 手持标签机：`/b/` 工人首页登录与 `/w/` 报工页共用一份工人 session（issue #8089）。
 *
 * 两边都发 `X-Worker-Session-Id`，但键不同：
 * - bmini（Taro H5）：`worker_session_id`（落盘形态 `{"data":...}`）
 * - worker-h5：`migao:worker-h5:session`
 * ⇒ bmini 登录后必须镜像到 H5 键，否则工人扫完码进 `/w/` 还要再登一次；登出/401 必须一起清。
 */
import {
  clearH5WorkerSession,
  clearWorkerSession,
  H5_WORKER_SESSION_KEY,
  mirrorWorkerSessionToH5,
} from '../src/utils/workerSession'

describe('手持机工人会话共享（/b/ ⇄ /w/）', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  test('bmini 登录后把工人身份镜像到 /w/ 的会话键', () => {
    mirrorWorkerSessionToH5({
      session_id: 's1',
      worker_id: 'w1',
      worker_no: 'W1',
      worker_name: '张三',
      idle_minutes: 15,
    })

    expect(JSON.parse(localStorage.getItem(H5_WORKER_SESSION_KEY) as string)).toEqual({
      sessionId: 's1',
      workerId: 'w1',
      workerNo: 'W1',
      workerName: '张三',
      idleMinutes: 15,
      idleExpiresAt: null,
    })
  })

  test('登出工人身份同时清 /w/ 镜像（不留上一个人的身份）', () => {
    mirrorWorkerSessionToH5({ session_id: 's1' })
    clearWorkerSession()

    expect(localStorage.getItem(H5_WORKER_SESSION_KEY)).toBeNull()
  })

  test('单独清镜像也只清镜像键', () => {
    mirrorWorkerSessionToH5({ session_id: 's1' })
    clearH5WorkerSession()

    expect(localStorage.getItem(H5_WORKER_SESSION_KEY)).toBeNull()
  })
})
