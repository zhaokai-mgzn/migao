/**
 * 「无权访问该页面」终态面（403）—— 从 `app/(dashboard)/layout.tsx` 提出来的**纯展示**组件。
 *
 * ## 为什么提出成独立组件（issue #6669 第 6 条）
 *
 * 修前这段 JSX 内联在 layout 的 `permissionDenied` 分支里，文案逐字是：
 * 「当前账号缺少权限 `production:view`，如需开通请联系管理员在「员工管理」中调整权限。」
 * —— 把**内部权限码**原样摆给商家看：商家看到一串自己用不上的英文冒号串，既看不懂也无从行动
 * （`migao-dev-flow` §31 P3「不摆内部标识」）。
 *
 * 提出来的两个理由：① 文案能被**单测直接钉住**（不用把整个 layout 的依赖网都 mock 一遍）；
 * ② 权限码**不进这个组件的 props** —— 结构上就没有回显它的入口（比"记得别渲染它"可靠）。
 *
 * 权限码本身仍在 `layout.tsx` 的 `ROUTE_PERMISSION_MAP` 里做判定（那是它的正当用途）；
 * 要排查时它在服务端日志/工单里可查，**不上商家屏**。
 */
export default function AccessDenied() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-neutral-50">
      <div className="rounded-2xl border border-neutral-200 bg-white p-10 text-center shadow-card max-w-md">
        <div className="text-4xl mb-3">🔒</div>
        <h1 className="text-lg font-semibold text-neutral-900">无权访问该页面</h1>
        <p className="mt-2 text-sm text-neutral-500">
          你的岗位没有这个功能的权限。如需开通，请联系管理员在「员工管理」中调整你的岗位权限。
        </p>
      </div>
    </div>
  )
}
