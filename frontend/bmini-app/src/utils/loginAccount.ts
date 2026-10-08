/**
 * 「记住上次成功登录的账号名」（issue #6478）—— **只记账号名**。
 *
 * ## 口径（用户原话「账号名存在 cookies 中，不要每次都要输入」）
 *
 * · **只记账号名**，且**按登录面分开存**：员工「用户名@企业编码」/ 管理员手机号 / 工人工号
 *   各自记各自的上次值（三个键互不覆盖），进登录页时预填。
 * · 🔴 **绝不记 PIN / 密码 / 短信验证码** —— 没有例外、也没有「记住密码」开关。
 *   本模块的 API **只接受账号名一个入参**：写不出凭据，除非有人把凭据当账号名传进来
 *   （那由 `frontend/bmini-app/tests/login-remember-account.test.tsx` 的反向判据拦住）。
 * · 记的是「**上次成功登录**用过的账号名」，不是「上次输入过」⇒ 只在登录成功之后写。
 * · 从未登录过 ⇒ 读到空串（**不编默认值**）；退出登录 / 切换身份**不清**（它只是输入便利）。
 *
 * ## 存储
 *
 * 用仓内既有的本地存储约定（`Taro.setStorageSync` + `src/utils/constants.ts` 的 `STORAGE_KEYS`，
 * 与 `workerSession.ts` 同款）—— **localStorage**，不新引依赖、不用 cookie。
 * ⚠️ 与用户口述的「cookies」是一处**有意替换**：cookie 会随每个请求上行、还要处理
 * path/expires，而本仓 h5 既有的本地记住约定就是 localStorage（口径替换已在 PR / CHANGELOG 写明）。
 */

import Taro from '@tarojs/taro'
import { STORAGE_KEYS } from './constants'

/** 三个登录面（与登录页的三个 tab 一一对应，各记各的） */
export type LoginFace = 'employee' | 'admin' | 'worker'

/** 面 → 存储键（键名单一真值在 `STORAGE_KEYS`，这里只做映射） */
const KEY_BY_FACE: Record<LoginFace, string> = {
  employee: STORAGE_KEYS.LOGIN_ACCOUNT_EMPLOYEE,
  admin: STORAGE_KEYS.LOGIN_ACCOUNT_ADMIN,
  worker: STORAGE_KEYS.LOGIN_ACCOUNT_WORKER,
}

/** 该面上次成功登录的账号名；从未登录过（或读失败）⇒ 空串，**不编默认值**。 */
export function getRememberedAccount(face: LoginFace): string {
  try {
    const raw = Taro.getStorageSync(KEY_BY_FACE[face])
    return typeof raw === 'string' ? raw : ''
  } catch {
    return ''
  }
}

/** 登录**成功**之后记下该面的账号名（空值不写 —— 空账号名没有记住的意义）。 */
export function rememberAccount(face: LoginFace, account: string): void {
  const value = account.trim()
  if (!value) return
  try {
    Taro.setStorageSync(KEY_BY_FACE[face], value)
  } catch {}
}
