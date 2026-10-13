// case_ids: UI-054
/**
 * **类级守卫：「域是可写的」**（铁律 8 / issue #6825）。
 *
 * ## 它治的类（缺陷形态，不是某一个域）
 *
 * `/settings?domain=calc`「算料口径」域**只有只读展示**：值都在、能看，但**一个可编辑控件都没有** ——
 * 真正的写面藏在别处（板子的 tab），而那个入口已从菜单撤掉 ⇒ **商家从任何导航都改不到这些参数**。
 *
 * 这个类的共性是「**配置域退化成展板**」：域还在、读数还在、主线也认它，**就是改不了**。
 * 而它当时**没有任何东西会红** —— 每个域各写各的判据，谁也不会去问「这个域能不能改」。
 *
 * ## 判据（逐条能红）
 *
 * 1. **未登记即红**：凡是声明了 `mainlineSteps` 的域（= 进配置主线 = 有配置值的域）**必须**在
 *    台账（`frontend/admin-web/tests/unit/lib/domain-write-surface-ledger.ts`）里有一行 ——
 *    新增域 / 给只读域接写面而忘记登记 ⇒ 具名报出该域（`writeSurfaceAnchorOf` 直接抛错，fail-closed）；
 * 2. **台账不许空转**：台账为空 ⇒ 红（有人清空台账「消红」）；
 * 3. **无幽灵**：台账的每个 key 都是现役域（拼错 ⇒ 判据在对空气放行）；
 * 4. **登记必须被兑现且真是写面**：每一行都要在**该域面板**（`config-domain-panel-<key>`）里
 *    真实存在，且落在**可交互控件**上（`input` / `select` / `textarea` / `button` /
 *    `[contenteditable]`）—— 域退回只读展示 ⇒ 红，并具名是哪一个域。
 *
 * ## 「摘掉接线 ⇒ 会怎么红」（可复制）
 *
 * - 把 `CalcCaliberPanel` 里那 8 个 `NumberInput` 删掉（退回只读值位）⇒ 判据 4 对 `calc` 红
 *   （`calc-caliber-scalar-per_fold_single` 取不到）；
 * - 把某域的 key 从台账里删一行 ⇒ 判据 1 当场红并报出该域（**未登记即红**）；
 * - 把台账清空 ⇒ 判据 2 红；
 * - 把某个域的 key 改名而不改台账 ⇒ 判据 3 红（无幽灵）。
 *
 * ## 边界（如实登记）
 *
 * - 它判「域里有**可交互的写入口**」，**不判**「改完能存下来」：写回语义（全量键 / 422 逐条理由 /
 *   草稿不回滚）由各域的实例判据承担（算料域 =
 *   `frontend/admin-web/tests/unit/components/CalcCaliberPanel.test.tsx`）；
 * - 台账是**人工维护**的（不是自动发现）：真接入写面却忘了登记 ⇒ 出口是「把它加进台账」，
 *   不是静默放行。这就是本判据的**判别力**所在 —— 它不会给「恰好有一个搜索框」的页面盖章。
 */
import { describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'

const mockSearchParams = vi.fn()
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => mockSearchParams(),
  usePathname: () => '/settings',
}))

vi.mock('@/lib/permission', () => ({
  usePermission: () => ({ has: () => true, permissions: [], isAdmin: false }),
}))

vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: Record<string, unknown>) => (
    <a href={href as string} {...props}>
      {children as never}
    </a>
  ),
}))

vi.mock('@/store/auth', () => ({
  useAuthStore: Object.assign(() => ({ user: null }), {
    getState: () => ({ fetchUserInfo: vi.fn() }),
  }),
}))

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const ok = (data: unknown) => ({ data: { success: true, data } })

vi.mock('@/lib/api', () => ({
  settingsApi: {
    getSettings: () =>
      Promise.resolve(ok({ companyName: '测试企业', logo: '', notificationEnabled: true, code: 'migao' })),
    updateSettings: () => Promise.resolve(ok(null)),
    getAiConfig: () => Promise.resolve(ok({ botName: '元元', greetingTemplate: '您好' })),
    updateAiConfig: () => Promise.resolve(ok(null)),
  },
  uploadApi: { uploadImage: () => Promise.resolve(ok({ url: '' })) },
  productionApi: {
    getOperationPositions: () =>
      Promise.resolve(ok([{ id: 'pos-精裁', operation: '精裁', position: '布帘', unit_price: 12 }])),
    getRoutings: () =>
      Promise.resolve(
        ok({
          total: 1,
          routings: [{ id: 11, name: '窗帘工序路线', is_default: true, mainline: [], positions: [] }],
        }),
      ),
    getFeeCombinations: () =>
      Promise.resolve(ok({ total: 1, combinations: [{ id: 1, items: ['韩褶', '花边'], unit_price: 12 }] })),
    getFeeGaps: () => Promise.resolve(ok({ unpriced_combination_total: 0 })),
    getCraftCalcConfig: () =>
      Promise.resolve(
        ok({
          source: 'stored',
          config: {
            per_fold_single: 0.25,
            per_fold_mixed_times: { '1': 0.65 },
            margin_single: 0.2,
            margin_multi: 0.3,
            min_fullness: 1.5,
            tiers: { standard: { fullness: 2, label: '标准工艺' } },
            default_formula: 'pleat',
            hem_margin: 0.3,
            meters_rounding_step: 0.1,
            oversize_width_threshold: 6,
            oversize_height_threshold: 4,
          },
        }),
      ),
    updateCraftCalcConfig: () => Promise.resolve(ok({ source: 'stored', config: {} })),
    getOperationsCatalog: () => Promise.resolve(ok({ total: 0, groups: [] })),
    getRouteRules: () => Promise.resolve(ok([])),
    getRouteRuleOptions: () => Promise.resolve(ok({})),
  },
  processingItemApi: { getProcessingItems: () => Promise.resolve(ok({ items: [] })) },
  processingCategoryApi: { getProcessingCategories: () => Promise.resolve(ok([])) },
  // 裁高读面：一行真形状的增量项（`hit` 必填 —— 夹具缺它会在渲染期抛错、把整个域打空）。
  // ⚠️ 报文**内联**（`vi.mock` 工厂被提升 ⇒ 工厂里不能调 `ok()`：那会让本域在提升期整个消失）
  cuttingHeightApi: {
    get: () =>
      Promise.resolve({
        data: { success: true, data: { source: 'stored', config: {
          items: [
            {
              key: 'butie',
              name: '布贴',
              value: 0.015,
              direction: 'add',
              height_join: false,
              hit: { trigger_kind: 'option', trigger_value: '布贴', position: '布帘' },
              hit_expr: null,
              enabled: true,
              order: 10,
            },
          ],
          rounding: { mode: 'half_up', digits: 3 },
        } } },
      }),
  },
  autoFeaturesApi: { preview: () => Promise.resolve(ok({ auto_features: [] })) },
  remnantApi: {
    smallItemSpecs: () =>
      Promise.resolve(ok({ configured: true, items: [{ itemKey: '帘头', lengthM: 1, widthM: 1 }] })),
    putSmallItemSpecs: () => Promise.resolve(ok(null)),
  },
  briefingApi: { getConfig: () => Promise.resolve(ok({ enabled: false, generateTime: '06:00' })) },
}))

vi.mock('@/lib/image-dimensions', () => ({
  readImageDimensions: () => Promise.resolve({ width: 1, height: 1 }),
}))

import SettingsPage from '@/app/(dashboard)/settings/page'
import { CONFIG_DOMAINS } from '@/lib/config-center-domains'
import {
  DOMAIN_WRITE_SURFACES,
  READ_ONLY_DOMAINS,
  domainsWithMainlineStep,
  writeSurfaceAnchorOf,
} from './domain-write-surface-ledger'

/**
 * 「可交互的写入口」——`<div>` / `<span>` / `<td>` 这类**改不了值**的东西不算
 * （它们正是「展板」的形态）。
 *
 * 有意包含 `button`：「点击进入编辑」是本仓配置面的既有交互（行内改价 / 改单价 / 增删行），
 * 把按钮排除出去会把**正常形态**判成只读。
 */
const INTERACTIVE = 'input:not([type="hidden"]), select, textarea, button, [contenteditable="true"]'

describe('判据 1：声明了 mainlineSteps 的域**必须**登记写面（未登记即红）', () => {
  it('台账覆盖全部「进配置主线」的域（少一行 ⇒ 具名报出该域）', () => {
    const required = domainsWithMainlineStep()
    // 自证非空：主线域为空时下面的循环恒真（空断言）
    expect(required.length).toBeGreaterThan(0)
    for (const key of required) {
      // 未登记 ⇒ `writeSurfaceAnchorOf` 抛错（fail-closed），本断言红
      const anchor = writeSurfaceAnchorOf(key)
      expect(anchor, `域「${key}」的写面锚点为空 ⇒ 退回只读展示`).toBeTruthy()
    }
  })

  it('🔴 判别力自证：未登记的域**当场抛错**（不是返回空串放行）', () => {
    expect(() => writeSurfaceAnchorOf('not-registered')).toThrow(/没有登记写面锚点/)
  })

  it('台账不许空转：条目数 > 0（清空台账「消红」⇒ 红）', () => {
    expect(Object.keys(DOMAIN_WRITE_SURFACES).length).toBeGreaterThan(0)
  })

  it('无幽灵：台账的每个 key 都是**现役域**（拼错 ⇒ 判据在对空气放行）', () => {
    const keys = CONFIG_DOMAINS.map((d) => d.key)
    for (const key of Object.keys(DOMAIN_WRITE_SURFACES)) {
      expect(keys, `台账里的域「${key}」已不是域 key ⇒ 请删掉该行`).toContain(key)
    }
    for (const key of READ_ONLY_DOMAINS) {
      expect(keys, `「有意只读」台账里的域「${key}」已不是域 key ⇒ 请删掉该行`).toContain(key)
    }
  })
})

describe('判据 4：每个登记域的写面**真的可交互**（域退回展板 ⇒ 红）', () => {
  for (const [key, anchor] of Object.entries(DOMAIN_WRITE_SURFACES)) {
    it(`域「${key}」：\`${anchor}\` 在面板里且是可交互控件`, async () => {
      mockSearchParams.mockReturnValue(new URLSearchParams(`domain=${key}`))
      render(<SettingsPage />)
      const panel = await screen.findByTestId(`config-domain-panel-${key}`)

      const el = await within(panel).findByTestId(anchor as string)
      expect(
        el.matches(INTERACTIVE),
        `域「${key}」的写面锚点「${anchor}」不是可交互控件 —— 配置域退化成展板（issue #6825 的缺陷形态）`,
      ).toBe(true)
    })
  }

  /**
   * 🔴 **写出口成对**（issue #6825 的**判别力**所在，主会话真机实测逼出来的）：
   * 「域内有 `input`」**不足以**证明这一域可写 —— `/settings?domain=calc` 改前就有输入框，
   * 但那是**阈值试算**工具（`OversizeThresholdPreview`，页面上写着「改完先看，不保存」），
   * 它**不发 `PUT`** ⇒ 只看 input 的判据会被它满足（**假绿**）。
   *
   * ⇒ 逐域同时要求「可编辑控件锚点」**与**「本域自己的写出口」（`[data-write-exit]`）。
   * 对照组（必红）：只留试算框、去掉保存出口 ⇒ 本判据红。
   */
  it('🔴 每个登记域都有**自己的写出口**（`[data-write-exit]`）—— 只留试算框那种形态必红', async () => {
    const missing: string[] = []
    for (const key of Object.keys(DOMAIN_WRITE_SURFACES)) {
      mockSearchParams.mockReturnValue(new URLSearchParams(`domain=${key}`))
      const { unmount } = render(<SettingsPage />)
      const panel = await screen.findByTestId(`config-domain-panel-${key}`)
      // 等本域读面落地（写出口跟读面一起来）
      await within(panel).findByTestId(DOMAIN_WRITE_SURFACES[key as never] as string)
      if (!panel.querySelector('[data-write-exit]')) missing.push(key)
      unmount()
    }
    expect(
      missing,
      '这些域只有可编辑控件、没有自己的写出口 —— 「能填不能存」正是 #6825 的缺陷形态（试算框满足不了它）',
    ).toEqual([])
  })
})
