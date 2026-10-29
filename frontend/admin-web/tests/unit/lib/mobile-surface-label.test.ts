// case_ids: MC-091
// @vitest-environment jsdom
//
// `formatMobileTitles` 的单测（issue #6759 需求①）—— 权限树「手机端可见面」标注的**唯一渲染实现**。
//
// 🔴 这是 `frontend/admin-web/src/lib/mobile-surface-label.ts` 的同名单测
// （`QA Growth Gate` 对**新增生产文件**要求同名测试，路径逐字 = `tests/unit/lib/mobile-surface-label.test.ts`）。
//
// 判据口径（与需求一一对应）：
//   ① 服务端**没给**面（undefined / null / 空数组 / 全是空白）⇒ **空串**（调用方不追加任何字符 ——
//      纯 PC 权限不产生噪音，§31 P2/P3）；
//   ② 给了 1 个面 ⇒ ` · 手机端：X`（前置空格 + 间隔点，与树上形态逐字一致）；
//   ③ 给了多个面 ⇒ 用 `、` 连接，**顺序 = 服务端给的顺序**（前端不排序、不重排）；
//   ④ 🔴 输出里**不得出现权限码字面量**（`domain:action` 形态）—— 标注只摆中文面名，
//      不摆内部标识（§31 P3）；
//   ⑤ 本模块**没有任何**「码 → 手机端面」映射常量（第二份真值）—— 由类级守卫
//      `tests/unit_ci_workflows/test_mobile_surface_annotation_single_source.py` 守着。
//
// 语料是**夹具**：模拟服务端 `GET /api/admin/menus` 的 `mobileTitles` 下发值，
// 不是前端映射表（真值只在 `backend/admin-api/src/main/java/com/migao/admin/service/MobileSurfaces.java`）。
import { describe, expect, it } from 'vitest'
import {
  MOBILE_TITLE_PREFIX,
  MOBILE_TITLE_SEPARATOR,
  mobileTitlesByCodeFromTree,
  formatMobileTitles,
} from '@/lib/mobile-surface-label'

/** 服务端可能下发的面名（夹具用的两个面名取自手机端菜单；它们**不是**前端真值）。 */
const SURFACE_A = '智能派单'
const SURFACE_B = '入库过账'

/** 权限码的形态（`domain:action`）—— 标注里出现它就说明摆了内部标识。 */
const LOOKS_LIKE_PERMISSION_CODE = /[a-z_]+:[a-z_]+/

describe('formatMobileTitles（issue #6759 手机端可见面标注）', () => {
  it('判据 1: 服务端没给面（undefined / null / [] / 全空白）⇒ 空串，一个字符都不追加', () => {
    expect(formatMobileTitles(undefined)).toBe('')
    expect(formatMobileTitles(null)).toBe('')
    expect(formatMobileTitles([])).toBe('')
    // 防御性：空白项 / 空串项被过滤（服务端理论上不会给，但过滤后仍不得留下 `手机端：` 这种半截标注）
    expect(formatMobileTitles([''])).toBe('')
    expect(formatMobileTitles(['   '])).toBe('')
    expect(formatMobileTitles(['', '  '])).toBe('')
  })

  it('判据 2: 单面 ⇒ ` · 手机端：X`（前置分隔符逐字，与树上形态一致）', () => {
    expect(formatMobileTitles([SURFACE_A])).toBe(`${MOBILE_TITLE_SEPARATOR}${MOBILE_TITLE_PREFIX}${SURFACE_A}`)
    expect(formatMobileTitles([SURFACE_A])).toBe(' · 手机端：智能派单')
    // 常量本身是渲染契约的一部分（别处按它比对形态）—— 同时钉住它们没被改成别的符号
    expect(MOBILE_TITLE_SEPARATOR).toBe(' · ')
    expect(MOBILE_TITLE_PREFIX).toBe('手机端：')
  })

  it('判据 3: 多面 ⇒ 用 `、` 连接，顺序 = 服务端给的顺序（前端不排序）', () => {
    expect(formatMobileTitles([SURFACE_B, SURFACE_A])).toBe(' · 手机端：入库过账、智能派单')
    // 反向顺序 ⇒ 输出顺序跟着反（证明「不排序」，不是恰好撞上）
    expect(formatMobileTitles([SURFACE_A, SURFACE_B])).toBe(' · 手机端：智能派单、入库过账')
  })

  it('判据 4: 输出里不得出现权限码字面量（不摆内部标识）', () => {
    const out = formatMobileTitles([SURFACE_A, SURFACE_B])
    expect(LOOKS_LIKE_PERMISSION_CODE.test(out)).toBe(false)
    // 负控：同一把尺子对真的权限码**会**命中（否则上面那条是空断言）
    expect(LOOKS_LIKE_PERMISSION_CODE.test('processing:view')).toBe(true)
  })

  it('判据 5（对照读数）: 空白项被过滤后不残留分隔符 / 半截前缀', () => {
    const out = formatMobileTitles(['  ', SURFACE_A, ''])
    expect(out).toBe(' · 手机端：智能派单')
    expect(out.endsWith('、')).toBe(false)
    expect(out).not.toContain('、、')
  })
})

// ══════════════════════════════════════════════════════════════════════════
// 2026-10-18（用户截图：权限列/岗位权限的「手机端菜单」漏项）：
// 收集「码 → 手机端面」时必须扫**整棵树** —— `dashboard:view`（经营看板）自 issue #7087 起
// 是顶层独立项，只扫 `children` 会让手机端「数据」静默消失。
// ══════════════════════════════════════════════════════════════════════════
describe('mobileTitlesByCodeFromTree（整棵树收表）', () => {
  it('顶层独立项也收（dashboard:view 在顶层，不是任何组的 children）', () => {
    const tree = [
      { code: 'dashboard:view', label: '经营概览', mobileTitles: ['数据'] },
      {
        code: 'production-center',
        label: '生产管理',
        children: [{ code: 'processing:view', label: '智能派单', mobileTitles: ['智能派单'] }],
      },
    ]
    expect(mobileTitlesByCodeFromTree(tree)).toEqual({
      'dashboard:view': ['数据'],
      'processing:view': ['智能派单'],
    })
  })

  it('同码多节点 ⇒ 树序首个带标注的节点生效（与服务端「只落首承载节点」同一条规则）', () => {
    const tree = [
      {
        code: 'group-a',
        label: 'A',
        children: [{ code: 'production:view', label: '作业单', mobileTitles: ['计件工资报表'] }],
      },
      { code: 'production:view', label: '企业基础设置', mobileTitles: ['不该覆盖'] },
    ]
    expect(mobileTitlesByCodeFromTree(tree)['production:view']).toEqual(['计件工资报表'])
  })

  it('无标注 / 空白面名不进表（纯 PC 权限不产生噪音）；空树 ⇒ 空表', () => {
    expect(mobileTitlesByCodeFromTree(undefined)).toEqual({})
    expect(mobileTitlesByCodeFromTree([])).toEqual({})
    expect(
      mobileTitlesByCodeFromTree([
        { code: 'order:list', label: '发货单' },
        { code: 'x:view', label: 'X', mobileTitles: [] },
        { code: 'y:view', label: 'Y', mobileTitles: ['  '] },
      ]),
    ).toEqual({})
  })
})
