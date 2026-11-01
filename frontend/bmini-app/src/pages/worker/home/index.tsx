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
 * 2. **工人功能入口**（拍照入库 / 补打入库标签 / 拍照发货 / 待发货单 / 返工记录）都走既有页面与
 *    既有路由常量（`utils/inbound/gaps.ts` 是路由单一真值，本页不写第二份字面量）；
 *    🔴 **「扫码报工」入口已移除**（2026-10-27 用户逐字「把工人菜单页面的扫码报工菜单移除掉了，
 *    直接用其他 app 的扫一扫功能替代」，issue #7920）：工人用**微信 / 手机相机**扫纸上的码
 *    ⇒ 服务端 302 到 `/b/?t=<token>` ⇒ 启动器 redirectTo 报工页（#7879 起就是落地面）。
 *    本页因此**不再发射**报工页入口 —— 报工页由一个**外部扫码**到达，不由菜单点进去；
 *    🔴 **入口显隐由「工人端菜单」开关决定**（`utils/workerMenu`）：读不到 ⇒ fail-open 全开；
 *    🔴 **待处理数**（issue #7921）：待发货单 / 返工记录两条入口标题上带红色数字（= 服务端列表行数，
 *    仅 >0 时显示；读不到 / 失败**不显示**，绝不冒充 0）；
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
 * **身份条（谁在干活 + 退出）+ 行卡（标题 + 一句「拿它干什么」）**。
 * （原「唯一主按钮『扫码报工』」已随报工页下架删除，理由见上面第 2 条。）
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
  PIECEWORK_PAGE_ROUTE,
  REPRINT_PAGE_ROUTE,
  REWORK_PAGE_ROUTE,
  SHIPMENT_ORDERS_PAGE_ROUTE,
  SHIPMENT_PAGE_ROUTE,
  STOCK_PAGE_ROUTE,
  WORKER_HOME_LOGIN_REQUIRED,
  WORKER_LOGIN_ROUTE,
} from '../../../utils/inbound/gaps'
import { fetchWorkerPages } from '../../../services/workerService'
import { listReadyShipmentOrders } from '../../../services/workerShipmentOrdersService'
import { listWorkerReworkOrders } from '../../../services/workerReworkService'
import {
  WORKER_MENU_KEYS,
  menuVisible,
  REWORK_PAGE_KEY,
  STOCK_PAGE_KEY,
  TO_SHIP_PAGE_KEY,
} from '../../../utils/workerMenu'

/** 读不到菜单开关时给工人的一句话（不摆内部键；文案守卫只扫 src/pages/**，故写在页内）。 */
export const PAGES_UNREAD_NOTICE = '未能读取本机菜单开关，已按全部菜单显示；若与本机应开的不符，请找管理员'
import './index.scss'

export default function WorkerHomePage() {
  /** 本机有没有工人身份（本地判据，只决定「渲染工人功能」还是「引导去登录」） */
  const workerReady = hasWorkerSession()
  const [worker, setWorker] = useState<CurrentWorker | null>(null)
  const [message, setMessage] = useState('')
  // 商家后台「设置工人端菜单」的**唯一**消费点（issue #7812）：null = 还没读到；
  // `pagesUnread` = 读不到（网络 / 5xx）⇒ fail-open 全开 + 一句显式提示。
  const [pages, setPages] = useState<string[] | null>(null)
  const [pagesUnread, setPagesUnread] = useState(false)

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

  // 页面开关：只决定**入口显不显示**（不是访问拦截）；读不到 ⇒ 全开 + 提示，绝不把活挡掉
  useEffect(() => {
    if (!worker) return
    void fetchWorkerPages().then((res) => {
      if (res.unauthorized) {
        clearWorkerSession()
        setWorker(null)
        return
      }
      setPages(res.pages)
      setPagesUnread(res.unread)
    })
  }, [worker])

  const showToShip = menuVisible(pages, pagesUnread, TO_SHIP_PAGE_KEY)
  const showShipment = menuVisible(pages, pagesUnread, WORKER_MENU_KEYS.shipment)
  const showRework = menuVisible(pages, pagesUnread, REWORK_PAGE_KEY)
  // 库存修正（issue #8104）：物料组的一张行卡 —— 这一批实际还剩多少，工人当场改。
  const showStock = menuVisible(pages, pagesUnread, STOCK_PAGE_KEY)
  // 我的计件（issue #7934）：显隐键 = 工人档案的 `piecework`（后端 `WorkerPages` 闭词表里**本来就有**
  // 这个键 —— 此前只有 H5 `/w/piecework.html` 消费它）。本卡把它归位到工人菜单页。
  const showPiecework = menuVisible(pages, pagesUnread, WORKER_MENU_KEYS.piecework)

  /**
   * 🔴 待处理数（issue #7921）。服务端**没有**计数端点 ⇒ 复用两个既有只读列表端点现算行数
   * （`GET /api/worker/shipment/orders` 的 `items` / `GET /api/worker/production/rework-orders`
   * 的 `orders`），**只在这条入口可见时才请求**。
   *
   * 口径：`null` = 没读到（不显示）；`0` = 读到了、真的没有（也不显示数字）；
   * `>0` = 显示红色数字。读失败**绝不**回落成 0（那是在替服务端断言「没有待处理的活」）。
   */
  const [pendingToShip, setPendingToShip] = useState<number | null>(null)
  const [pendingRework, setPendingRework] = useState<number | null>(null)

  // 🔴 菜单还没读到 = `menuVisible` 的 fail-open 期（全开）⇒ 这时候按「全开」去请求，
  // 会给没有该页权限的工人打出 403，手机照 `request.ts` 弹一句「无权限访问」
  // （真机读数 2026-11-01：王建国 W2005 首页 `GET /api/worker/production/rework-orders` 403）。
  // 计数只是**补充信息**，等菜单落定再取 —— 不是把入口挡掉（显隐仍按 fail-open 显示）。
  const pagesSettled = pages !== null || pagesUnread
  useEffect(() => {
    if (!worker || !pagesSettled) {
      setPendingToShip(null)
      setPendingRework(null)
      return
    }
    let alive = true
    if (showToShip) {
      void listReadyShipmentOrders().then((res) => {
        if (!alive) return
        setPendingToShip(res.success ? (res.data?.items ?? []).length : null)
      })
    } else {
      setPendingToShip(null)
    }
    if (showRework) {
      void listWorkerReworkOrders().then((res) => {
        if (!alive) return
        setPendingRework(res.success ? (res.data?.orders ?? []).length : null)
      })
    } else {
      setPendingRework(null)
    }
    return () => {
      alive = false
    }
  }, [worker, pagesSettled, showToShip, showRework])

  /**
   * 引导去**工人登录页**（issue #8194）：落在 `pages/worker/login/index` —— 它渲染的是与终端
   * `/w/` 逐字一致的共享表单 `WorkerLoginForm`，与扫码报工页未登录时就地渲染的是**同一份**。
   * （三角色登录页的工人 tab 仍是常规入口，本页不再拿它当工人的登录引导。）
   */
  const goWorkerLogin = useCallback(() => {
    Taro.navigateTo({ url: WORKER_LOGIN_ROUTE })
  }, [])

  const exitWorker = useCallback(async () => {
    // 先结束服务端 session（幂等），再清本机 —— 只清本机会让下一个人记到上一个人头上
    await workerLogout()
    clearWorkerSession()
    // 退出后同样回工人登录页（同一张表单；登录页在页面栈只有自己时会回本页）
    Taro.redirectTo({ url: WORKER_LOGIN_ROUTE })
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
          {pagesUnread ? (
            <Text className='worker-home__message' data-testid='worker-home-pages-unread'>
              {PAGES_UNREAD_NOTICE}
            </Text>
          ) : null}

          {/* 🔴 入口按**商家后台的工人端菜单**显隐（issue #7812；商家反馈「勾了却没变」）。
              语义 = 菜单显隐、不是访问拦截；读不到页面集 ⇒ fail-open 全开（见 utils/workerMenu）。
              仍然是**静态字面锚点**（不走数组 + map）：入口可达性守卫按 `Taro.navigateTo({ url: <常量> })`
              静态证明「页面有入口」，数据驱动会让它解析不到。 */}
          {/* 🔴 「扫码报工」行卡已删除（2026-10-27 用户逐字「把工人菜单页面的扫码报工菜单移除掉了，
              直接用其他 app 的扫一扫功能替代」，issue #7920）：扫纸上的码由**微信 / 手机相机**发起
              ⇒ 服务端 302 到 `/b/?t=<token>` ⇒ 启动器 redirectTo 报工页。这里再放一个入口，
              只会把工人带进一个「没有码可解」的页面（此前落地只剩手输框，正是本单的现场）。 */}

          {/* 拍照入库 / 补打入库标签 = 工人面**固有**能力（后端没有页面键）⇒ 恒显示 */}
          <View
            className='worker-home__entry'
            onClick={() => Taro.navigateTo({ url: INBOUND_PAGE_ROUTE })}
          >
            <View className='worker-home__entry-bar worker-home__entry-bar--b' />
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
            <View className='worker-home__entry-bar worker-home__entry-bar--c' />
            <View className='worker-home__entry-body'>
              <Text className='worker-home__entry-text'>补打入库标签</Text>
              <Text className='worker-home__entry-sub'>标签丢了 / 磨花了</Text>
            </View>
            <Text className='worker-home__entry-go'>›</Text>
          </View>

          {/* 库存修正（issue #8104；用户 2026-10-29：「手机端还要增加一个库存修正的功能……
              允许工人对某个批次的布匹进行修正」）。显隐键 = 工人档案的 `stock`（默认开、可逐人关）。
              入口是**静态字面锚点**（`Taro.navigateTo({ url: STOCK_PAGE_ROUTE })`）：
              入口可达性守卫按它静态证明「页面有入口」，数据驱动会让它解析不到。 */}
          {showStock ? (
          <View
            className='worker-home__entry'
            onClick={() => Taro.navigateTo({ url: STOCK_PAGE_ROUTE })}
          >
            <View className='worker-home__entry-bar worker-home__entry-bar--a' />
            <View className='worker-home__entry-body'>
              <Text className='worker-home__entry-text'>库存修正</Text>
              <Text className='worker-home__entry-sub'>这一批实际剩多少 ⇒ 按实盘改过来</Text>
            </View>
            <Text className='worker-home__entry-go'>›</Text>
          </View>
          ) : null}

          {showShipment ? (
          <View
            className='worker-home__entry'
            onClick={() => Taro.navigateTo({ url: SHIPMENT_PAGE_ROUTE })}
          >
            <View className='worker-home__entry-bar worker-home__entry-bar--d' />
            <View className='worker-home__entry-body'>
              <Text className='worker-home__entry-text'>拍照发货</Text>
              <Text className='worker-home__entry-sub'>拍运单 / 商品标签 ⇒ 生成发货单</Text>
            </View>
            <Text className='worker-home__entry-go'>›</Text>
          </View>
          ) : null}

          {/* 待发货单（issue #7806 P1a；门控键 `to_ship` 由 #7814 落地）：与「拍照发货」分开勾选 ——
              前者是名单 + 标签（读），后者是发出去（写）。 */}
          {showToShip ? (
          <View
            className='worker-home__entry'
            onClick={() => Taro.navigateTo({ url: SHIPMENT_ORDERS_PAGE_ROUTE })}
          >
            <View className='worker-home__entry-bar worker-home__entry-bar--a' />
            <View className='worker-home__entry-body'>
              <View className='worker-home__entry-head'>
                <Text className='worker-home__entry-text'>待发货单</Text>
                {pendingToShip !== null && pendingToShip > 0 ? (
                  <Text className='worker-home__badge' data-testid='worker-home-badge-to-ship'>
                    {pendingToShip}
                  </Text>
                ) : null}
              </View>
              <Text className='worker-home__entry-sub'>全部完工的单 ⇒ 看收货人 / 电话 / 地址 / 物流</Text>
            </View>
            <Text className='worker-home__entry-go'>›</Text>
          </View>
          ) : null}

          {/* 返工记录（issue #7921）：显隐键 = 工人档案的 `rework`（商家面名字「返工记录」，
              后端 `WorkerPages.optionalPages()` 逐人开）。与「待发货单」同类 = 只读名单 + 待处理数。 */}
          {showRework ? (
          <View
            className='worker-home__entry'
            onClick={() => Taro.navigateTo({ url: REWORK_PAGE_ROUTE })}
          >
            <View className='worker-home__entry-bar worker-home__entry-bar--b' />
            <View className='worker-home__entry-body'>
              <View className='worker-home__entry-head'>
                <Text className='worker-home__entry-text'>返工记录</Text>
                {pendingRework !== null && pendingRework > 0 ? (
                  <Text className='worker-home__badge' data-testid='worker-home-badge-rework'>
                    {pendingRework}
                  </Text>
                ) : null}
              </View>
              <Text className='worker-home__entry-sub'>报过返工的加工单 ⇒ 看返工笔数 / 原因 / 工序</Text>
            </View>
            <Text className='worker-home__entry-go'>›</Text>
          </View>
          ) : null}

          {/* 我的计件（issue #7934）：显隐键 = 工人档案的 `piecework`；行卡放在设计稿的「我的」组
              （物料 / 出货之后）—— 它是这一天干完才看的东西，不占干活动线的前排。
              🔴 入口是**静态字面锚点**（`Taro.navigateTo({ url: PIECEWORK_PAGE_ROUTE })`）：
              入口可达性守卫按它静态证明「页面有入口」，数据驱动会让它解析不到。 */}
          {showPiecework ? (
          <View
            className='worker-home__entry'
            onClick={() => Taro.navigateTo({ url: PIECEWORK_PAGE_ROUTE })}
          >
            <View className='worker-home__entry-bar worker-home__entry-bar--d' />
            <View className='worker-home__entry-body'>
              <Text className='worker-home__entry-text'>我的计件</Text>
              <Text className='worker-home__entry-sub'>本月做了多少、这一笔怎么算的</Text>
            </View>
            <Text className='worker-home__entry-go'>›</Text>
          </View>
          ) : null}
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
