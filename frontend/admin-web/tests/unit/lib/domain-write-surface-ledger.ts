// case_ids: UI-054
/**
 * 「域是可写的」台账 —— 类级守卫（铁律 8 / `migao-dev-flow` §23）的**数据面**。
 *
 * ## 它治的类
 *
 * issue #6825 的缺陷形态：`/settings?domain=calc`「算料口径」域**只有只读展示、没有写面**
 * —— 值在那儿、能看，改不了；而真正的写面藏在另一个入口（板子的 tab）里，那个入口已随 #6580
 * 从菜单撤掉 ⇒ 商家从任何导航都改不到这些参数。
 *
 * 「某个配置域退化成展板」这件事**当时没有任何东西会红** —— 每个域各写各的判据，谁也不会去问
 * 「这个域今天还能不能改」。本台账 + 配套守卫（`domain-write-surface.test.tsx`）把这句话变成可执行的：
 *
 * 1. **声明了 `mainlineSteps` 的域**（= 进配置主线 = 有配置值的域）**必须登记**在
 *    {@link DOMAIN_WRITE_SURFACES} 里 —— 未登记 ⇒ 红（fail-closed，不靠人记得加）；
 * 2. 登记的 `anchor` 必须是该域面板（`config-domain-panel-<key>`）里**真实存在**的
 *    **可交互控件**（`input` / `select` / `textarea` / `button` / `[contenteditable]`）——
 *    域退回只读展示 ⇒ 红，并具名是哪一个域（`<div>` / `<span>` / `<td>` 这类**不算**：它们改不了值）；
 * 3. 台账**不许空转**（空台账 = 有人清空它「消红」⇒ 红）且**无幽灵**（拼错域 key ⇒ 红）。
 *
 * ## 边界（如实登记）
 *
 * - 判据判「**有可交互的写入口**」，**不判**「改完能存下来」—— 后者由各域的实例判据承担
 *   （算料域 = `frontend/admin-web/tests/unit/components/CalcCaliberPanel.test.tsx`
 *   的全量键 / 422 逐条理由 / 草稿不回滚）；
 * - 「可交互控件」包含**点击进入编辑**的入口（本仓配置面的既有交互）与开关按钮；
 *   它**不判**「点了之后一定出现输入框」—— 那种判据对每个域都是另一条交互契约，
 *   属各域自己的测试（硬塞进本守卫会变成假判据）；
 * - 台账是**人工维护**的（不是自动发现）：真接入写面却忘了登记 ⇒ 出口是「把它加进台账」，
 *   不是静默放行。
 */
import type { ConfigDomainKey } from '../../../src/lib/config-center-domains'
import { CONFIG_DOMAINS } from '../../../src/lib/config-center-domains'

/**
 * **已登记**的域写面：域 key（逐字 = `CONFIG_DOMAINS` 的 key）→ 该域面板里那个
 * **写入口控件**的 `data-testid`。
 *
 * 🔴 新增域 / 给只读域接入写面 ⇒ **必须**在这里加一行；否则守卫的「未登记即红」当场失败（具名报出）。
 */
export const DOMAIN_WRITE_SURFACES: Readonly<Partial<Record<ConfigDomainKey, string>>> = {
  // 算料口径（issue #6825）：8 个标量就地可改（tiers / 拼色 / 公式 / 保存同在面板内）
  calc: 'calc-caliber-scalar-per_fold_single',
  // 加工项与分类（`ProcessingItemsPanel`）：新建加工项入口（面板内「新建」）
  'processing-items': 'processing-item-new',
  // 加工费组合（`FeeCombinationsPanel`）：行内「改单价」入口
  'fee-combinations': 'fee-combination-edit-1',
  // 工序与部位单价（`OperationPricePanel`）：矩阵格的行内改价入口
  'operation-prices': 'operation-price-edit-精裁',
  // 工艺路线（`RoutingsPanel`）：路线主线编辑入口
  'craft-route': 'routing-edit-11',
  // 裁高配置（`CuttingHeightPanel` → `CuttingHeightConfigPanel`）：增量项可增删改
  'cutting-height': 'cutting-height-add',
  // 余料尺寸（`RemnantItemSizesPanel`）：小件（工序名）输入框
  'remnant-sizes': 'remnant-size-item-0',
  // 企业信息（`EnterpriseDomainPanel`）：公司名称
  enterprise: 'settings-enterprise-name',
  // AI 客服（`AiDomainPanel`）：AI 客服名称
  ai: 'settings-ai-bot-name',
  // 通知设置（`NotificationsDomainPanel`）：系统通知开关
  notifications: 'settings-notification-toggle',
}

/**
 * 声明了 `mainlineSteps`（= 进配置主线 = 有配置值）却**有意**不给写面的域。
 *
 * **今天为空**（每一个域都有可交互的写入口）。它存在的意义：将来真出现「只读才是正确形态」的域
 * （如纯展示的诊断域）时，必须**具名登记 + 写清为什么**，而不是把守卫放宽。
 */
export const READ_ONLY_DOMAINS: readonly string[] = []

/** 进配置主线（`mainlineSteps` 非空）= 有配置值的域 —— 这一族**必须**在写面台账里 */
export function domainsWithMainlineStep(): string[] {
  return CONFIG_DOMAINS.filter((d) => d.mainlineSteps.length > 0).map((d) => d.key)
}

/**
 * 取某个域的写面锚点。
 *
 * 🔴 **fail-closed**：未登记 ⇒ **抛错**（不是返回 `''` / `undefined`）。
 * 调用方（守卫）因此拿不到「空字符串也算通过」的假绿。
 */
export function writeSurfaceAnchorOf(domainKey: string): string {
  const anchor = DOMAIN_WRITE_SURFACES[domainKey as ConfigDomainKey]
  if (!anchor) {
    throw new Error(
      `域「${domainKey}」没有登记写面锚点 —— 要么给它接一个可交互的写入口并登记在 ` +
        `frontend/admin-web/tests/unit/lib/domain-write-surface-ledger.ts，` +
        `要么把它登记进 READ_ONLY_DOMAINS 并写清为什么只读`,
    )
  }
  return anchor
}
