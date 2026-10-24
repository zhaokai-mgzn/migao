import { View, Text } from '@tarojs/components'

/**
 * 「没有权限」的授权缺失态 —— **唯一呈现实现**（用户 2026-10-18 裁定）
 *
 * ## 裁定与形态
 *
 * 用户逐字：「底部菜单做成常驻，没权限就向问黄金策页面的做法，底部我的菜单的子菜单就做成
 * 无权限不可见，也需要能在员工管理上设置菜单」。
 *
 * ⇒ 底栏 4 项**常驻**（`MerchantTabBar`，不再按权限删格）⇒ 没有权限的岗位也能点进底栏页面；
 * 这些页面必须**跟「问黄金策」一个做法**（`src/components/chat/MibaoAccessGate.tsx` 是第一个消费者）：
 * ① 逐字「需要管理员授权」（`SURFACE_NEEDS_ADMIN_GRANT_TEXT`，改字即红）；
 * ② **可行动引导**（去哪开通、找谁）—— 只写「无权限」等于让员工回电脑端问人；
 * ③ **不白屏、不静默隐藏、不画成空态**（「看不到」不许说成「没有」）。
 *
 * ## 单一真值
 *
 * 判定来源一律是**服务端**：本轮各页用 `GET /api/auth/me` 的 `mobileTabs`（服务端
 * `MobileSurfaces.visibleTabsFor` 的投影）或接口的 403，端侧**不自己判权限码**。
 */
export const SURFACE_NEEDS_ADMIN_GRANT_TEXT = '需要管理员授权'

/** 可行动引导（唯一生成处；面名由调用方给，例如「移动坐席」「经营数据」）。 */
export function surfaceGrantGuide(surfaceName: string): string {
  return `请联系企业管理员在「员工管理」中为你开通「${surfaceName}」权限`
}

interface AdminGrantGateProps {
  /** 授权缺失态的 `data-testid`（各页各一条，判据按它取） */
  testid: string
  /** 可行动引导文案（用 `surfaceGrantGuide(...)` 生成） */
  guide: string
}

/**
 * 授权缺失态的呈现（**与「问黄金策」逐字逐形一致**：大标题 + 一句引导，居中）。
 *
 * @see SURFACE_NEEDS_ADMIN_GRANT_TEXT 逐字文案（判据断言它）
 */
export default function AdminGrantGate({ testid, guide }: AdminGrantGateProps) {
  return (
    <View
      data-testid={testid}
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '80px 32px',
        textAlign: 'center',
      }}
    >
      <Text style={{ fontSize: '32px', fontWeight: '600', color: '#1f2937' }}>
        {SURFACE_NEEDS_ADMIN_GRANT_TEXT}
      </Text>
      <Text style={{ marginTop: '16px', fontSize: '26px', color: '#6b7280', lineHeight: '1.6' }}>
        {guide}
      </Text>
    </View>
  )
}
