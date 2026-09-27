/**
 * **入口台账**：面向用户的每一个页面，「谁把它送到用户眼前」（issue #5052 实现 PR）
 *
 * ## 治的形态：「交付物做完了，却没有任何入口能走到它」（验收协议 v1.11 三问之②）
 *
 * 反面教材就在本仓、就在本单要接的那两条链路上：`src/utils/inbound/gaps.ts` 里的
 * `INBOUND_PAGE_ROUTE` / `REPRINT_PAGE_ROUTE` **被声明了**、被 `tests/inbound-page-platform-gaps.test.ts`
 * 的 G0 **比对过 `app.config.ts`**，却**没有任何一处跳转用它们** ⇒ 两页都"在册、可编译、有单测"，
 * 而工人**一步也走不到**。⇒ **「声明存在」不等于「可达」**：一条路由到底可达，判据必须是
 * 「**有一处真的在跳转**」，不是「有个常量写着它」。
 *
 * 本台账把「谁发射」写死；守卫 `tests/page-entry-reachability.test.ts` 只做两件事：
 * ① **未登记即红** —— `app.config.ts` 里每一个**非 tabBar** 页面都必须在册
 *    （tabBar 页面由**系统 tabBar** 承载，是机制而非声明 ⇒ 机械豁免，见 {@link TABBAR_REACHABLE}）；
 * ② **登记了没人指向也红** —— 每一条都必须能在 `from` 里找到**导航形态**
 *    （`navigateTo` / `redirectTo` / `switchTab` / `reLaunch` / 跨应用 `href`）**且**跳转里带着目标记号。
 *    只保留第 ① 条的话，"只声明"仍会绿 —— 那正是本单要拦的形态。
 *
 * ## 入口在**哪个应用**里都可以登记（跨应用入口也是一条真入口）
 *
 * `frontend/bmini-app`（h5 产物落在 `app.migaozn.com/b/`）与 `frontend/worker-h5`
 * （零依赖纯静态，落在 `app.migaozn.com/w/`）**同源同静态根**：工人手里常开的那个页面是 `/w/`
 * （他一天扫几十次洗水码报工），因此 `/w/` 上的两个链接就是工人面两页的**真实动线**入口
 * （设计 §5.4 的两条路选了 (a)，理由见 PR）。
 *
 * ## 边界（明确的，不要把本台账读成覆盖面更大的东西）
 *
 * ① **只保证「有导航形态指向它」**，不保证这条路径在**真机/线上**走得通（发布腿、nginx 面、
 *    工人会话是否已登录都不在本判据里）—— 那是发布后断言（`deploy/scripts/*-verify-served.sh`）
 *    与各页面自己的身份分流判据的事；
 * ② `via` 若是**动态记号**（`surface.route` / `reprintLandingUrl`），本台账只能保证
 *    「跳转语句里带着这个记号」；「这个记号确实解析成 `route`」由 `viaFile` 那一侧**另有一条**核验
 *    （见守卫的 L2），或者由该记号自己的既有守卫负责（管理面 4 项 = `tests/admin-surfaces-guard.test.ts`
 *    的 `ADMIN_SURFACES[].route` 逐值比对 `app.config.ts`）；
 * ③ tabBar 四页**机械豁免**，不在册：它们在 `app.config.ts` 的 `tabBar.list` 里，
 *    可达性由系统（微信 / Taro h5 的 tabbar）提供，不是谁"跳"过去的。
 */
import { INBOUND_PAGE_ROUTE, REPRINT_PAGE_ROUTE, WORKER_LOGIN_ROUTE } from './inbound/gaps'

/** 导航形态（守卫据此选正则；**不能**是新造的词 —— 形态本身就是判据的一部分） */
export type EntryNav = 'navigateTo' | 'redirectTo' | 'switchTab' | 'reLaunch' | 'href'

export interface PageEntry {
  /** 目标页面路由（bmini 页面路由；必须逐字出现在 `src/app.config.ts` 的 `pages` 里） */
  route: string
  /** **谁发射**：把用户送到这一页的那一处代码（仓库相对全路径） */
  from: string
  /** 导航形态 */
  nav: EntryNav
  /** `from` 的跳转语句里必须出现的**目标记号**（路由字面量 / 路由常量名 / 该路由的构造函数名） */
  via: string
  /**
   * `via` **不是**路由字面量时：把「**这个记号 ⇒ 哪条路由**」钉住的那份真值（仓库相对 / bmini 相对路径均可）。
   * 守卫在那里核它出现**目标路由字面量**或**路由常量名**（`REPRINT_PAGE_ROUTE` 这类）。
   * `via` 就是字面量时留空。
   */
  viaBinding?: string
  /**
   * 导航语句**所在函数会被执行**的依据（issue #5052 验收 D3）。
   *
   * 守卫 L3b 用的是**文件内**近似判定（组件 / hook / 文件内被引用过）——
   * 跨文件调用它看不见。此时**不许让它猜，也不许放行**：在这一栏写清"谁在什么时候调用它"，
   * 并给出那处调用所在的仓库相对路径（守卫不解析这一栏，它只是**登记**：把沉默的例外变成写下来的裁定）。
   */
  reachableBy?: string
  /** 从哪个身份出发、登录态怎么衔接（给人看的一句话，守卫只核非空） */
  audience: string
}

/** tabBar 页面的可达机制（**机械豁免**的依据：`app.config.ts` 的 `tabBar.list`，不是手写名单） */
export const TABBAR_REACHABLE =
  '系统 tabBar（`app.config.ts` 的 `tabBar.list`）承载：可达性由宿主提供，不依赖任何跳转语句'

/**
 * 台账本体。
 *
 * 🔴 **只许缩短**（照 `MENU_READ_PARITY_RESIDUALS` / `PublicCodeSpaces` / `reconcile_trigger_paths_ledger.json`
 * 的范式）：登记项对应的页面若从 `app.config.ts` 消失 ⇒ 守卫判红（条目必须**活着**）。
 * 新增一个面向用户的页面 ⇒ 在这里登记「谁发射」；**没有入口的页面不留白名单**，
 * 要么补入口，要么在 `docs/` 里论证它为什么不需要（本单没有这样的页面）。
 */
export const PAGE_ENTRY_LEDGER: PageEntry[] = [
  {
    route: '/pages/sessions/detail/index',
    from: 'src/pages/sessions/index/index.tsx',
    nav: 'navigateTo',
    via: '/pages/sessions/detail/index',
    audience: '商家身份（会话列表点进详情；未登录时该页自身引导去商家登录）',
  },
  {
    route: '/pages/auth/login/index',
    from: 'src/utils/request.ts',
    nav: 'redirectTo',
    via: '/pages/auth/login/index',
    audience: '公开（未登录 / 401 兜底：请求层发现凭据失效即送登录页）',
  },
  {
    route: '/pages/auth/change-password/index',
    from: 'src/pages/auth/login/index.tsx',
    nav: 'redirectTo',
    via: '/pages/auth/change-password/index',
    audience: '商家身份（首次登录强制改密：登录成功后按服务端标记 redirectTo 本页）',
  },
  {
    route: '/pages/production/index/index',
    from: 'src/pages/profile/index/index.tsx',
    nav: 'navigateTo',
    via: '/pages/production/index/index',
    audience: '商家身份（「我的」→ 扫码报工；页内按有无工人 session 分流读面）',
  },
  {
    route: WORKER_LOGIN_ROUTE,
    from: 'src/pages/worker/inbound/index.tsx',
    nav: 'navigateTo',
    via: 'WORKER_LOGIN_ROUTE',
    viaBinding: 'src/utils/inbound/gaps.ts',
    audience:
      '工人身份（入库 / 补打页在**无工人 session** 时给的显式入口；登录成功 navigateBack 回原页再继续）',
  },
  {
    route: INBOUND_PAGE_ROUTE,
    from: 'frontend/worker-h5/src/render.mjs',
    nav: 'href',
    via: '/pages/worker/inbound/index',
    audience:
      '工人身份（`/w/` 报工页页头入口 —— 跨应用静态链接 → `/b/#<路由>`；工人到达 `/b/` 时通常**还没有** bmini 侧的工人 session ⇒ 页面显式引导去工号 + PIN 登录，登录后回本页继续）',
  },
  {
    route: REPRINT_PAGE_ROUTE,
    from: 'src/app.tsx',
    nav: 'redirectTo',
    via: 'reprintLandingUrl',
    viaBinding: 'src/utils/inbound/deepLink.ts',
    audience:
      '公开入口 → 工人身份（扫标签上的码：`GET /i/{短码}` 302 到 `/b/?code=<短码>`，启动器把码原样交给本页；未登录时页面引导去工人登录，登录回来再消费）',
  },
  {
    route: REPRINT_PAGE_ROUTE,
    from: 'frontend/worker-h5/src/render.mjs',
    nav: 'href',
    via: '/pages/worker/reprint/index',
    audience:
      '工人身份（`/w/` 报工页页头入口；标签不在手边、或要按短码手输时走这条 —— 不必先扫洗水码）',
  },
  {
    route: '/pages/admin/pool/index',
    from: 'src/pages/profile/index/index.tsx',
    nav: 'navigateTo',
    via: 'surface.route',
    viaBinding: 'src/utils/adminPermission.ts',
    audience: '商家身份（「我的」按服务端下发的读权限显示管理面入口，集合未知时 fail-open 照显）',
  },
  {
    route: '/pages/admin/inbound/index',
    from: 'src/pages/profile/index/index.tsx',
    nav: 'navigateTo',
    via: 'surface.route',
    viaBinding: 'src/utils/adminPermission.ts',
    audience: '商家身份（同上；权限码真值在后端 `@RequirePermission`，端侧台账是它的镜像）',
  },
  {
    route: '/pages/admin/after-sales/index',
    from: 'src/pages/profile/index/index.tsx',
    nav: 'navigateTo',
    via: 'surface.route',
    viaBinding: 'src/utils/adminPermission.ts',
    audience: '商家身份（同上）',
  },
  {
    route: '/pages/admin/piecework/index',
    from: 'src/pages/profile/index/index.tsx',
    nav: 'navigateTo',
    via: 'surface.route',
    viaBinding: 'src/utils/adminPermission.ts',
    audience: '商家身份（同上）',
  },
]
