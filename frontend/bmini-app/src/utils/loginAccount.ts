/**
 * 「记住上次成功登录的账号名 / 企业编码」（issue #6478 / issue #7944）—— **只记输入便利**。
 *
 * ## 口径
 *
 * · 用户原话（#6478）：「账号名存在 cookies 中，不要每次都要输入」
 *   ⇒ **账号名**按登录面分开存：员工用户名 / 管理员手机号 / 工人工号，三键互不覆盖，进登录页预填。
 * · 用户原话（#7944）：「让浏览器记录下来上次登录的企业编码」「员工登录也应该记录下来@企业编码，
 *   最好是只需要输入员工账号，除非是首次登录才需要输入」
 *   ⇒ **企业编码**同样按面分开存（员工面 / 工人面）。它不是凭据 —— 没有用户名 + 密码 /
 *   工号 + PIN 就登不进去 —— 记它只为「换人登录时企业编码还在，只需改用户名」。
 * · 🔴 **绝不记 PIN / 密码 / 短信验证码** —— 没有例外、也没有「记住密码」开关
 *   （工人共用 PAD 上更不能留凭据）。本模块只有这两组 API（账号名、企业编码），写不出凭据，
 *   除非有人把凭据当参数传进来 —— 那由
 *   `frontend/bmini-app/tests/login-remember-account.test.tsx` 的反向判据拦住。
 * · 记的是「**上次成功登录**用过的值」，不是「上次输入过」⇒ 只在登录成功之后写。
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

/** 有「企业编码」这一格的登录面（管理员面是手机号 + 短信，没有企业编码） */
export type TenantFace = 'employee' | 'worker'

/** 面 → 账号名存储键（键名单一真值在 `STORAGE_KEYS`，这里只做映射） */
const KEY_BY_FACE: Record<LoginFace, string> = {
  employee: STORAGE_KEYS.LOGIN_ACCOUNT_EMPLOYEE,
  admin: STORAGE_KEYS.LOGIN_ACCOUNT_ADMIN,
  worker: STORAGE_KEYS.LOGIN_ACCOUNT_WORKER,
}

/** 面 → 企业编码存储键（同上；键名单一真值在 `STORAGE_KEYS`） */
const TENANT_KEY_BY_FACE: Record<TenantFace, string> = {
  employee: STORAGE_KEYS.LOGIN_TENANT_EMPLOYEE,
  worker: STORAGE_KEYS.LOGIN_TENANT_WORKER,
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

/** 该面上次成功登录用过的企业编码；从未登录过（或读失败）⇒ 空串，**不编默认值**。 */
export function getRememberedTenantCode(face: TenantFace): string {
  try {
    const raw = Taro.getStorageSync(TENANT_KEY_BY_FACE[face])
    return typeof raw === 'string' ? raw : ''
  } catch {
    return ''
  }
}

/** 登录**成功**之后记下该面的企业编码（空值不写）。 */
export function rememberTenantCode(face: TenantFace, tenantCode: string): void {
  const value = tenantCode.trim()
  if (!value) return
  try {
    Taro.setStorageSync(TENANT_KEY_BY_FACE[face], value)
  } catch {}
}

/**
 * 把「用户名@企业编码」拆成两段 —— 只用于**读 #6478 时代存下的整串**（issue #7944 的旧数据迁移）。
 *
 * 按**最后一个** `@` 切分，与服务端 `LoginIdentifiers.split()` 同口径；没有 `@` ⇒
 * 整串当用户名、企业编码为空（退回「首次登录」）。新写入不再使用整串：账号名与企业编码分别落盘。
 */
export function splitLoginIdentifier(value: string): { username: string; tenantCode: string } {
  const at = value.lastIndexOf('@')
  if (at < 0) return { username: value.trim(), tenantCode: '' }
  return {
    username: value.slice(0, at).trim(),
    tenantCode: value.slice(at + 1).trim(),
  }
}
