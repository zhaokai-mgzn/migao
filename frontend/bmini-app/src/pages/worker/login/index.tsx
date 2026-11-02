/**
 * 独立工人登录页（issue #4733；**issue #8194 起 = 与 `/w/` 同一份表单**）。
 *
 * <p>主路径**不依赖微信**（设计 §2.1 裁定③）：车间 PAD 是普通浏览器/普通设备，没有微信授权；
 * 微信网页授权今天还是 501 占位（`AuthService.buildWechatH5AuthorizeUrl`），且**不得**成为唯一路径。</p>
 *
 * <p>与商家登录页（`pages/auth/login`）是**两条完全不同的链路**：那边走微信授权手机号 + 员工 JWT，
 * 这边走工号 + PIN + 工人 session；工人拿不到商家权限（服务端把 `worker` 放进
 * `/api/admin/**` 的拒绝集合）。三角色登录页的工人 tab 仍是**常规入口**（`?tab=worker`），本页是
 * 「工人首页去登录工人身份」「入库 / 补打 / 库存 / 报工页的未登录引导」落到的那一页。</p>
 *
 * <p>🔴 本页**不再自己写一份表单**（issue #8194）：标题 / 副标题 / 三个字段的顺序 / 按钮 / 错误位
 * 全部来自共享组件 `components/WorkerLoginForm` —— 与扫码报工页未登录时**就地**渲染的是同一份，
 * 也与终端 `/w/` 逐字一致（判据 `tests/worker-login-parity.test.ts`）。本页只负责
 * 「调 `workerLogin`」与「登录成功后去哪儿」两件事。</p>
 */
import { useCallback } from 'react'
import { View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { workerLogin } from '../../../services/workerService'
import WorkerLoginForm, {
  WORKER_LOGIN_FAILED_FALLBACK,
  type WorkerLoginSubmitResult,
  type WorkerLoginValues,
} from '../../../components/WorkerLoginForm'
import { reportReturnUrl, takeReportReturn } from '../../../utils/reportEntry'
import { WORKER_HOME_ROUTE } from '../../../utils/inbound/gaps'
import './index.scss'

export default function WorkerLoginPage() {
  const submit = useCallback(
    async (values: WorkerLoginValues): Promise<WorkerLoginSubmitResult> => {
      // 设备标签**不传**：`/w/` 没有那一格（它只在三角色登录页的工人 tab，本链路不再收集）
      const res = await workerLogin(
        values.workerNo,
        values.pin,
        undefined,
        values.enterpriseCode,
      )
      if (!res.success) {
        return { ok: false, message: res.message || WORKER_LOGIN_FAILED_FALLBACK }
      }
      return { ok: true, workerName: res.data?.worker_name ?? null }
    },
    [],
  )

  const done = useCallback((result: WorkerLoginSubmitResult) => {
    Taro.showToast({ title: `已登录：${result.workerName || '工人'}`, icon: 'success' })
    // 「登录完要接着报的码」（别处留下的一次性记录）⇒ 直接回报工页继续（读到即清）
    const back = takeReportReturn()
    if (back.present) {
      Taro.redirectTo({ url: reportReturnUrl(back.code) })
      return
    }
    // 从入库 / 补打 / 库存页 `navigateTo` 过来 ⇒ 回原页（原页的 `useDidShow` 会补读身份）；
    // 页面栈里只有自己（工人首页「退出」用 `redirectTo` 过来）⇒ 回工人首页 ——
    // 否则 `navigateBack` 无处可回，工人会停在登录页
    const stack = (Taro.getCurrentPages?.() ?? []).length
    if (stack > 1) {
      Taro.navigateBack({ delta: 1 })
      return
    }
    Taro.redirectTo({ url: WORKER_HOME_ROUTE })
  }, [])

  return (
    <View className='worker-login'>
      <WorkerLoginForm onSubmit={submit} onSuccess={done} />
    </View>
  )
}
