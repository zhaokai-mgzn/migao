/**
 * 管理面写动作的**二次确认**（issue #5654 验收判据：不可逆动作必须有护栏）。
 *
 * 为什么抽成一个函数而不是页面里各写一遍 `Taro.showModal`：
 * ① 不可逆动作的护栏**只该有一处口径**（文案形态、返回值语义）；
 * ② 测试要能**注入「用户点了取消」**——页面内联写法在 jest 里只能靠整页 mock 才拦得住，
 *    而本函数可被单测直接钉「取消 ⇒ 不提交」；
 * ③ 守卫射程（`ADMIN_SURFACE_SCOPE_FILES`）要把 `showModal` 这一处平台依赖**算得出来**。
 *
 * 🔴 h5 可用性：`Taro.showModal` 在 taro-h5 里是**真实 DOM 实现**
 * （`node_modules/@tarojs/taro-h5/dist/api/ui/interaction/modal.js`），既不在
 * `temporarilyNotSupport(...)` 也不在「只走微信 JS-SDK」的 `processOpenApi` 名单里
 * ⇒ 浏览器下确认框可用（与 `scanCode` 那种「纯浏览器必然不可用」是两件事）。
 */
import Taro from '@tarojs/taro'

/**
 * 确认框的**三态**结论（issue #7822）。
 *
 * 🔴 为什么必须把 `cancelled` 与 `failed` 分开：原来两者都压成 `false`，页面无法分辨「工人不想过账」
 * 与「**确认框根本没弹出来**」—— 后者的现场形态是**零反馈**：工人点「提交过账」，屏上什么都不发生
 * （既不建单、也不报错），读到的就是「点了没反应」（2026-10-26 线上实测）。
 * 取消是**工人的选择**（该静默）；弹窗失联是**故障**（必须说一句）。
 */
export type ConfirmOutcome = 'confirmed' | 'cancelled' | 'failed'

/**
 * 弹一次确认框，返回三态。`failed` 仍然等价于「不执行」（**默认拒绝**：拿不到确认就不执行不可逆
 * 动作 —— 弹窗异常时静默放行是更坏的失败方向），但调用方现在能把它**说出来**。
 */
export async function confirmActionResult(title: string, content: string): Promise<ConfirmOutcome> {
  try {
    const res: any = await Taro.showModal({
      title,
      content,
      confirmText: '确认',
      cancelText: '取消',
    })
    return res?.confirm ? 'confirmed' : 'cancelled'
  } catch {
    return 'failed'
  }
}

/**
 * 弹一次确认框。返回 `true` = 用户确认，`false` = 取消 / 弹窗失败（**默认拒绝**）。
 *
 * 不区分「失败 vs 取消」的调用方用它；要区分（= 要把弹窗失联说出来）的调用方用
 * `confirmActionResult`（类级判据 = `frontend/bmini-app/tests/confirm-failure-surfaced.test.ts`）。
 */
export async function confirmAdminAction(title: string, content: string): Promise<boolean> {
  return (await confirmActionResult(title, content)) === 'confirmed'
}
