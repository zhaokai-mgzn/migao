// case_ids: PG-065, BM-045, BM-006
//
// 工人端登录的**服务端响应数据集**（issue #6747）—— 逐字取自生产实测，**不是**本包编的样例。
//
// 🔴 为什么独立成文件（**不是** `*.test.mjs`）：`tests/*.test.mjs` 由
//    `.github/workflows/worker-h5-tests.yml` 的 `node --test frontend/worker-h5/tests/*.test.mjs` 执行
//    ⇒ 数据集放 `*.mjs`（无 `.test.`）就**不会被当作用例文件执行**，同时可被用例文件
//    （`worker-h5-6747-auth-failed-copy.test.mjs`）与**跨模块元守卫**
//    （`tests/unit_ci_workflows/test_worker_h5_auth_failure_copy.py`，注在测试用例里的 mutation 用）共同复用。
//    ⇒ 「服务端给了什么」只有**一处**真值，两边不会各写一份而漂移（同族纪律：不新造第二套口径）。
//
// 复算（2026-10-11，本机与生产各跑过一次；两条输出逐字一致）：
//   curl -s -X POST https://app.migaozn.com/api/worker/login -H 'Content-Type: application/json' \
//     -d '{"workerNo":"wuitest","pin":"wrongpin","enterpriseCode":"migao"}'
//   ⇒ 401 {"success":false,"error":{"code":"AUTH_FAILED","message":"工号或 PIN 不正确"},"requestId":"…","timestamp":…}
//   curl -s -X POST https://app.migaozn.com/api/worker/login -H 'Content-Type: application/json' \
//     -d '{"employeeNo":"wuitest","pin":"UiTest246810","enterpriseCode":"migao"}'
//   ⇒ 422 {"success":false,"error":{"code":"VALIDATION_ERROR","message":"参数校验失败",
//        "details":[{"field":"workerNo","message":"工号不能为空"}]},"requestId":"…","timestamp":…}
//
// ⚠️ 字段契约 = `workerNo` + `pin`（`enterpriseCode` 可带）——`employeeNo` / `workNo` 都不是字段名
//    （用了就 422），以服务端为准。

/** 认证失败：企业编码不存在 / 工号不存在 / PIN 错 ⇒ **同一个 401、同一句**（反枚举口径，不许分辨是哪一项）。 */
export const AUTH_FAILED_401 = {
  success: false,
  error: { code: 'AUTH_FAILED', message: '工号或 PIN 不正确' },
}

/** 形状校验失败（#6738 已治的那一族）：顶层是内部术语，可行动理由在 `details[].message`。 */
export const VALIDATION_ERROR_422 = {
  success: false,
  error: { code: 'VALIDATION_ERROR', message: '参数校验失败', details: [{ field: 'pin', message: 'PIN 不能为空' }] },
}

/** 服务端在形状校验失败时回的**内部口径**（`GlobalExceptionHandler` 的 `MethodArgumentNotValidException` 分支）。 */
export const INTERNAL_WORDING = '参数校验失败'

/**
 * 泛化兜底话术（`frontend/worker-h5/src/api.mjs::transportMessage` 的末档）——issue #6747 的病灶本身：
 * 认证失败**不得**落到它（「请再试一次」会让打了错 PIN 的工人**反复重试**，而不是去核对）。
 */
export const GENERIC_RETRY_WORDING = '操作没成功（请再试一次；若反复如此请找管理员）'

/** 4xx/5xx 传输层「稍后重试」族（网络面口径，issue #6747 要求 3 必须**保持不变**）。 */
export const RETRY_TERMS = ['请过', '请再按', '稍后', '再试']
