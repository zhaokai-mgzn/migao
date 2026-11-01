/**
 * 工人登录表单（issue #8194）—— **与终端 `/w/` 的 `loginView()` 逐字同源**。
 *
 * ## 为什么是**一个**组件
 *
 * 同一张表单今天出现在三处：扫码报工页**未登录就地**、工人首页「去登录工人身份」落到的
 * `pages/worker/login/index`、（常规入口）三角色登录页的工人 tab（**本单不碰**）。
 * 前两处必须是**同一份**文案与字段顺序 —— 改前它们与 `/w/` 一处都不像（标题「工人登录」、
 * 副标题讲计件归属、多一格「设备标签」、配色是蓝色 #1a73e8），而两边的测试各自只断言自己那份，
 * 于是「两个端讲同一件事却像两个产品」永远不会变红。
 *
 * ⇒ 文案 / 字段顺序 / 错误位对齐 `/w/` 的 `loginView()`，**由一份共享组件承载**，
 * 并由 `tests/worker-login-parity.test.ts` 逐字比对（改一个标签 / 换顺序 ⇒ 红）。
 *
 * ## 口径（与 `/w/` 逐条对齐）
 *
 * | 项 | 值（真值 = `frontend/worker-h5/src/render.mjs::loginView`） |
 * |---|---|
 * | 标题 | {@link WORKER_LOGIN_TITLE} |
 * | 副标题 | {@link WORKER_LOGIN_SUBTITLE} |
 * | 字段顺序 | {@link WORKER_LOGIN_FIELDS}：企业编码（向商家索取）→ 工号 → PIN |
 * | 按钮 | {@link WORKER_LOGIN_SUBMIT_TEXT}（`登 录`，中间那个空格是文案的一部分） |
 * | 错误位 | 标题 / 副标题**之后、字段之前**（`/w/` 的 `.wh5-error` 同位） |
 *
 * 🔴 **不含「设备标签」字段**：`/w/` 没有它。设备标签只留在三角色登录页的工人 tab，
 * 属另一条链路（本单不改、也不让跨端判据把它钉成「必须像 `/w/`」）。
 *
 * ## 凭据纪律（沿用 #6478 / #7944，一格未放宽）
 *
 * **只**在登录成功后记「工号 + 企业编码」（输入便利，按登录面分键存）；
 * **PIN 绝不预填、绝不落盘**（共用 PAD 上更不能留凭据）。
 */
import { useCallback, useState } from 'react'
import { View, Text, Button, Input } from '@tarojs/components'
import {
  getRememberedAccount,
  getRememberedTenantCode,
  rememberAccount,
  rememberTenantCode,
} from '../utils/loginAccount'
import './WorkerLoginForm.scss'

/** 标题（`/w/` 的 `.wh5-title`） */
export const WORKER_LOGIN_TITLE = '工人报工'
/** 副标题（`/w/` 的 `.wh5-sub`） */
export const WORKER_LOGIN_SUBTITLE = '工号 + PIN 登录（手机 / PAD 均可，无需微信）'
/** 提交按钮文案（`/w/` 的 `.wh5-primary`；`登 录` 中间的空格是文案的一部分） */
export const WORKER_LOGIN_SUBMIT_TEXT = '登 录'
/** 服务端没给失败原因时的兜底（技术原文留在请求层） */
export const WORKER_LOGIN_FAILED_FALLBACK = '登录失败，请重试'
export const WORKER_LOGIN_NO_PIN_REQUIRED = '请输入工号与 PIN'
export const WORKER_LOGIN_ENTERPRISE_REQUIRED = '请输入企业编码（向商家索取）'

export interface WorkerLoginField {
  key: 'enterpriseCode' | 'workerNo' | 'pin'
  label: string
  testId: string
  /** PIN 遮蔽输入（`/w/` 的 `type="password"`） */
  password?: boolean
}

/**
 * 三个字段的**标签与顺序**（真值 = `/w/` 的 `loginView()`：企业编码 → 工号 → PIN）。
 * 跨端判据按这一份数组核顺序，所以顺序改动会同时被渲染面与源码面看见。
 */
export const WORKER_LOGIN_FIELDS: ReadonlyArray<WorkerLoginField> = [
  { key: 'enterpriseCode', label: '企业编码（向商家索取）', testId: 'worker-login-enterprise-code' },
  { key: 'workerNo', label: '工号', testId: 'worker-login-worker-no' },
  { key: 'pin', label: 'PIN', testId: 'worker-login-pin', password: true },
]

export interface WorkerLoginValues {
  enterpriseCode: string
  workerNo: string
  pin: string
}

export interface WorkerLoginSubmitResult {
  ok: boolean
  /** 失败时的可行动文案（服务端是文案单一真值；页面只透传） */
  message?: string
  /** 成功时的工人姓名（页面用它做 toast / 文案，不参与鉴权） */
  workerName?: string | null
}

export interface WorkerLoginFormProps {
  /** 提交（页面负责调 `workerLogin` 与登录后的去向；本组件只管表单与错误位） */
  onSubmit: (values: WorkerLoginValues) => Promise<WorkerLoginSubmitResult>
  /** 登录成功、且工号 / 企业编码已记下之后（页面在这里做导航） */
  onSuccess?: (result: WorkerLoginSubmitResult) => void
}

export default function WorkerLoginForm({ onSubmit, onSuccess }: WorkerLoginFormProps) {
  // 工号 / 企业编码预填「该面上次成功登录用过的值」；PIN 一律不预填
  const [values, setValues] = useState<WorkerLoginValues>(() => ({
    enterpriseCode: getRememberedTenantCode('worker'),
    workerNo: getRememberedAccount('worker'),
    pin: '',
  }))
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const submit = useCallback(async () => {
    if (submitting) return
    const workerNo = values.workerNo.trim()
    const pin = values.pin.trim()
    const enterpriseCode = values.enterpriseCode.trim()
    if (!workerNo || !pin) {
      setError(WORKER_LOGIN_NO_PIN_REQUIRED)
      return
    }
    if (!enterpriseCode) {
      setError(WORKER_LOGIN_ENTERPRISE_REQUIRED)
      return
    }
    setSubmitting(true)
    setError('')
    try {
      const result = await onSubmit({ workerNo, pin, enterpriseCode })
      if (!result.ok) {
        setError(result.message || WORKER_LOGIN_FAILED_FALLBACK)
        return
      }
      // 成功才记：工号 + 企业编码（PIN 绝不落盘）
      rememberAccount('worker', workerNo)
      rememberTenantCode('worker', enterpriseCode)
      onSuccess?.(result)
    } finally {
      setSubmitting(false)
    }
  }, [onSubmit, onSuccess, submitting, values])

  return (
    <View className='worker-login-form' data-testid='worker-login-form'>
      <Text className='worker-login-form__title'>{WORKER_LOGIN_TITLE}</Text>
      <Text className='worker-login-form__sub'>{WORKER_LOGIN_SUBTITLE}</Text>
      {error ? (
        <Text className='worker-login-form__error' data-testid='worker-login-error'>
          {error}
        </Text>
      ) : null}
      {WORKER_LOGIN_FIELDS.map((field) => (
        <View className='worker-login-form__field' key={field.key}>
          <Text className='worker-login-form__label'>{field.label}</Text>
          <Input
            className='worker-login-form__input'
            data-testid={field.testId}
            password={field.password}
            value={values[field.key]}
            onInput={(event: any) => {
              const next = event?.detail?.value ?? ''
              setValues((prev) => ({ ...prev, [field.key]: String(next) }))
            }}
            onConfirm={field.key === 'pin' ? submit : undefined}
          />
        </View>
      ))}
      <Button
        className='worker-login-form__submit'
        data-testid='worker-login-submit'
        loading={submitting}
        disabled={submitting}
        onClick={submit}
      >
        {WORKER_LOGIN_SUBMIT_TEXT}
      </Button>
    </View>
  )
}
