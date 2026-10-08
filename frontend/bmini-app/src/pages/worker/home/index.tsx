/**
 * 工人首页（issue #6467 切片 1）—— **纯工人设备**（有工人 session、无商家会话）的落地页。
 *
 * ## 为什么必须有这一页
 * 现场（2026-10-07 生产）：管理员账号在 H5 点「完成报工」⇒ 报工写入口（`completeByScan`）401
 * （它只认工号 + PIN 签发的工人身份）+ 请求层把商家登录态清掉、踢回登录页。
 * 症状的根因之一是**工人身份没有落点**：工人登录后只能落进商家的 tabBar，而工人零商家权限
 * （`/api/admin/**` 的拒绝集合含 `worker`）⇒ 看见商家菜单只会 403 / 空页；且
 * `Taro.switchTab` **只能**落 tabBar 页 ⇒ 工人登录成功只能 `redirectTo` 一个非 tabBar 的工人页。
 *
 * ## 页面上的四条纪律
 * 1. **身份卡读服务端**（`fetchCurrentWorker()`）：页头显示的正是「这笔活会记到谁头上」
 *    = 计件工资的凭证 ⇒ 前端自己拼一个名字就是把凭证交给客户端。服务端读不到就**回落成未登录**
 *    （绝不静默留着上一个人的名字）；
 * 2. **三件工人功能**（扫码报工 / 拍照入库 / 补打入库标签）都走既有页面与既有路由常量
 *    （`utils/inbound/gaps.ts` 是路由单一真值，本页不写第二份字面量）；
 * 3. **一件商家面都不出现**：问黄金策 / 数据 / 坐席 / 管理面 4 项都不在本页（工人点了只会 403）；
 * 4. **退出工人身份** = `workerLogout()`（服务端留 `end_reason=logout` 痕）+ `clearWorkerSession()`
 *    ⇒ 回登录页的**工人入口**（共用 PAD 场景：下一个人接着用）。
 */
import { useCallback, useEffect, useState } from 'react'
import { View, Text, Button } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { fetchCurrentWorker, workerLogout } from '../../../services/workerService'
import {
  clearWorkerSession,
  hasWorkerSession,
  type CurrentWorker,
} from '../../../utils/workerSession'
import {
  INBOUND_PAGE_ROUTE,
  PRODUCTION_PAGE_ROUTE,
  REPRINT_PAGE_ROUTE,
  WORKER_HOME_LOGIN_REQUIRED,
  WORKER_TAB_LOGIN_ROUTE,
} from '../../../utils/inbound/gaps'
import './index.scss'

export default function WorkerHomePage() {
  /** 本机有没有工人身份（本地判据，只决定「渲染工人功能」还是「引导去登录」） */
  const workerReady = hasWorkerSession()
  const [worker, setWorker] = useState<CurrentWorker | null>(null)
  const [message, setMessage] = useState('')

  const refresh = useCallback(async () => {
    const res = await fetchCurrentWorker()
    if (res.success && res.data) {
      setWorker(res.data)
      setMessage('')
      return
    }
    // 服务端读不到当前工人（401 / 闲置超时 / 未登录）⇒ 回落成「未登录」，
    // 绝不静默保留上一个人的名字（页头就是计件归属的可见面）。
    clearWorkerSession()
    setWorker(null)
    setMessage(res.message || '')
  }, [])

  useEffect(() => {
    if (workerReady) void refresh()
  }, [refresh, workerReady])

  /** 引导去登录页的**工人入口**（`?tab=worker` 直达第三 tab） */
  const goWorkerLogin = useCallback(() => {
    Taro.navigateTo({ url: WORKER_TAB_LOGIN_ROUTE })
  }, [])

  const exitWorker = useCallback(async () => {
    // 先结束服务端 session（幂等），再清本机 —— 只清本机会让下一个人记到上一个人头上
    await workerLogout()
    clearWorkerSession()
    Taro.redirectTo({ url: WORKER_TAB_LOGIN_ROUTE })
  }, [])

  return (
    <View className='worker-home'>
      <View className='worker-home__card'>
        <Text className='worker-home__card-title'>当前工人</Text>
        {worker ? (
          <>
            <Text className='worker-home__worker-no'>{`工号 ${worker.worker_no || '—'}`}</Text>
            <Text className='worker-home__worker-name'>{worker.worker_name || '未署名'}</Text>
          </>
        ) : (
          <Text className='worker-home__worker-name'>未登录工人身份</Text>
        )}
        {message ? <Text className='worker-home__message'>{message}</Text> : null}
      </View>

      {worker ? (
        <>
          <View className='worker-home__entries'>
            <View
              className='worker-home__entry'
              onClick={() => Taro.navigateTo({ url: PRODUCTION_PAGE_ROUTE })}
            >
              <Text className='worker-home__entry-text'>扫码报工</Text>
            </View>
            <View
              className='worker-home__entry'
              onClick={() => Taro.navigateTo({ url: INBOUND_PAGE_ROUTE })}
            >
              <Text className='worker-home__entry-text'>拍照入库</Text>
            </View>
            <View
              className='worker-home__entry'
              onClick={() => Taro.navigateTo({ url: REPRINT_PAGE_ROUTE })}
            >
              <Text className='worker-home__entry-text'>补打入库标签</Text>
            </View>
          </View>

          <Button className='worker-home__exit' onClick={exitWorker}>
            退出工人身份
          </Button>
        </>
      ) : (
        <View className='worker-home__gate'>
          <Text className='worker-home__gate-text'>{WORKER_HOME_LOGIN_REQUIRED}</Text>
          <Button className='worker-home__login' onClick={goWorkerLogin}>
            去登录工人身份
          </Button>
        </View>
      )}
    </View>
  )
}
