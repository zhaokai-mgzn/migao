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
 * 2. **四件工人功能**（扫码报工 / 拍照入库 / 补打入库标签 / 拍照发货）都走既有页面与既有路由常量
 *    （`utils/inbound/gaps.ts` 是路由单一真值，本页不写第二份字面量）；
 * 3. **一件商家面都不出现**：问黄金策 / 数据 / 坐席 / 管理面 4 项都不在本页（工人点了只会 403）；
 * 4. **退出工人身份** = `workerLogout()`（服务端留 `end_reason=logout` 痕）+ `clearWorkerSession()`
 *    ⇒ 回登录页的**工人入口**（共用 PAD 场景：下一个人接着用）。
 *
 * ## 第 5 条（2026-10-13，issue #6858）：布局按**菜单**设计，不按"任务页"设计
 *
 * 用户逐字：「这版本的菜单主页不太符合我们整体样式设计，为什么搞成纯白色背景了？」
 * + 「工人登录后的页面菜单很少，通常只能看到 1-4 个菜单」。
 * ⇒ 结构按 2026-10-12 已裁定的菜单设计（`docs/design/worker-home-menu.md`）的语言重排，三个候选
 * （V1 大卡列表 / V2 宫格瓦片 / V3 分组清单）由用户**选定 V1**：
 * **身份条（谁在干活 + 退出）+ 唯一主按钮「扫码报工」+ 行卡（标题 + 一句「拿它干什么」）**。
 * 为什么 V1：条目只有 1~4 条时，宫格会出现「2+1」孤儿格、分组会出现「标题底下孤零零一张卡」，
 * 行卡在 1~4 条都成立，且主按钮永远在第一屏（`docs/design/worker-home-menu.md` §3.1/§3.2）。
 * 🔴 行为一字未改：身份仍读服务端、路由仍来自 `gaps.ts`、退出仍是 `workerLogout()` + 清本机 + 回工人入口。
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
  SHIPMENT_PAGE_ROUTE,
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

  /** 常驻主按钮：扫码报工（`report` 面 = 报工页，一天几十次的那一下） */
  const goReport = useCallback(() => {
    Taro.navigateTo({ url: PRODUCTION_PAGE_ROUTE })
  }, [])

  const exitWorker = useCallback(async () => {
    // 先结束服务端 session（幂等），再清本机 —— 只清本机会让下一个人记到上一个人头上
    await workerLogout()
    clearWorkerSession()
    Taro.redirectTo({ url: WORKER_TAB_LOGIN_ROUTE })
  }, [])

  return (
    <View className='worker-home'>
      {/* 身份条：谁在干活（姓名 / 工号读服务端 = 计件归属的可见面）+ 退出 */}
      <View className='worker-home__card'>
        <View className='worker-home__who'>
          <Text className='worker-home__worker-name'>
            {worker ? worker.worker_name || '未署名' : '未登录工人身份'}
          </Text>
          {worker ? (
            <Text className='worker-home__worker-no'>{`工号 ${worker.worker_no || '—'}`}</Text>
          ) : null}
          <Text className='worker-home__worker-status'>
            {worker ? '本机登录中' : '本机没有工人身份'}
          </Text>
        </View>
        {worker ? (
          <Button className='worker-home__ghost' onClick={exitWorker}>
            退出
          </Button>
        ) : null}
        {message ? <Text className='worker-home__message'>{message}</Text> : null}
      </View>

      {worker ? (
        <>
          {/* 常驻主按钮：全屏**唯一** primary（菜单设计 §3.2） */}
          <Button className='worker-home__primary' onClick={goReport}>
            <Text className='worker-home__primary-title'>扫码报工</Text>
            <Text className='worker-home__primary-sub'>扫一次码 = 报一道工序（先报工再生产，做完不用再扫）</Text>
          </Button>

          <Text className='worker-home__section'>其他功能</Text>

          {/* 🔴 三张行卡**逐条显式**写（不走数组 + `.map()`）：本仓的入口可达性守卫
              （`tests/page-entry-reachability.test.ts`）按 `Taro.navigateTo({ url: <路由常量> })`
              这类**字面锚点**静态证明「页面有入口」，数据驱动会让它解析不到 ⇒ 5 条判据一起红
              （实测：本项目 #6858 第一版用 `WORKER_ENTRIES.map()` 时踩到，守卫是对的）。 */}
          <View
            className='worker-home__entry'
            onClick={() => Taro.navigateTo({ url: INBOUND_PAGE_ROUTE })}
          >
            <View className='worker-home__entry-bar worker-home__entry-bar--a' />
            <View className='worker-home__entry-body'>
              <Text className='worker-home__entry-text'>拍照入库</Text>
              <Text className='worker-home__entry-sub'>拍上游标签 ⇒ 过账 ⇒ 打标签</Text>
            </View>
            <Text className='worker-home__entry-go'>›</Text>
          </View>

          <View
            className='worker-home__entry'
            onClick={() => Taro.navigateTo({ url: REPRINT_PAGE_ROUTE })}
          >
            <View className='worker-home__entry-bar worker-home__entry-bar--b' />
            <View className='worker-home__entry-body'>
              <Text className='worker-home__entry-text'>补打入库标签</Text>
              <Text className='worker-home__entry-sub'>标签丢了 / 磨花了</Text>
            </View>
            <Text className='worker-home__entry-go'>›</Text>
          </View>

          {/* 第 3 条（issue #6761）：#5648 的后端与纯逻辑早已就绪，缺的就是这个入口 */}
          <View
            className='worker-home__entry'
            onClick={() => Taro.navigateTo({ url: SHIPMENT_PAGE_ROUTE })}
          >
            <View className='worker-home__entry-bar worker-home__entry-bar--c' />
            <View className='worker-home__entry-body'>
              <Text className='worker-home__entry-text'>拍照发货</Text>
              <Text className='worker-home__entry-sub'>拍运单 / 商品标签 ⇒ 生成发货单</Text>
            </View>
            <Text className='worker-home__entry-go'>›</Text>
          </View>
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
