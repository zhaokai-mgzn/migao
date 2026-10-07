// case_ids: BM-041
/**
 * 「记住上次成功登录的账号名」判据（issue #6478）
 *
 * ## 用户原话与冻结口径
 *
 * > 还要做个小优化，账号名存在 cookies 中，不要每次都要输入
 *
 * · **只记账号名**，按登录面分开存（员工「用户名@企业编码」/ 管理员手机号 / 工人工号各自记各自的上次值），
 *   进登录页**预填**；
 * · 🔴 **绝不记 PIN / 密码 / 短信验证码** —— 没有例外、也没有「记住密码」开关
 *   （工人共用 PAD 上更不能留凭据）；
 * · 记的是「**上次成功登录**用过的账号名」，不是「上次输入过」⇒ 失败不写、成功才写；
 * · 从未登录过 ⇒ 留空（**不编默认值**）；退出登录 / 切换身份**不清**（它只是输入便利）。
 * · 存储 = **localStorage**（`Taro.setStorageSync` + `STORAGE_KEYS`，与 `workerSession.ts` 同款）——
 *   用户口述的「cookies」是有意替换（cookie 会随每个请求上行、还要处理 path/expires），
 *   口径替换已在 PR / CHANGELOG 显式写明。
 *
 * | # | 判据 | 红证（怎么让它单独变红） |
 * |---|---|---|
 * | 1a | 从未登录过 ⇒ 三个面都留空（不编默认值） | 给 `getRememberedAccount` 加一个兜底默认值 ⇒ 红 |
 * | 1b | 员工面预填上次成功登录的账号名；**密码不预填** | 把密码也预填 ⇒ 红 |
 * | 1c | 三面各记各的、互不串台 | 三面共用一个键 ⇒ 红（管理员的值串到员工面） |
 * | 1d | 只在**成功之后**写：失败保留上次成功值，成功才覆盖 | 把 `rememberAccount` 移到 `if (!success)` 之前 ⇒ 红 |
 * | 1e | 退出登录**不清**账号名 | 把三个键加进 `logout()` 的清理列表 ⇒ 红 |
 * | 1f | 独立工人登录页同样预填工号（PIN 不预填） | 摘掉该页的预填 ⇒ 红 |
 * | 2 | 🔴 **反向红线**：三个面全部填满并成功登录 ⇒ 落盘键值里**不出现**密码 / PIN / 验证码，且键名不越界 | 注入「把 pin 也存进去」⇒ 红 |
 * | 2b | **类级**：本仓存储键面不许出现凭据形态的键名（`password`/`pwd`/`pin`/`*code`/`credential`…） | 新增 `LOGIN_PASSWORD` 之类的键 ⇒ 红 |
 * | 2c | **类级**：账号名三键只有 `frontend/bmini-app/src/utils/loginAccount.ts` 一个读写点 | 在别处直写这两个键 ⇒ 红 |
 *
 * ## 边界（照实登记）
 * · 判据只覆盖「端侧落盘面」：**服务端**是否记录账号名不在本文件射程内（本就与本次改动无关）。
 * · 判据不看「预填值是否可读/好看」（那是登录页既有的可读性判据 BM-027 的面）。
 */
import fs from 'fs'
import path from 'path'
import React from 'react'
import { render, screen, fireEvent, act, cleanup } from '@testing-library/react'
import { stripComments } from './helpers/h5PlatformLists'

const mockEmployeeLoginAction = jest.fn()
const mockSmsLoginAction = jest.fn()
const mockLogin = jest.fn()
const mockGetState = jest.fn()
const mockSendSmsCode = jest.fn()
const mockWorkerLogin = jest.fn()

jest.mock('../src/store/authStore', () => ({
  useAuthStore: Object.assign(
    jest.fn(() => ({
      isLoading: false,
      login: mockLogin,
      employeeLoginAction: mockEmployeeLoginAction,
      smsLoginAction: mockSmsLoginAction,
    })),
    { getState: () => mockGetState() },
  ),
}))

jest.mock('../src/utils/auth', () => ({
  sendSmsCode: (...args: unknown[]) => mockSendSmsCode(...args),
}))

jest.mock('../src/services/workerService', () => ({
  workerLogin: (...args: unknown[]) => mockWorkerLogin(...args),
}))

import Taro from '@tarojs/taro'
import LoginPage from '../src/pages/auth/login/index'
import WorkerLoginPage from '../src/pages/worker/login/index'
import { STORAGE_KEYS } from '../src/utils/constants'

// 登出语义必须读**真实现**（`../src/utils/auth` 在本文件被替身掉了）
const realAuth = jest.requireActual('../src/utils/auth') as typeof import('../src/utils/auth')

const SRC_DIR = path.join(__dirname, '..', 'src')
const ACCOUNT_KEYS = [
  STORAGE_KEYS.LOGIN_ACCOUNT_EMPLOYEE,
  STORAGE_KEYS.LOGIN_ACCOUNT_ADMIN,
  STORAGE_KEYS.LOGIN_ACCOUNT_WORKER,
] as const
const ALL_STORAGE_KEYS: string[] = Object.values(STORAGE_KEYS)

/** 凭据形态键名（命中 ⇒ 红）。`token` 不在此列 —— 它是既有登录态键，不是用户输入的口令。 */
const CREDENTIAL_KEY_RE = /pass(word|wd)?|pwd|\bpin\b|sms_?code|captcha|verify_?code|credential|secret/i

const IDENTIFIER_PLACEHOLDER = '如 zhangsan@acme'
const PASSWORD_PLACEHOLDER = '请输入密码'
const PHONE_PLACEHOLDER = '请输入管理员手机号'
const CODE_PLACEHOLDER = '请输入验证码'
const WORKER_NO_PLACEHOLDER = '请输入工号'
const PIN_PLACEHOLDER = '请输入 PIN'

/** 凭据哨兵：只要它们出现在任何落盘键值里，反向红线当场红。
 *  ⚠️ 验证码哨兵必须是**纯数字**：登录页的验证码框是 `type='number'`，
 *  jsdom 里给数字框喂非数字串会被读成空串（那样「没存验证码」就退化成空断言 —— 本文件初版踩过）。 */
const SENTINEL_PASSWORD = 'SENTINEL-PASSWORD-9f2c'
const SENTINEL_CODE = '604137'
const SENTINEL_PIN = 'SENTINEL-PIN-77b3'

function valueOf(placeholder: string): string {
  return (screen.getByPlaceholderText(placeholder) as HTMLInputElement).value
}

function type(placeholder: string, value: string): void {
  fireEvent.change(screen.getByPlaceholderText(placeholder), { target: { value } })
}

function switchTo(label: string): void {
  fireEvent.click(screen.getByText(label))
}

async function clickLogin(): Promise<void> {
  await act(async () => {
    fireEvent.click(screen.getByText('登录'))
  })
}

/** 递归收集 `src/**` 下的 ts/tsx（bmini 相对 posix 路径） */
function sourceFiles(dir: string = SRC_DIR): string[] {
  const out: string[] = []
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) out.push(...sourceFiles(full))
    else if (/\.tsx?$/.test(entry.name)) {
      out.push(path.relative(path.join(__dirname, '..'), full).split(path.sep).join('/'))
    }
  }
  return out.sort()
}

function readSource(rel: string): string {
  const abs = path.join(__dirname, '..', rel)
  if (!fs.existsSync(abs)) throw new Error(`找不到源文件：${rel}（路径漂移不得静默跳过 ⇒ 红）`)
  return stripComments(fs.readFileSync(abs, 'utf8'))
}

/** 现取：本仓 `src/**` 里**真实出现**的存储键字面量（storage 调用 + `*_KEY/_PREFIX` 常量） */
function storageKeyLiterals(): Set<string> {
  const keys = new Set<string>()
  for (const rel of sourceFiles()) {
    const text = readSource(rel)
    for (const match of text.matchAll(/(?:set|get|remove)StorageSync\(\s*'([^']+)'/g)) keys.add(match[1])
    for (const match of text.matchAll(/\b[A-Z][A-Z0-9_]*(?:KEY|PREFIX)[A-Z0-9_]*\s*=\s*'([^']+)'/g)) {
      keys.add(match[1])
    }
  }
  return keys
}

describe('A. 记住上次成功登录的账号名（issue #6478）', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    mockGetState.mockReturnValue({ user: { mustChangePassword: false } })
    // 每个用例自带前置（不依赖执行顺序 / 不依赖上一个用例留下的存储）
    for (const key of ALL_STORAGE_KEYS) Taro.removeStorageSync(key)
  })

  afterEach(() => {
    cleanup()
  })

  it('判据 1a：从未登录过 ⇒ 三个面都留空（不编默认值）', () => {
    render(<LoginPage />)

    expect(valueOf(IDENTIFIER_PLACEHOLDER)).toBe('')
    switchTo('管理员登录')
    expect(valueOf(PHONE_PLACEHOLDER)).toBe('')
    switchTo('工人登录')
    expect(valueOf(WORKER_NO_PLACEHOLDER)).toBe('')
  })

  it('判据 1b：员工面预填上次成功登录的账号名，**密码不预填**', () => {
    Taro.setStorageSync(STORAGE_KEYS.LOGIN_ACCOUNT_EMPLOYEE, 'zhangsan@acme')

    render(<LoginPage />)

    expect(valueOf(IDENTIFIER_PLACEHOLDER)).toBe('zhangsan@acme')
    expect(valueOf(PASSWORD_PLACEHOLDER)).toBe('')
  })

  it('判据 1c：按登录面分开存 —— 三面各预填各自的值，互不串台', () => {
    Taro.setStorageSync(STORAGE_KEYS.LOGIN_ACCOUNT_ADMIN, '13800000000')
    Taro.setStorageSync(STORAGE_KEYS.LOGIN_ACCOUNT_WORKER, 'W-001')

    render(<LoginPage />)

    // 员工面没有记录 ⇒ 空（没有被管理员/工人的值串上）
    expect(valueOf(IDENTIFIER_PLACEHOLDER)).toBe('')
    switchTo('管理员登录')
    expect(valueOf(PHONE_PLACEHOLDER)).toBe('13800000000')
    switchTo('工人登录')
    expect(valueOf(WORKER_NO_PLACEHOLDER)).toBe('W-001')
    // PIN 同样是凭据 ⇒ 不预填
    expect(valueOf(PIN_PLACEHOLDER)).toBe('')
  })

  it('判据 1d：只在**成功之后**写 —— 失败保留上次成功值，成功才覆盖', async () => {
    Taro.setStorageSync(STORAGE_KEYS.LOGIN_ACCOUNT_EMPLOYEE, 'old@acme')
    mockEmployeeLoginAction.mockResolvedValueOnce(false)

    render(<LoginPage />)
    type(IDENTIFIER_PLACEHOLDER, 'new@acme')
    type(PASSWORD_PLACEHOLDER, 'init-pass-123')
    await clickLogin()

    // 失败不写：仍是上次**成功**用过的那个
    expect(Taro.getStorageSync(STORAGE_KEYS.LOGIN_ACCOUNT_EMPLOYEE)).toBe('old@acme')

    mockEmployeeLoginAction.mockResolvedValueOnce(true)
    await clickLogin()

    expect(Taro.getStorageSync(STORAGE_KEYS.LOGIN_ACCOUNT_EMPLOYEE)).toBe('new@acme')
  })

  it('判据 1e：退出登录**不清**账号名（它只是输入便利，不是登录态）', () => {
    for (const key of ACCOUNT_KEYS) Taro.setStorageSync(key, 'kept')
    Taro.setStorageSync(STORAGE_KEYS.TOKEN, 'tok-1')
    Taro.setStorageSync(STORAGE_KEYS.USER, '{"id":1}')

    realAuth.logout()

    for (const key of ACCOUNT_KEYS) expect(Taro.getStorageSync(key)).toBe('kept')
    // 对照：登录态照旧被清（否则「没清账号名」可能只是 logout 什么都没干）
    expect(Taro.getStorageSync(STORAGE_KEYS.TOKEN)).toBe('')
    expect(Taro.getStorageSync(STORAGE_KEYS.USER)).toBe('')
  })

  it('判据 1f：独立工人登录页（`pages/worker/login`）同样预填工号，PIN 不预填', () => {
    Taro.setStorageSync(STORAGE_KEYS.LOGIN_ACCOUNT_WORKER, 'W-042')

    render(<WorkerLoginPage />)

    expect(valueOf('工号')).toBe('W-042')
    expect(valueOf('PIN')).toBe('')
  })

  it('🔴 判据 2（反向红线）：三个面全部填满并成功登录 ⇒ 落盘键值里不出现密码 / 验证码 / PIN', async () => {
    mockEmployeeLoginAction.mockResolvedValueOnce(true)
    mockSmsLoginAction.mockResolvedValueOnce(true)
    mockWorkerLogin.mockResolvedValueOnce({ success: true, data: { worker_name: '张三' } })
    ;(Taro.setStorageSync as jest.Mock).mockClear()

    render(<LoginPage />)

    // 员工面：账号名 + 密码
    type(IDENTIFIER_PLACEHOLDER, 'zhangsan@acme')
    type(PASSWORD_PLACEHOLDER, SENTINEL_PASSWORD)
    await clickLogin()

    // 管理员面：手机号 + 短信验证码
    switchTo('管理员登录')
    type(PHONE_PLACEHOLDER, '13800000000')
    type(CODE_PLACEHOLDER, SENTINEL_CODE)
    await clickLogin()

    // 工人面：工号 + PIN（+ 设备标签）
    switchTo('工人登录')
    type(WORKER_NO_PLACEHOLDER, 'W-007')
    type(PIN_PLACEHOLDER, SENTINEL_PIN)
    await clickLogin()

    const calls = (Taro.setStorageSync as jest.Mock).mock.calls as [string, unknown][]
    // 反空跑：三个面都真的落盘了（否则「没有凭据」是空集恒真）
    expect(calls.map(([key]) => key).sort()).toEqual(
      [...ACCOUNT_KEYS].sort(),
    )

    const written = calls.map(([key, value]) => `${key}=${JSON.stringify(value)}`).join('\n')
    expect(written).not.toContain(SENTINEL_PASSWORD)
    expect(written).not.toContain(SENTINEL_CODE)
    expect(written).not.toContain(SENTINEL_PIN)
    // 键面也不越界：落盘的键全部是仓内已登记键
    for (const [key] of calls) expect(ALL_STORAGE_KEYS).toContain(key)
  })

  it('🔴 判据 2b（类级）：本仓存储键面不许出现凭据形态的键名', () => {
    const literals = storageKeyLiterals()
    const all = new Set<string>([...ALL_STORAGE_KEYS, ...literals])

    // 反空跑：现取真的扫到了键（否则「没有凭据键」是空集恒真）
    expect(ALL_STORAGE_KEYS.length).toBeGreaterThanOrEqual(7)
    expect(literals.size).toBeGreaterThanOrEqual(3)

    const offenders = [...all].filter((key) => CREDENTIAL_KEY_RE.test(key))
    expect(offenders).toEqual([])
  })

  it('🔴 判据 2c（类级）：账号名三键只有 loginAccount.ts 一个读写点', () => {
    const direct = sourceFiles().filter((rel) => {
      if (rel === 'src/utils/constants.ts' || rel === 'src/utils/loginAccount.ts') return false
      const text = readSource(rel)
      return /LOGIN_ACCOUNT_(EMPLOYEE|ADMIN|WORKER)/.test(text) || /login_account_(employee|admin|worker)/.test(text)
    })

    expect(direct).toEqual([])
  })
})
